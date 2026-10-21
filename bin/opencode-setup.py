#!/usr/bin/env python3
"""Prepare or verify the independently supervised OpenCode 2 service.

Uses only the standard library so fresh hosts do not need a Python environment
before creating service configuration. Never executes dotenv contents.
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import grp
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_KEYS = {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "OLLAMA_API_KEY",
    "OPENCODE_SERVER_USERNAME", "OPENCODE_SERVER_PASSWORD",
    "JARVIS_WORKSPACE_ROOT", "JARVIS_VOICE_ROOT",
}
UNIT_MANAGED_ENV = {
    "PATH", "TMPDIR", "TMP", "TEMP", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
    "XDG_STATE_HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "npm_config_cache",
    "NPM_CONFIG_CACHE", "UV_CACHE_DIR", "CARGO_HOME", "GOPATH", "GOCACHE", "GOMODCACHE",
}
LEGACY_DISABLED_PROVIDERS = [
    "cloudflare-workers", "amazon-bedrock", "nvidia", "workers-ai", "bedrock", "huggingface",
]


def read_env(path: Path, *, systemd: bool = False) -> dict[str, str]:
    """Read Jarvis's literal single-line dotenv format, without shell expansion."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text().splitlines():
        match = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)$", raw.strip())
        if not match:
            continue
        key, value = match.groups()
        if value.startswith(('"', "'")) and value.endswith(value[0]):
            value = json.loads(value) if systemd and value.startswith('"') else value[1:-1]
        else:
            value = re.sub(r"\s+#.*$", "", value).strip()
        result[key] = value
    return result


def selected_env(explicit: str | None) -> Path:
    if explicit:
        source = Path(explicit).expanduser()
    elif os.environ.get("OPENCODE_ENV_FILE"):
        source = Path(os.environ["OPENCODE_ENV_FILE"]).expanduser()
    else:
        mode = os.environ.get("JARVIS_MODE", "cloud")
        if mode not in {"cloud", "local"}:
            raise ValueError("JARVIS_MODE must be cloud or local")
        source = ROOT / "config" / f"{mode}.env"
    if not source.is_file():
        raise ValueError(f"Source env file not found: {source}")
    return source


def config_dir() -> Path:
    return Path.home() / ".config" / "opencode"


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def backup_config(path: Path, content: str) -> Path:
    backup = path.with_suffix(path.suffix + ".v1-backup")
    if backup.exists() and backup.read_text() != content:
        backup = backup.with_name(backup.name + f".{time.time_ns()}")
    if not backup.exists():
        atomic_write(backup, content)
    return backup


def prepare_env(source: Path) -> None:
    target = config_dir() / "jarvis-env.env"
    values = read_env(target, systemd=True)
    source_values = read_env(source)
    # Keep existing optional credentials/settings; explicit source values win.
    values.update({key: value for key, value in source_values.items() if key in RUNTIME_KEYS})
    removed = sorted(values.keys() & UNIT_MANAGED_ENV)
    for key in removed:
        del values[key]
    if values.get("OPENCODE_SERVER_USERNAME", "opencode") not in {"", "opencode"}:
        raise ValueError("OpenCode 2 requires OPENCODE_SERVER_USERNAME=opencode in Jarvis and the service env")
    if not values.get("OPENCODE_SERVER_PASSWORD"):
        raise ValueError("Set OPENCODE_SERVER_PASSWORD in the selected Jarvis mode env before service setup")
    # V2 prefers the shorter name; do not let an old optional setting override
    # the password used by Jarvis's clients and by this health check.
    values["OPENCODE_PASSWORD"] = values["OPENCODE_SERVER_PASSWORD"]
    values["OPENCODE_SERVER_USERNAME"] = "opencode"
    values.setdefault("JARVIS_VOICE_ROOT", str(ROOT))
    values.setdefault("JARVIS_WORKSPACE_ROOT", str(Path.home() / "jarvis-workspace"))
    for key in ("JARVIS_WORKSPACE_ROOT", "JARVIS_VOICE_ROOT"):
        value = values[key].replace("${HOME}", str(Path.home())).replace("$HOME", str(Path.home()))
        values[key] = str(Path(value).expanduser().resolve())
    if target.exists() and not target.with_suffix(".env.v1-backup").exists():
        atomic_write(target.with_suffix(".env.v1-backup"), target.read_text())
    atomic_write(target, "".join(f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in sorted(values.items())))
    print(f"Prepared {target}; credential values are hidden")
    if removed:
        print("Service unit manages these environment settings: " + ", ".join(removed))


