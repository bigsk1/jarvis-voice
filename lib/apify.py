"""One bounded Apify lifecycle for ordinary Actors, independent of Actor business schemas.

Actor details use the hosted MCP server; policy-filtered discovery and this
trusted submission/read boundary use the platform API. Submissions pin the
validated build, impose run limits and retain native handles. No operation
retries a state-changing request.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import requests
from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable
from urllib3.exceptions import HTTPError as UrllibHTTPError

from lib.config_loader import get_bool, get_config_value
from lib.http_client import http_request

API_BASE = "https://api.apify.com/v2"
TERMINAL = frozenset({"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"})
STATUSES = TERMINAL | {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}
MAX_INPUT_BYTES = 60 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9]{1,128}\Z")
_ACTOR = re.compile(r"[A-Za-z0-9_-]{1,80}/[A-Za-z0-9_-]{1,100}\Z")


class ApifyError(ValueError):
    """A nonsecret integration failure with explicit submission uncertainty."""

    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


def _number(key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(get_config_value(key, str(default)))
    except (TypeError, ValueError):
        raise ApifyError(f"{key} must be a finite number") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ApifyError(f"{key} must be between {minimum:g} and {maximum:g}")
    return value


@dataclass(frozen=True)
class ApifySettings:
    token: str = field(repr=False)
    run_seconds: int
    memory_mb: float
    max_charge_usd: float
    poll_seconds: float
    page_size: int
    allowed_actors: frozenset[str]

    @classmethod
    def load(cls, *, require_enabled: bool = True) -> ApifySettings:
        if require_enabled and not get_bool("APIFY_MCP_ENABLED", False):
            raise ApifyError("Apify is disabled. Enable APIFY_MCP_ENABLED in this mode first.")
        token = str(get_config_value("APIFY_TOKEN", "") or "").strip()
        if not token or any(char in token for char in "\r\n"):
            raise ApifyError("APIFY_TOKEN is missing or invalid in the selected mode")
        run_seconds = int(_number("APIFY_RUN_TIMEOUT_SECONDS", 1800, 1, 3300))
        # Preserve fractions until run preparation. Reads and recovery do not
        # allocate memory and must remain usable with an invalid start ceiling.
        memory_mb = _number("APIFY_MAX_MEMORY_MB", 2048, 128, 32768)
        page_size = int(_number("APIFY_RESULT_PAGE_SIZE", 20, 1, 100))
        allowed = frozenset(item.strip() for item in str(
            get_config_value("APIFY_ALLOWED_ACTORS", "") or "").split(",") if item.strip())
        if any(not (_ACTOR.fullmatch(item) or _ID.fullmatch(item)) for item in allowed):
            raise ApifyError("APIFY_ALLOWED_ACTORS must contain Actor IDs or username/name values")
        return cls(token, run_seconds, memory_mb,
                   _number("APIFY_MAX_CHARGE_USD", 1.0, 0.001, 1000),
                   _number("APIFY_POLL_SECONDS", 30, 1, 300), page_size, allowed)


def native_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ApifyError(f"Invalid Apify {label}")
    return value


def _run_memory(value: float, label: str) -> int:
    if (not 128 <= value <= 32768 or value != int(value)
            or int(value) & (int(value) - 1)):
        raise ApifyError(f"{label} must be a power of two between 128 and 32768 MiB")
    return int(value)


def actor_is_allowed(details: dict[str, Any], allowed_actors: frozenset[str]) -> bool:
    """Trust Apify's native owner identity or an exact operator-selected Actor.

    Ratings and adoption are selection evidence, not execution permission.
    This does not waive the independent schema, permission or resource checks.
    """
    actor_id = details.get("id")
    username, name = details.get("username"), details.get("name")
    canonical = f"{username}/{name}" if isinstance(username, str) and isinstance(name, str) else None
    return (username == "apify"
            or isinstance(actor_id, str) and actor_id in allowed_actors
            or canonical is not None and canonical in allowed_actors)


def _finite_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ApifyError("Apify input or output must be finite JSON") from None


def _invalid_constant(value: str):
    raise ValueError("Non-finite JSON")


class ApifyClient:
    """Fixed-origin, non-retrying platform calls; credentials never enter results."""

    def __init__(self, settings: ApifySettings | None = None, *, request=None):
        self.settings = settings or ApifySettings.load()
        self.request = request or http_request

    def _request(self, method: str, path: str, *, params=None, body=None,
                 missing_ok: bool = False, submission: bool = False,
                 binary: bool = False) -> Any:
        # All paths are assembled below from validated IDs, not returned URLs.
        response = None
        deadline = time.monotonic() + 20
        try:
            response = self.request(method, API_BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + self.settings.token},
                proxy_policy="off", timeout=10, stream=True, allow_redirects=False)
            if response.status_code == 404 and missing_ok:
                return None
            if not 200 <= response.status_code < 300:
                raise ApifyError(f"Apify returned HTTP {response.status_code}",
                                 uncertain=submission and (response.status_code >= 500 or response.status_code == 408))
            payload = bytearray()
            read1 = getattr(getattr(response, "raw", None), "read1", None)
            chunks = iter(lambda: read1(65536, decode_content=True), b"") if callable(read1) else response.iter_content(chunk_size=65536)
            for chunk in chunks:
                if time.monotonic() >= deadline:
                    raise ApifyError("Apify response exceeded its observation budget", uncertain=submission)
                payload.extend(chunk)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ApifyError("Apify response exceeded the 8 MiB limit",
                                     uncertain=submission)
            if binary:
                return bytes(payload), response.headers.get("Content-Type", "application/octet-stream")
            try:
                result = json.loads(bytes(payload), parse_constant=_invalid_constant)
            except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
                raise ApifyError("Apify returned invalid JSON", uncertain=submission) from None
            return result
        except (requests.RequestException, UrllibHTTPError, OSError):
            raise ApifyError("Apify connection failed; check the same run before retrying.",
                             uncertain=submission) from None
        finally:
            if response is not None:
                response.close()

    def _object(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        payload = self._request(method, path, **kwargs)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ApifyError("Apify returned invalid metadata", uncertain=kwargs.get("submission", False))
        return data

    def get_actor(self, actor: Any) -> dict[str, Any]:
        """Read native Actor identity; neither a display badge nor input grants trust."""
        if not isinstance(actor, str) or not (_ACTOR.fullmatch(actor) or _ID.fullmatch(actor)):
            raise ApifyError("Use an Actor ID or username/name; MCP-server Actor tools are unsupported")
        details = self._object("GET", "/acts/" + actor.replace("/", "~"))
        actor_id = native_id(details.get("id"), "Actor ID")
        canonical = f"{details.get('username', '')}/{details.get('name', '')}"
        if actor not in (actor_id, canonical):
            raise ApifyError("Apify returned mismatched Actor identity")
        return details

    def prepare(self, actor: Any, actor_input: Any) -> dict[str, Any]:
        """Resolve an eligible Actor/build and validate its original schema offline."""
        if not isinstance(actor_input, dict) or len(_finite_json(actor_input)) > MAX_INPUT_BYTES:
            raise ApifyError("Actor input must be a JSON object of at most 60 KiB")
        memory_cap = _run_memory(self.settings.memory_mb, "APIFY_MAX_MEMORY_MB")
        details = self.get_actor(actor)
        actor_id = native_id(details.get("id"), "Actor ID")
        canonical_name = f"{details.get('username', '')}/{details.get('name', '')}"
        if not actor_is_allowed(details, self.settings.allowed_actors):
            raise ApifyError("This Actor is not maintained by Apify or explicitly trusted in APIFY_ALLOWED_ACTORS")
        if details.get("actorPermissionLevel") != "LIMITED_PERMISSIONS":
            raise ApifyError("Only limited-permission Apify Actors are supported")
        if (details.get("actorStandby") or {}).get("isEnabled") is True:
            raise ApifyError("Standby/MCP-server Actors do not use the supported run lifecycle")
        build = self._object("GET", f"/acts/{actor_id}/builds/default")
        build_id = native_id(build.get("id"), "build ID")
        if build.get("actId") != actor_id or build.get("status") != "SUCCEEDED":
            raise ApifyError("The Actor has no verified successful default build")
        definition = build.get("actorDefinition") or {}
        schema = definition.get("input") if isinstance(definition, dict) else None
        if not isinstance(schema, dict):
            schema = build.get("inputSchema")
            if isinstance(schema, str):
                try:
                    schema = json.loads(schema, parse_constant=_invalid_constant)
                except (TypeError, ValueError, RecursionError):
                    raise ApifyError("The Actor input schema is invalid") from None
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ApifyError("The Actor does not advertise a usable object input schema")
        try:
            Draft7Validator.check_schema(schema)
            Draft7Validator(schema, registry=Registry()).validate(actor_input)
        except (SchemaError, ValidationError, Unresolvable):
            # Do not echo the rejected input, which can include site credentials.
            raise ApifyError("Actor input does not match its build's schema; inspect Actor details") from None
        build_number = build.get("buildNumber")
        if not isinstance(build_number, str) or not re.fullmatch(r"\d+\.\d+\.\d+", build_number):
            raise ApifyError("The Actor build number could not be pinned")
        minimum = definition.get("minMemoryMbytes", 128) if isinstance(definition, dict) else 128
        default_memory = details.get("defaultRunOptions", {}).get("memoryMbytes", 1024)
        if type(minimum) is not int or minimum > memory_cap:
            raise ApifyError("The Actor requires more memory than APIFY_MAX_MEMORY_MB")
        memory = _run_memory(min(memory_cap,
            max(minimum, default_memory if type(default_memory) is int else 1024)),
            "Actor memory allocation")
        return {"actor_id": actor_id, "actor_name": canonical_name, "build_id": build_id,
                "build_number": build_number, "memory_mb": memory, "input": actor_input}

    def start(self, prepared: dict[str, Any]) -> dict[str, str]:
        """One POST only. A lost receipt is uncertain and is never resubmitted."""
        run = self._object("POST", f"/acts/{native_id(prepared['actor_id'], 'Actor ID')}/runs",
            params={"build": prepared["build_number"], "timeout": self.settings.run_seconds,
                    "memory": prepared["memory_mb"], "maxTotalChargeUsd": self.settings.max_charge_usd,
                    "waitForFinish": 0, "restartOnError": "false",
                    "forcePermissionLevel": "LIMITED_PERMISSIONS"},
            body=prepared["input"], submission=True)
        try:
            checkpoint = {"run_id": native_id(run.get("id"), "run ID"),
                          "actor_id": prepared["actor_id"], "build_id": prepared["build_id"]}
        except ApifyError:
            raise ApifyError("Apify submission returned no usable native run handle; do not resubmit.",
                             uncertain=True) from None
        for upstream, key in (("defaultDatasetId", "default_dataset_id"),
                              ("defaultKeyValueStoreId", "default_key_value_store_id")):
            value = run.get(upstream)
            if isinstance(value, str) and _ID.fullmatch(value):
                checkpoint[key] = value
        # Expected validated identities stay authoritative. Later reads verify
        # them, and a malformed optional receipt cannot erase a usable run ID.
        return checkpoint

    def get_run(self, run_id: str, *, expected_actor: str | None = None) -> dict[str, Any]:
        run_id = native_id(run_id, "run ID")
        run = self._object("GET", f"/actor-runs/{run_id}")
        if run.get("id") != run_id or run.get("status") not in STATUSES:
            raise ApifyError("Apify returned mismatched run metadata")
        if expected_actor and run.get("actId") != expected_actor:
            raise ApifyError("Apify returned a different Actor for the saved run")
        return run

    def abort(self, run_id: str) -> None:
        # Requesting abortion is not confirmation. The observer must re-read status.
        self._object("POST", f"/actor-runs/{native_id(run_id, 'run ID')}/abort",
                     params={"gracefully": "true"})

    @staticmethod
    def storages(run: dict[str, Any], kind: str) -> dict[str, str]:
        result = dict((run.get("storageIds") or {}).get(kind) or {})
        primary = run.get("defaultDatasetId" if kind == "datasets" else "defaultKeyValueStoreId")
        if primary:
            result.setdefault("default", primary)
        return {key: native_id(value, "storage ID") for key, value in result.items()}

    def dataset(self, dataset_id: str, *, offset: int = 0, limit: int = 20,
                fields: str | None = None) -> tuple[dict, list]:
        dataset_id = native_id(dataset_id, "dataset ID")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ApifyError("Dataset pages require offset >= 0 and limit between 1 and 100")
        if fields is not None and (not isinstance(fields, str) or len(fields) > 1000):
            raise ApifyError("Invalid dataset fields")
        meta = self._object("GET", f"/datasets/{dataset_id}")
        params = {"offset": offset, "limit": limit, "format": "json", "clean": "false"}
        if fields:
            params["fields"] = fields
        items = self._request("GET", f"/datasets/{dataset_id}/items", params=params)
        if not isinstance(items, list):
            raise ApifyError("Apify returned an invalid dataset page")
        if len(items) > limit:
            raise ApifyError("Apify returned more records than requested")
        return meta, items

    def result(self, run: dict[str, Any], *, action: str = "status", dataset_id: str | None = None,
               offset: int = 0, limit: int | None = None, fields: str | None = None,
               record_key: str = "OUTPUT") -> dict[str, Any]:
        from lib.external_results import make_external_result_data

        run_id = native_id(run.get("id"), "run ID")
        datasets = self.storages(run, "datasets")
        stores = self.storages(run, "keyValueStores")
        execution = {"run_id": run_id, "actor_id": run.get("actId"), "build_id": run.get("buildId"),
                     "status": run["status"], "datasets": datasets, "key_value_stores": stores}
        result: dict[str, Any] = {"kind": "object", "value": {
            "status": run["status"], "status_message": run.get("statusMessage"),
            "started_at": run.get("startedAt"), "finished_at": run.get("finishedAt")},
            "complete": run["status"] in TERMINAL}
        raw: Any = {"run": run}
        if action == "dataset":
            selected = dataset_id or datasets.get("default")
            if selected not in datasets.values():
                raise ApifyError("Select a dataset belonging to this run")
            limit = self.settings.page_size if limit is None else limit
            meta, items = self.dataset(selected, offset=offset, limit=limit, fields=fields)
            total = meta.get("itemCount")
            total = total if type(total) is int and total >= 0 else None
            complete = run["status"] in TERMINAL and offset == 0 and total is not None and len(items) >= total
            result = {"kind": "dataset", "dataset_id": selected, "sample_items": items,
                "sample_count": len(items), "returned_count": len(items), "total_items": total,
                "offset": offset, "limit": limit, "complete": complete,
                "pagination": {"tool": "apify_read_result", "action": "dataset", "run_id": run_id,
                    "has_more": total is None or offset + len(items) < total,
                    "dataset_id": selected, "next_offset": offset + len(items)
                    if items and (total is None or offset + len(items) < total) else None}}
            raw = {"run": run, "dataset": meta, "offset": offset, "items": items}
        elif action == "record":
            if not isinstance(record_key, str) or not 1 <= len(record_key) <= 256:
                raise ApifyError("A record key must contain 1–256 characters")
            store_id = stores.get("default")
            if not store_id:
                raise ApifyError("This run has no default key-value store")
            record = self._request("GET", f"/key-value-stores/{store_id}/records/{quote(record_key, safe='')}",
                                   binary=True, missing_ok=True)
            if record is None:
                raise ApifyError("The requested record does not exist")
            content, mime = record
            try:
                value = json.loads(content, parse_constant=_invalid_constant)
                result = {"kind": "object", "value": value, "complete": True,
                          "key_value_store_id": store_id, "record_key": record_key}
                raw = {"run": run, "record": value}
            except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
                from lib.stash_helper import StashFile, open_space
                space, _ = open_space(scope="session", labels=["apify", "external_result"])
                saved = StashFile(space).save_binary(content, name="apify-record.bin", mime_type=mime,
                    tool_origin="apify_read_result")
                result = {"kind": "file", "complete": True, "record_key": record_key,
                          "key_value_store_id": store_id}
                data = make_external_result_data(provider="apify", tool="apify_read_result",
                    execution=execution, result=result, artifacts=[{"ref": saved["ref"], "mime_type": mime,
                    "title": record_key}], raw_payload={"run": run}, raw_ref=saved["ref"])
                return {"ok": True, "speech": "Apify record saved to Stash.", "data": data}
        elif action != "status":
            raise ApifyError("Unknown Apify result action")
        data = make_external_result_data(provider="apify", tool="apify_read_result",
            execution=execution, result=result, raw_payload=raw)
        status = run["status"]
        if action == "dataset":
            speech = f"Apify run {status}. Retrieved {result['returned_count']} dataset records."
            if not result["complete"]:
                speech += " This is a page, not the complete dataset."
        else:
            speech = f"Apify run {status}."
        if status not in TERMINAL:
            speech += " The run is not finished. Check this run ID; do not start it again."
        return {"ok": status not in {"FAILED", "TIMED-OUT", "ABORTED"}, "speech": speech, "data": data}


def run_actor(arguments: dict[str, Any], *, checkpoint: Callable[[], None] | None = None,
              client: ApifyClient | None = None) -> dict[str, Any]:
    """Foreground submission returns a native handle, never a background receipt."""
    client = client or ApifyClient()
    prepared = client.prepare(arguments.get("actor"), arguments.get("input"))
    if checkpoint:
        checkpoint()
    handle = client.start(prepared)
    from lib.external_results import make_external_result_data
    return {"ok": True, "speech": "Apify accepted the Actor run. It is not confirmed complete. "
        "Use apify_read_result with the returned run_id to check status; do not submit it again.",
        "data": make_external_result_data(provider="apify", tool="apify_run_actor",
            execution={**handle, "status": "SUBMITTED"}, result={"kind": "object", "complete": False},
            raw_payload={"checkpoint": handle})}


def read_result(arguments: dict[str, Any], *, client: ApifyClient | None = None) -> dict[str, Any]:
    client = client or ApifyClient()
    run = client.get_run(arguments.get("run_id"))
    return client.result(run, action=arguments.get("action", "status"),
        dataset_id=arguments.get("dataset_id"), offset=arguments.get("offset", 0),
        limit=arguments.get("limit"), fields=arguments.get("fields"),
        record_key=arguments.get("record_key", "OUTPUT"))
