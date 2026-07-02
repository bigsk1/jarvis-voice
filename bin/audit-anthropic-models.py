#!/usr/bin/env python3
"""Audit Jarvis Anthropic metadata against the live Anthropic Models API.

Examples:
    ./bin/audit-anthropic-models.py --mode cloud
    ./bin/audit-anthropic-models.py --mode local --json

Exit codes:
    0  No API/catalog drift (warnings may still require review)
    1  Catalog drift detected
    2  Configuration, SDK, or API failure
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ensure_jarvis_python() -> None:
    """Re-exec direct CLI runs through Jarvis's external virtual environment."""
    expected_venv = Path(
        os.environ.get("JARVIS_VENV", str(Path.home() / "jarvis-venv"))
    ).expanduser().resolve()
    expected_python = expected_venv / "bin" / "python"
    active_prefix = Path(sys.prefix).expanduser().resolve()
    executable = Path(sys.executable).expanduser()
    if active_prefix == expected_venv or executable.is_relative_to(expected_venv):
        return
    if not expected_python.is_file():
        print(
            f"ERROR: Jarvis Python was not found at {expected_python}. "
            "Set JARVIS_VENV to the correct environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    os.execv(str(expected_python), [str(expected_python), str(Path(__file__).resolve()), *sys.argv[1:]])


if __name__ == "__main__":
    _ensure_jarvis_python()

sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from anthropic_model_audit import audit_anthropic_models
from config_loader import config_scope, get_config_value
from model_catalog import (
    ANTHROPIC_MODEL_AUDIT_IGNORES,
    ANTHROPIC_MODELS_SOURCE,
    ANTHROPIC_PRICING_SOURCE,
    get_provider_catalog,
)


def _print_human(report: dict[str, Any], mode: str) -> None:
    summary = report["summary"]
    print("Anthropic Model Catalog Audit")
    print(f"Mode/key source: {mode}")
    print(f"Checked: {report['checked_on']}")
    print(
        f"Models: {summary['api_models']} API / "
        f"{summary['catalog_models']} catalog"
    )
    print()

    if report["drift"]:
        print(f"DRIFT ({len(report['drift'])})")
        for item in report["drift"]:
            if item["type"] == "api_model_missing_from_catalog":
                print(f"  - New API model missing from Jarvis: {item['model_id']}")
            else:
                print(
                    f"  - {item['model_id']} {item['field']}: "
                    f"catalog={item['catalog']!r}, API={item['api']!r}"
                )
    else:
        print("OK: token limits and capabilities match the live API.")

    if report["warnings"]:
        print()
        print(f"WARNINGS ({len(report['warnings'])})")
        for item in report["warnings"]:
            warning_type = item["type"]
            if warning_type == "catalog_model_unavailable_to_key":
                detail = "not returned for this API key; review before removing"
            elif warning_type == "pricing_verification_stale":
                detail = f"pricing verification is {item['age_days']} days old"
            elif warning_type == "pricing_expired":
                detail = f"pricing validity ended {item['valid_until']}"
            elif warning_type == "pricing_not_verified":
                detail = "pricing has no verification date"
            elif warning_type == "missing_pricing_source":
                detail = "pricing has no source URL"
            elif warning_type == "missing_pricing":
                detail = "pricing metadata is missing"
            else:
                detail = warning_type.replace("_", " ")
            print(f"  - {item['model_id']}: {detail}")

    if report["ignored_api_models"]:
        print()
        print(f"INTENTIONALLY EXCLUDED ({len(report['ignored_api_models'])})")
        for item in report["ignored_api_models"]:
            print(f"  - {item['model_id']}: {item['reason']}")

    print()
    print("Pricing is curated separately because the Models API does not return it.")
    print(f"Models API: {ANTHROPIC_MODELS_SOURCE}")
    print(f"Pricing: {ANTHROPIC_PRICING_SOURCE}")


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"status": "error", "error": message}, indent=2))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare Jarvis Anthropic model metadata with the live Models API."
    )
    parser.add_argument(
        "--mode",
        choices=("cloud", "local"),
        default="cloud",
        help="Config env containing the Anthropic API key (default: cloud).",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    parser.add_argument(
        "--pricing-max-age-days",
        type=int,
        default=90,
        help="Warn when manually verified pricing is older than this (default: 90).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Anthropic API timeout in seconds (default: 30).",
    )
    args = parser.parse_args(argv)

    if args.pricing_max_age_days < 0:
        return _error("--pricing-max-age-days must be zero or greater", json_output=args.json)
    if args.timeout <= 0:
        return _error("--timeout must be greater than zero", json_output=args.json)

    try:
        from anthropic import Anthropic
    except ImportError:
        return _error(
            "anthropic>=0.115.0 is required; update the Jarvis environment first",
            json_output=args.json,
        )

    try:
        with config_scope(args.mode):
            api_key = str(get_config_value("ANTHROPIC_API_KEY", "") or "").strip()
            if not api_key:
                return _error(
                    f"ANTHROPIC_API_KEY is not configured in {args.mode}.env",
                    json_output=args.json,
                )
            models = list(Anthropic(api_key=api_key, timeout=args.timeout).models.list(limit=1000))
    except Exception as exc:
        return _error(f"Anthropic Models API request failed: {exc}", json_output=args.json)

    report = audit_anthropic_models(
        models,
        get_provider_catalog("anthropic"),
        ignored_api_models=ANTHROPIC_MODEL_AUDIT_IGNORES,
        pricing_max_age_days=args.pricing_max_age_days,
    )
    report["mode"] = args.mode
    report["sources"] = {
        "models": ANTHROPIC_MODELS_SOURCE,
        "pricing": ANTHROPIC_PRICING_SOURCE,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, args.mode)
    return 1 if report["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