def generated_legacy_profile(config: dict) -> bool:
    """Recognize the exact old Jarvis generator profile, allowing model edits.

    Matching a permission map alone cannot establish its provenance. Require
    the surrounding generator fields, standard provider adapters/credentials,
    filters, and absence of custom policy/agent settings as well.
    """
    allowed = {"$schema", "model", "small_model", "enabled_providers", "provider",
               "disabled_providers", "autoupdate", "permission"}
    # Schema metadata is optional; the provider and policy shape still has to
    # match the old generator. An explicitly different schema is not recognized.
    if (set(config) - allowed
            or ("$schema" in config and config["$schema"] != "https://opencode.ai/config.json")
            or config.get("disabled_providers") != LEGACY_DISABLED_PROVIDERS
            or config.get("permission") not in ({"edit": "ask", "bash": "ask"},
                                                {"edit": "allow", "bash": "allow"})):
        return False
    if "enabled_providers" in config and config["enabled_providers"] != ["ollama", "openai", "anthropic", "xai"]:
        return False
    providers = config.get("provider")
    if not isinstance(providers, dict) or set(providers) != {"ollama", "openai", "anthropic"}:
        return False
    for name, package, label in (("ollama", "@ai-sdk/openai-compatible", "Ollama (local)"),
                                 ("openai", "@ai-sdk/openai", "OpenAI"),
                                 ("anthropic", "@ai-sdk/anthropic", "Anthropic")):
        entry = providers[name]
        if (not isinstance(entry, dict) or set(entry) != {"npm", "name", "options", "models"}
                or entry["npm"] != package or entry["name"] != label
                or not isinstance(entry["models"], dict) or not isinstance(entry["options"], dict)):
            return False
        options = entry["options"]
        if name == "ollama":
            if set(options) != {"baseURL"} or not isinstance(options["baseURL"], str):
                return False
        elif options != {"apiKey": "{env:" + name.upper() + "_API_KEY}"}:
            return False
    return True


def broad_build_blocker(config: dict) -> bool:
    """Detect broad build approval blockers without overriding narrow policies."""
    legacy = config.get("permission", {})
    for action in ("edit", "shell"):
        effect = "allow"
        if isinstance(legacy, str):
            effect = legacy
        elif isinstance(legacy, dict):
            for pattern, value in legacy.items():
                canonical = "shell" if pattern == "bash" else pattern
                if fnmatch.fnmatchcase(action, canonical):
                    if isinstance(value, str):
                        effect = value
                    elif isinstance(value, dict) and "*" in value:
                        effect = value["*"]
        rules = config.get("permissions", [])
        if isinstance(rules, list):
            for rule in rules:
                if (isinstance(rule, dict) and isinstance(rule.get("action"), str)
                        and fnmatch.fnmatchcase(action, rule["action"]) and rule.get("resource") == "*"):
                    effect = rule.get("effect")
        if isinstance(effect, str) and effect in {"ask", "deny"}:
            return True
    policies = config.get("policies", [])
    if isinstance(policies, list):
        for rule in policies:
            if (isinstance(rule, dict) and rule.get("effect") == "deny"
                    and isinstance(rule.get("action"), str)
                    and fnmatch.fnmatchcase("tool.use", rule["action"])
                    and isinstance(rule.get("resource"), str)
                    and rule.get("resource") in {"*", "edit:*", "shell:*", "bash:*"}):
                return True
    return False


def existing_config_plan() -> list[tuple[Path, str, dict, list[str]]]:
    """Validate both global config files before any prepare action mutates files."""
    plans = []
    for name in ("opencode.json", "opencode.jsonc"):
        target = config_dir() / name
        if not target.exists():
            continue
        text = target.read_text()
        try:
            config = json.loads(text)
        except ValueError as exc:
            raise ValueError(
                f"Setup cannot safely migrate {target.name}: this helper requires plain JSON. "
                "OpenCode V2 supports JSONC; review/convert this file while preserving its settings, "
                "then rerun setup. No prepare files have been changed."
            ) from exc
        if not isinstance(config, dict):
            raise ValueError(f"Expected a configuration object in {target.name}")
        changes = []
        known = generated_legacy_profile(config)
        if known:
            config.pop("permission")
            config["permissions"] = [
                {"action": action, "resource": "*", "effect": "allow"}
                for action in ("edit", "shell", "external_directory")
            ]
            changes.append("legacy Jarvis edit/bash permissions -> native unattended build permissions")
        elif broad_build_blocker(config):
            raise ValueError(
                f"Customized edit/shell approval rules in {target.name} need review for unattended Jarvis builds. "
                "Setup preserves custom ask/deny rules; adjust the intended broad build policy explicitly "
                "and rerun. No prepare files have been changed."
            )
        automatic = config.get("update") == "auto" or ("update" not in config and config.get("autoupdate") is True)
        if automatic and not known:
            raise ValueError(
                f"Customized automatic-update policy in {target.name} needs review: the confined service "
                "cannot replace its binary. Set update to notify or disable explicitly and rerun. "
                "No prepare files have been changed."
            )
        if known and "autoupdate" in config:
            previous = config.pop("autoupdate")
            config["update"] = "disable" if previous is False else "notify"
            changes.append("legacy autoupdate -> " + config["update"] + " (host performs upgrades)")
        # Jarvis explicitly selects build even when the terminal's default agent
        # differs. Both can append permissions after the global rules.
        selected = config.get("default_agent", "build")
        if not isinstance(selected, str):
            raise ValueError(f"Invalid selected agent in {target.name}; review its configuration before setup")
        for key in ("agent", "agents", "mode", "modes"):
            agents = config.get(key, {})
            for agent_id in {"build", selected}:
                if isinstance(agents, dict) and isinstance(agents.get(agent_id), dict) and broad_build_blocker(agents[agent_id]):
                    raise ValueError(f"Agent {agent_id} in {target.name} has custom approval blockers; review its policy before setup")
        plans.append((target, text, config, changes))
    return plans


