#!/usr/bin/env python3
"""Audit Jarvis OpenAI chat options against the live OpenAI Models API.

Examples:
    ./bin/audit-openai-models.py --mode cloud
    ./bin/audit-openai-models.py --mode local --json

Exit codes: 0 clean, 1 new general model family needs review, 2 config/API failure.
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
from model_catalog import OPENAI_MODELS_SOURCE, get_provider_catalog
from openai_model_audit import audit_openai_models


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"status": "error", "error": message}, indent=2))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    return 2


def _print_human(report: dict[str, Any], mode: str, *, show_all: bool) -> None:
    summary = report["summary"]
    print("OpenAI Model Catalog Audit")
    print(f"Mode/key source: {mode}")
    print(f"Checked: {report['checked_at']}")
    print(f"Models: {summary['api_models']} API / {summary['catalog_models']} catalog")
    print()

    if report["review_candidates"]:
        print(f"REVIEW REQUIRED ({len(report['review_candidates'])})")
        for candidate in report["review_candidates"]:
            variants = ", ".join(model["id"] for model in candidate["models"])
            print(f"  - {candidate['family']}: {variants}")
    else:
        print("OK: no newer general-purpose GPT family needs catalog review.")

    if report["warnings"]:
        print()
        print(f"WARNINGS ({len(report['warnings'])})")
        for item in report["warnings"]:
            print(f"  - {item['model_id']}: not returned for this API key")

    if show_all:
        print()
        print(f"ALL API MODELS ({len(report['api_models'])})")
        for model in report["api_models"]:
            print(f"  - {model['id']} ({model['owned_by']})")

    print()
    print(report["api_note"])
    print(f"API reference: {OPENAI_MODELS_SOURCE}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare Jarvis OpenAI chat options with the live Models API."
    )
    parser.add_argument(
        "--mode",
        choices=("cloud", "local"),
        default="cloud",
        help="Config env containing OPENAI_API_KEY (default: cloud).",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    parser.add_argument("--show-all", action="store_true", help="List every API model in text output.")
    parser.add_argument("--timeout", type=float, default=30.0, help="API timeout (default: 30).")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        return _error("--timeout must be greater than zero", json_output=args.json)

    try:
        from openai import OpenAI

        with config_scope(args.mode):
            api_key = str(get_config_value("OPENAI_API_KEY", "") or "").strip()
            if not api_key:
                return _error(
                    f"OPENAI_API_KEY is not configured in {args.mode}.env",
                    json_output=args.json,
                )
            models = list(OpenAI(api_key=api_key, timeout=args.timeout).models.list())
    except Exception as exc:
        return _error(f"OpenAI Models API request failed: {exc}", json_output=args.json)

    report = audit_openai_models(models, get_provider_catalog("openai"))
    report["mode"] = args.mode
    report["source"] = OPENAI_MODELS_SOURCE
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, args.mode, show_all=args.show_all)
    return 1 if report["review_candidates"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
