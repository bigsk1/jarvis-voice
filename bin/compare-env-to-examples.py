#!/usr/bin/env python3
"""
Compare active config/cloud.env & config/local.env against *.env.example.

- Ignores comments; strips inline `# ...` from unquoted values.
- Prints secret-like keys as <set>; scrubs credentials from proxy URLs.
- Does not print API keys or token values.

Usage:
  ./bin/compare-env-to-examples.py
  ./bin/compare-env-to-examples.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_env_assignments(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        val = val.strip()
        if "#" in val and not (val.startswith('"') or val.startswith("'")):
            val = re.sub(r"\s+#.*$", "", val).rstrip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            q = val[0]
            val = val[1:-1].replace("\\" + q, q)
        out[key] = val.strip()
    return out


def classify_secret(key: str) -> bool:
    kl = key.lower()
    needles = (
        "api_key",
        "apikey",
        "_key",
        "secret",
        "password",
        "passwd",
        "_pass",  # e.g. CRAWL4AI_PASS, VPS2_SUDO_PASS
        "_token",
        "credential",
        "webhook_auth",
        "sudo_pass",
    )
    if kl.endswith("_pass") or kl.endswith("_password"):
        return True
    if any(n in kl for n in needles):
        return True
    if kl.endswith("_auth_tokens"):
        return True
    if key in ("GITHUB_TOKEN", "HF_AUTH_TOKENS"):
        return True
    if key == "JARVIS_API_AUTH":  # may be bearer material
        return True
    # Voice/provider IDs are not cryptographic secrets but clutter diffs — hide in summaries
    if key.startswith("VAPI_") and key.endswith("_ID"):
        return True
    return False


def scrub_value(key: str, val: str) -> str:
    if classify_secret(key):
        return "<set>" if val else ""
    if key == "PHONE_CONTACTS":
        return "<contacts json>"
    if "PROXY" in key.upper():
        return re.sub(r"://[^:]+:[^@]+@", r"://***:***@", val)
    # common semi-secrets / long ids
    if "CLIENT_ID" in key or key.endswith("_ACCOUNT_ID"):
        if len(val) > 8:
            return "<id>"
        return val
    if len(val) > 140:
        return val[:137] + "..."
    return val


def categorize_key(key: str) -> str:
    if key in ("WAKE_GREETINGS", "SYSTEM_PROMPT"):
        return "persona"
    if any(
        p in key
        for p in (
            "_URL",
            "AUDIO_DIR",
            "CANVAS_",
            "DEVICE_",
            "IN_DEV",
            "OUT_DEV",
            "PRINTER_",
            "N8N_",
            "QWEN3_",
            "KOKORO_TTS_URL",
            "SAMANTHA_URL",
            "CRAWL4AI_URL",
            "SUPA_CRAWL_CHAT_URL",
        )
    ):
        return "network_device"
    if "JARVIS_DEFAULT_LOCATION" in key or "POSTAL_CODE" in key:
        return "network_device"
    if key == "OWNER_NAME":
        return "network_device"
    return "tuning"


def compare_one(label: str, example_p: Path, real_p: Path, as_json: bool) -> dict:
    ex = parse_env_assignments(example_p.read_text(encoding="utf-8", errors="replace"))
    rl = parse_env_assignments(real_p.read_text(encoding="utf-8", errors="replace"))

    vm = [(k, ex[k], rl[k]) for k in sorted(ex.keys() & rl.keys()) if ex[k].strip() != rl[k].strip()]
    only_real = sorted((k, rl[k]) for k in rl.keys() - ex.keys() if rl[k].strip())
    only_ex = sorted((k, ex[k]) for k in ex.keys() - rl.keys() if ex[k].strip())

    structured = {
        "label": label,
        "example_file": str(example_p.relative_to(ROOT)),
        "real_file": str(real_p.relative_to(ROOT)),
        "value_mismatches": [
            {
                "key": k,
                "category": categorize_key(k),
                "example": scrub_value(k, ev),
                "real": scrub_value(k, rv),
                "secret": classify_secret(k),
            }
            for k, ev, rv in vm
        ],
        "only_in_real": [
            {"key": k, "category": categorize_key(k), "value": scrub_value(k, v), "secret": classify_secret(k)}
            for k, v in only_real
        ],
        "only_in_example_nonempty": [
            {"key": k, "category": categorize_key(k), "example_value": scrub_value(k, v), "secret": classify_secret(k)}
            for k, v in only_ex
        ],
    }

    if as_json:
        return structured

    print(f"\n{'=' * 72}\n{label}: {real_p.relative_to(ROOT)}  vs  {example_p.relative_to(ROOT)}\n{'=' * 72}")
    print(
        f"Counts: differing values={len(vm)}, only in yours={len(only_real)}, "
        f"nonempty example-only={len(only_ex)}"
    )

    buckets: dict[str, list] = {"tuning": [], "network_device": [], "persona": []}
    for row in structured["value_mismatches"]:
        cat = row["category"]
        if cat in buckets:
            buckets[cat].append(row)

    for title, bid in ("Tuning / behavior defaults", "tuning"), ("Host / LAN / URLs / devices", "network_device"):
        rows = buckets[bid]
        if not rows:
            continue
        print(f"\n--- {title} ---")
        for r in rows:
            k = r["key"]
            print(f"  {k}: {r['example']} → {r['real']}")

    pers = buckets["persona"]
    if pers:
        print("\n--- Persona / long text ---")
        for r in pers:
            print(f"  {r['key']}: differs (length example vs real omitted; sanitize in editor)")

    sec_diffs = [r for r in structured["value_mismatches"] if r["secret"]]
    if sec_diffs:
        print("\n--- Secret-like keys (value hidden; both sides may differ) ---")
        for r in sec_diffs:
            print(f"  {r['key']}")

    if structured["only_in_real"]:
        print("\n--- Only in YOUR env (baseline gap for newcomers) ---")
        for r in structured["only_in_real"]:
            print(f"  {r['key']}={r['value']}")

    if structured["only_in_example_nonempty"]:
        print("\n--- Nonempty in EXAMPLE only (missing from YOUR file) ---")
        for r in structured["only_in_example_nonempty"]:
            print(f"  {r['key']}={r['example_value']}")

    return structured


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of human text")
    args = ap.parse_args()

    targets = [
        ("CLOUD", ROOT / "config/cloud.env.example", ROOT / "config/cloud.env"),
        ("LOCAL", ROOT / "config/local.env.example", ROOT / "config/local.env"),
    ]
    payload = []
    for label, ex, real in targets:
        if not real.is_file():
            print(f"[skip {label}] missing {real.relative_to(ROOT)}", file=sys.stderr)
            continue
        payload.append(compare_one(label, ex, real, args.json))

    if args.json:
        print(json.dumps(payload, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
