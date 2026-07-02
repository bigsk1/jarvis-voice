#!/usr/bin/env python3
"""Audit Jarvis xAI chat metadata against the live xAI REST model APIs.

Examples:
    ./bin/audit-xai-models.py --mode cloud
    ./bin/audit-xai-models.py --mode local --json

Exit codes: 0 clean, 1 drift, 2 configuration/API failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
XAI_API_BASE = "https://api.x.ai/v1"


def _ensure_jarvis_python() -> None:
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

from config_loader import config_scope, get_config_value
from model_catalog import XAI_MODEL_AUDIT_IGNORES, XAI_MODELS_SOURCE, get_provider_catalog
from xai_model_audit import audit_xai_models


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"status": "error", "error": message}, indent=2))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    return 2


def _print_human(report: dict[str, Any], mode: str) -> None:
    summary = report["summary"]
    print("xAI Model Catalog Audit")
    print(f"Mode/key source: {mode}")
    print(f"Checked: {report['checked_at']}")
    print(
        f"Models: {summary['api_language_models']} API language / "
        f"{summary['catalog_models']} catalog"
    )
    print()
    if report["drift"]:
        print(f"DRIFT ({len(report['drift'])})")
        for item in report["drift"]:
            if item["type"] == "api_model_missing_from_catalog":
                detail = "new API language model missing from Jarvis"
            elif item["type"] == "model_metadata_mismatch":
                detail = f"{item['field']} differs: catalog={item['catalog']!r}, API={item['api']!r}"
            elif item["type"] == "catalog_aliases_not_reported_by_api":
                detail = f"catalog aliases no longer reported: {', '.join(item['aliases'])}"
            else:
                detail = item["type"].replace("_", " ")
            print(f"  - {item['model_id']}: {detail}")
    else:
        print("OK: context, modalities, aliases, and pricing match the live APIs.")

    if report["warnings"]:
        print()
        print(f"WARNINGS ({len(report['warnings'])})")
        for item in report["warnings"]:
            print(f"  - {item['model_id']}: not returned for this API key; review before removing")

    if report["ignored_api_models"]:
        print()
        print(f"INTENTIONALLY EXCLUDED ({len(report['ignored_api_models'])})")
        for item in report["ignored_api_models"]:
            print(f"  - {item['model_id']}: {item['reason']}")

    print()
    print(f"API reference: {XAI_MODELS_SOURCE}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare Jarvis xAI chat metadata with the live xAI model APIs."
    )
    parser.add_argument(
        "--mode",
        choices=("cloud", "local"),
        default="cloud",
        help="Config env containing XAI_API_KEY (default: cloud).",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout (default: 30).")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        return _error("--timeout must be greater than zero", json_output=args.json)

    try:
        import requests

        with config_scope(args.mode):
            api_key = str(get_config_value("XAI_API_KEY", "") or "").strip()
            if not api_key:
                return _error(
                    f"XAI_API_KEY is not configured in {args.mode}.env",
                    json_output=args.json,
                )
            headers = {"Authorization": f"Bearer {api_key}"}
            basic_response = requests.get(
                f"{XAI_API_BASE}/models", headers=headers, timeout=args.timeout
            )
            language_response = requests.get(
                f"{XAI_API_BASE}/language-models", headers=headers, timeout=args.timeout
            )
            basic_response.raise_for_status()
            language_response.raise_for_status()
            basic_models = basic_response.json().get("data", [])
            language_models = language_response.json().get("models", [])
    except Exception as exc:
        return _error(f"xAI model API request failed: {exc}", json_output=args.json)

    report = audit_xai_models(
        basic_models,
        language_models,
        get_provider_catalog("xai"),
        ignored_api_models=XAI_MODEL_AUDIT_IGNORES,
    )
    report["mode"] = args.mode
    report["source"] = XAI_MODELS_SOURCE
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, args.mode)
    return 1 if report["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