def apply_config_plan(plans: list[tuple[Path, str, dict, list[str]]]) -> None:
    for target, text, config, changes in plans:
        if not changes:
            continue
        backup = backup_config(target, text)
        atomic_write(target, json.dumps(config, indent=2) + "\n")
        print(f"Migrated {target.name}; backup: {backup}")
        for change in changes:
            print("  " + change)


def prepare_config(source: Path) -> None:
    target = config_dir() / "opencode.json"
    plans = existing_config_plan()
    if plans:
        apply_config_plan(plans)
        print("Preserved existing OpenCode provider/model selections and custom rules")
        return
    settings = read_env(source)
    config = json.loads((ROOT / "config" / "opencode.config.json.template").read_text())
    provider = settings.get("OPENCODE_PROVIDER")
    model = settings.get("OPENCODE_MODEL")
    if provider and model:
        config["model"] = f"{provider}/{model}"
    elif source.name == "local.env" or os.environ.get("JARVIS_MODE") == "local":
        config["model"] = f"ollama/{settings.get('OLLAMA_MODEL', 'gemma4')}"
    endpoint = settings.get("OLLAMA_BASE_URL", "http://localhost:11434").split(",")[0].strip().rstrip("/")
    config["providers"]["ollama"]["settings"]["baseURL"] = endpoint if endpoint.endswith("/v1") else f"{endpoint}/v1"
    ollama_model = settings.get("OLLAMA_MODEL", "gemma4")
    config["providers"]["ollama"]["models"] = {ollama_model: {"name": ollama_model}}
    # Fresh cloud installs may not serve the local helper model; the selected
    # coding model is an available title-model default as well.
    config["agents"]["title"]["model"] = config["model"]
    atomic_write(target, json.dumps(config, indent=2) + "\n")
    print(f"Created {target}")


def prepare_plugin() -> None:
    directory = config_dir() / "plugins"
    target = directory / "00-workspace-protection.js"
    legacy = config_dir() / "plugin" / target.name
    # V2 auto-discovers local .js files, but explicitly configured local plugin
    # entries must be directories. Remove only this guard's obsolete file entry.
    aliases = {str(legacy), legacy.as_uri(), f"./plugin/{target.name}",
               str(target), target.as_uri(), f"./plugins/{target.name}"}
    for name in ("opencode.json", "opencode.jsonc"):
        config_path = config_dir() / name
        if not config_path.exists():
            continue
        text = config_path.read_text()
        if not any(json.dumps(alias) in text for alias in aliases):
            continue
        try:
            config = json.loads(text)
        except ValueError as exc:
            raise ValueError("Remove the workspace guard's explicit file entry from JSONC; V2 auto-discovers its installed plugin") from exc

        def keep(entry: object) -> bool:
            value = entry[0] if isinstance(entry, list) and entry else entry
            value = value.get("package") if isinstance(value, dict) else value
            return not isinstance(value, str) or value not in aliases

        for key in ("plugin", "plugins"):
            if isinstance(config.get(key), list):
                config[key] = [entry for entry in config[key] if keep(entry)]
        backup_config(config_path, text)
        atomic_write(config_path, json.dumps(config, indent=2) + "\n")
    if legacy.exists():
        backup = legacy.with_suffix(".js.v1-backup")
        if not backup.exists():
            atomic_write(backup, legacy.read_text())
        legacy.unlink()
    atomic_write(target, (ROOT / "docs" / "opencode" / "plugin" / target.name).read_text(), 0o644)
    print(f"Installed V2 workspace guard: {target}")


def workspace() -> Path:
    values = read_env(config_dir() / "jarvis-env.env", systemd=True)
    return Path(values.get("JARVIS_WORKSPACE_ROOT", str(Path.home() / "jarvis-workspace"))).resolve()


