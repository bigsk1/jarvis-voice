"""Bounded, explicit normalization for durable watch observations."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_RECORDS = 1000
MAX_JSON_BYTES = 2_000_000
MAX_RECORD_BYTES = 16_384
MAX_DEPTH = 12
MAX_PAGE = 1000
MAX_SNAPSHOT_RECORDS = 20_000
SHARED_RADAR_KEYS = frozenset({"upcoming_movie_radar", "upcoming_tv_radar"})


class WatchStateError(ValueError):
    """A safe error suitable for the watch-state API/tool boundary."""


class ValidationError(WatchStateError):
    pass


class NotFoundError(WatchStateError):
    pass


class AuthorityError(WatchStateError, PermissionError):
    pass


class ConflictError(WatchStateError):
    pass


class StorageError(WatchStateError):
    pass


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def validate_json(value: Any, *, maximum: int = MAX_JSON_BYTES) -> None:
    def visit(item: Any, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ValidationError("JSON nesting exceeds the watch-state limit.")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ValidationError("Nonfinite numbers are not supported.")
            return
        if isinstance(item, dict):
            if len(item) > 200 or any(not isinstance(key, str) for key in item):
                raise ValidationError("JSON objects require string keys and at most 200 fields.")
            for child in item.values():
                visit(child, depth + 1)
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        raise ValidationError("Records must contain only JSON values.")

    visit(value, 0)
    try:
        size = len(json_text(value).encode("utf-8"))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Records must be valid finite UTF-8 JSON.") from exc
    if size > maximum:
        raise ValidationError("JSON exceeds the watch-state size limit.")


def bounded_string(value: Any, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValidationError(f"{name} must be a nonempty bounded string without control characters.")
    return value


def validate_key(key: Any) -> str:
    key = bounded_string(key, "key", 160)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", key) or ".." in key.split("/"):
        raise ValidationError("key must be a safe watch identifier.")
    return key


def _path(value: Any) -> str:
    value = bounded_string(value, "field path", 200)
    if any(not part for part in value.split(".")):
        raise ValidationError("Field paths must contain nonempty dot-separated names.")
    return value


def get_field(record: dict, path: str, default: Any = None) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _set_field(record: dict, path: str, value: Any) -> None:
    target = record
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _remove_field(record: dict, path: str) -> None:
    target: Any = record
    parts = path.split(".")
    parents = []
    for part in parts[:-1]:
        if not isinstance(target, dict):
            return
        parents.append((target, part))
        target = target.get(part)
    if isinstance(target, dict):
        target.pop(parts[-1], None)
        for parent, part in reversed(parents):
            if parent.get(part) == {}:
                parent.pop(part)
            else:
                break


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{name} must be an integer from {minimum} to {maximum}.")
    return value


def normalize_definition(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("definition must be an object.")
    allowed = {"id_field", "compare_fields", "ignore_fields", "normalizers", "schema_version", "complete",
               "missing_grace", "quiet_first", "retention_days", "stale_after_seconds", "channels"}
    if set(value) - allowed:
        raise ValidationError("Definition contains unsupported fields; thresholds are not implemented.")
    validate_json(value, maximum=32_000)
    result: dict[str, Any] = {"id_field": _path(value.get("id_field"))}
    for name in ("compare_fields", "ignore_fields"):
        fields = value.get(name, [])
        if not isinstance(fields, list) or len(fields) > 100:
            raise ValidationError(f"{name} must be a list of at most 100 field paths.")
        result[name] = sorted({_path(field) for field in fields})
    if any(field == ignored or field.startswith(ignored + ".")
           for field in result["compare_fields"] for ignored in result["ignore_fields"]):
        raise ValidationError("A compared field cannot be hidden by an ignored field or ancestor.")
    normalizers = value.get("normalizers", {})
    if not isinstance(normalizers, dict) or len(normalizers) > 100:
        raise ValidationError("normalizers must map at most 100 fields to explicit normalizers.")
    result["normalizers"] = {}
    for field, spec in normalizers.items():
        field = _path(field)
        identity = result["id_field"]
        if field == identity or field.startswith(identity + ".") or identity.startswith(field + "."):
            raise ValidationError("Record identities cannot be normalized.")
        spec = {"type": spec} if isinstance(spec, str) else deepcopy(spec)
        if not isinstance(spec, dict) or set(spec) - {"type", "currency"} or spec.get("type") not in {"money", "number", "text", "date"}:
            raise ValidationError("Normalizers must specify money, number, text or date.")
        if "currency" in spec:
            if spec["type"] != "money" or not isinstance(spec["currency"], str) or not re.fullmatch(r"[A-Z]{3}", spec["currency"]):
                raise ValidationError("Only money normalizers accept an explicit uppercase currency code.")
        result["normalizers"][field] = spec
    for name, default in (("complete", False), ("quiet_first", True)):
        result[name] = value.get(name, default)
        if type(result[name]) is not bool:
            raise ValidationError(f"{name} must be a boolean.")
    for name, default, minimum, maximum in (
        ("schema_version", 1, 1, 1_000_000), ("missing_grace", 2, 1, 100),
        ("retention_days", 90, 1, 3650), ("stale_after_seconds", 0, 0, 315_360_000),
    ):
        result[name] = _integer(value.get(name, default), name, minimum, maximum)
    channels = value.get("channels", [])
    if not isinstance(channels, list) or len(channels) > 8:
        raise ValidationError("channels must contain at most 8 delivery destinations.")
    result["channels"] = []
    for entry in channels:
        if not isinstance(entry, dict) or set(entry) != {"channel", "destination"}:
            raise ValidationError("Each channel requires exactly channel and destination.")
        channel = bounded_string(entry["channel"], "channel", 40)
        destination = bounded_string(entry["destination"], "destination", 1024)
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", channel):
            raise ValidationError("channel must be a lowercase channel name.")
        normalized = {"channel": channel, "destination": destination}
        if normalized not in result["channels"]:
            result["channels"].append(normalized)
    result["channels"].sort(key=lambda row: (row["channel"], row["destination"]))
    return result


def _decimal(value: Any) -> str:
    if type(value) not in (str, int, float, Decimal):
        raise ValidationError("A number normalizer requires a numeric value or decimal string.")
    text = str(value).strip()
    if not re.fullmatch(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d{1,4})?", text):
        raise ValidationError("Numbers require unambiguous decimal notation; commas may separate thousands.")
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise ValidationError("A normalizer received an invalid decimal number.") from exc
    if not number.is_finite() or abs(number.adjusted()) > 1000:
        raise ValidationError("Nonfinite numbers are not supported.")
    if number == 0:
        return "0"
    return format(number, "f").rstrip("0").rstrip(".") if "." in format(number, "f") else format(number, "f")


def _normalize(value: Any, spec: dict) -> Any:
    if value is None:
        return None
    kind = spec["type"]
    if kind == "number":
        return _decimal(value)
    if kind == "money":
        currency = spec.get("currency")
        if isinstance(value, dict):
            if set(value) != {"amount", "currency"} or not re.fullmatch(r"[A-Z]{3}", str(value.get("currency", ""))):
                raise ValidationError("Money objects require amount and an uppercase currency code.")
            if currency and value["currency"] != currency:
                raise ValidationError("Money currency does not match the explicit normalizer.")
            currency, value = value["currency"], value["amount"]
        if isinstance(value, str) and currency:
            value = value.strip()
            if value.startswith(currency + " "):
                value = value[len(currency):].strip()
            symbol = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(currency)
            if symbol and value.startswith(symbol):
                value = value[len(symbol):].strip()
        amount = _decimal(value)
        return {"amount": amount, "currency": currency} if currency else amount
    if not isinstance(value, str):
        raise ValidationError("Text and date normalizers require strings.")
    if kind == "text":
        return " ".join(value.split()).casefold()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Missing timezone")
        return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError as exc:
        raise ValidationError("Dates require an ISO date or an ISO timestamp with an explicit timezone.") from exc


def normalize_records(records: Any, definition: dict) -> dict[str, dict]:
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValidationError(f"records must be a list of at most {MAX_RECORDS} objects.")
    validate_json(records)
    result = {}
    missing = object()
    for record in records:
        if not isinstance(record, dict):
            raise ValidationError("Each record must be an object.")
        if len(json_text(record).encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValidationError("Each record is limited to 16 KiB; keep large content in Stash and watch its reference.")
        identifier = get_field(record, definition["id_field"], missing)
        if type(identifier) is int:
            identifier = str(identifier)
        identifier = bounded_string(identifier, "record identity", 256)
        if identifier in result:
            raise ValidationError("Duplicate record identities are not supported.")
        normalized = deepcopy(record)
        for field, spec in definition["normalizers"].items():
            value = get_field(normalized, field, missing)
            if value is not missing:
                _set_field(normalized, field, _normalize(value, spec))
        if len(json_text(normalized).encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValidationError("Normalized records are limited to 16 KiB; watch a Stash reference instead.")
        result[identifier] = normalized
    validate_json(list(result.values()))
    return result


def comparison_value(record: dict, definition: dict) -> dict:
    value = deepcopy(record)
    for field in definition["ignore_fields"]:
        _remove_field(value, field)
    if definition["compare_fields"]:
        missing = object()
        return {field: result for field in definition["compare_fields"]
                if (result := get_field(value, field, missing)) is not missing}
    _remove_field(value, definition["id_field"])
    return value