def validate_workspace() -> None:
    target = workspace()
    values = read_env(config_dir() / "jarvis-env.env", systemd=True)
    jarvis = Path(values.get("JARVIS_VOICE_ROOT", str(ROOT))).resolve()
    if target == Path.home() or target in jarvis.parents or jarvis == target or jarvis in target.parents:
        raise ValueError("Workspace must be separate from home and the protected Jarvis checkout")


def prepare_directories() -> None:
    validate_workspace()
    for child in ("projects", "temp", "deployments", ".cache", ".toolchains/cargo", ".toolchains/go"):
        (workspace() / child).mkdir(parents=True, exist_ok=True)
    for child in (".local/share/opencode", ".local/state/opencode", ".cache/opencode"):
        (Path.home() / child).mkdir(parents=True, exist_ok=True)


def prepare_instructions() -> None:
    target = config_dir() / "AGENTS.md"
    if not target.exists():
        atomic_write(target, (ROOT / "config" / "opencode.instructions.md.template").read_text(), 0o644)


def check_binary() -> str:
    executable = Path(os.environ.get("OPENCODE_BINARY", str(Path.home() / ".opencode/bin/opencode")))
    result = subprocess.run([str(executable), "--version"], text=True, capture_output=True, timeout=15, check=True)
    version = re.search(r"(?<![A-Za-z0-9])v?(\d+\.\d+\.\d+)(?:\b|[-+])", result.stdout)
    if not version or not version[1].startswith("2."):
        raise ValueError("OpenCode 2 is required. Install V2 before configuring its Jarvis service.")
    print(f"OpenCode binary version: {version[1]}")
    return version[1]


def render_unit(output: Path) -> None:
    validate_workspace()
    user = os.environ.get("JARVIS_SERVICE_USER", pwd.getpwuid(os.getuid()).pw_name)
    group = os.environ.get("JARVIS_SERVICE_GROUP", grp.getgrgid(os.getgid()).gr_name)
    home = Path(os.environ.get("JARVIS_SERVICE_HOME", str(Path.home()))).resolve()
    values = read_env(config_dir() / "jarvis-env.env", systemd=True)
    replacements = {"__JARVIS_USER__": user, "__JARVIS_GROUP__": group,
                    "__JARVIS_HOME__": str(home), "__JARVIS_WORKSPACE__": str(workspace()),
                    "__JARVIS_ROOT__": values.get("JARVIS_VOICE_ROOT", str(ROOT))}
    content = (ROOT / "systemd" / "opencode-jarvis.service").read_text()
    for token, value in replacements.items():
        if any(char in value for char in ('\n', '\r', '"', '\\')):
            raise ValueError("Service account/workspace paths contain unsupported characters")
        content = content.replace(token, value.replace("%", "%%"))
    atomic_write(output, content, 0o644)
    print(f"Rendered service for {user}; workspace {workspace()}")


def verify_health() -> None:
    expected_version = check_binary()
    values = read_env(config_dir() / "jarvis-env.env", systemd=True)
    base = os.environ.get("OPENCODE_HEALTH_URL", "http://localhost:4096").rstrip("/")
    headers = {}
    password = values.get("OPENCODE_SERVER_PASSWORD")
    if password:
        auth = f"{values.get('OPENCODE_SERVER_USERNAME') or 'opencode'}:{password}"
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()

    def get_json(route: str) -> dict:
        request = urllib.request.Request(base + route, headers=headers)
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response)

    for _ in range(20):
        try:
            info = get_json("/api/info")
            if info.get("version") != expected_version:
                raise ValueError("Running OpenCode version does not match the installed V2 binary")
            plugins = get_json("/api/plugin?" + urllib.parse.urlencode({"location[directory]": str(workspace())}))
            if not any(plugin.get("id") == "jarvis.workspace-protection" and plugin.get("state", {}).get("status") == "active"
                       for plugin in plugins.get("data", [])):
                raise ValueError("V2 workspace guard is not ready")
            print(f"Verified running OpenCode {info['version']} and active workspace guard")
            return
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(1)
    raise ValueError("OpenCode V2 health/plugin verification failed; inspect service logs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("env", "config", "prepare", "version", "render", "health"))
    parser.add_argument("path", nargs="?")
    args = parser.parse_args()
    if args.action == "version":
        check_binary()
    elif args.action == "render":
        if not args.path:
            parser.error("render requires an output path")
        render_unit(Path(args.path))
    elif args.action == "health":
        verify_health()
    else:
        source = selected_env(args.path)
        if args.action == "prepare":
            existing_config_plan()
        if args.action in {"env", "prepare"}:
            prepare_env(source)
        if args.action in {"config", "prepare"}:
            prepare_config(source)
        if args.action == "prepare":
            prepare_plugin()
            prepare_directories()
            prepare_instructions()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"OpenCode setup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
