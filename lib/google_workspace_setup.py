"""Operator setup for the optional Google service; no Google login automation."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from config_loader import config_scope, get_config_value  # noqa: E402
from mcp_client import MCPRemoteClient  # noqa: E402

SERVICE = ROOT / "google-workspace"
SERVICE_KEYS = (
    "GOOGLE_ACCOUNT", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_WORKSPACE_MCP_TOKEN", "GOOGLE_WORKSPACE_UID", "GOOGLE_WORKSPACE_GID",
)
URL = "http://127.0.0.1:8765/mcp"


class SetupError(ValueError):
    """An operator-facing diagnostic that never contains credentials."""


def offline_consent_url(url: str) -> str:
    """Force a fresh offline grant, including after moving Testing to production."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "accounts.google.com":
        raise SetupError("Unexpected Google authorization URL")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"access_type": "offline", "prompt": "consent select_account"})
    return urlunsplit(parsed._replace(query=urlencode(query)))


def atomic_private_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def service_config() -> dict[str, str]:
    return {key: value for key, value in dotenv_values(SERVICE / ".env", interpolate=False).items()
            if key in SERVICE_KEYS and isinstance(value, str)}


def prepare(mode: str, client_json: Path | None = None):
    previous = service_config()
    with config_scope(mode):
        values = {key: str(get_config_value(key, None) or "")
                  for key in SERVICE_KEYS[:3]}
    if client_json:
        data = json.loads(client_json.read_text())
        client = data.get("web")
        if not isinstance(client, dict):
            raise SetupError("Use a Google OAuth Web application client JSON")
        values.update({"GOOGLE_OAUTH_CLIENT_ID": client["client_id"],
                       "GOOGLE_OAUTH_CLIENT_SECRET": client["client_secret"]})
    missing = [key for key in SERVICE_KEYS[:3] if not values[key].strip()]
    if missing:
        raise SetupError("Missing selected-mode Google configuration: " + ", ".join(missing))
    if not re.fullmatch(r"[a-zA-Z0-9.+_-]+@gmail\.com", values["GOOGLE_ACCOUNT"], re.IGNORECASE):
        raise SetupError("Set GOOGLE_ACCOUNT to the dedicated Gmail account in the selected mode ENV")
    old_account = previous.get("GOOGLE_ACCOUNT", "")
    if old_account and old_account.lower() != values["GOOGLE_ACCOUNT"].lower():
        raise SetupError("This service already belongs to a different account; keep its credentials separate")
    values["GOOGLE_WORKSPACE_MCP_TOKEN"] = previous.get("GOOGLE_WORKSPACE_MCP_TOKEN") or secrets.token_urlsafe(48)
    values["GOOGLE_WORKSPACE_UID"] = str(os.getuid())
    values["GOOGLE_WORKSPACE_GID"] = str(os.getgid())
    for value in values.values():
        if not isinstance(value, str) or any(char in value for char in "\r\n\x00"):
            raise SetupError("Invalid Google service setting")
    for path in (SERVICE / "data", SERVICE / "data" / "credentials"):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    atomic_private_write(SERVICE / ".env", "".join(f"{key}={json.dumps(value)}\n" for key, value in values.items()))
    print("Private service configuration prepared; account passwords were not copied.")
    print("OAuth client configured:", bool(values["GOOGLE_OAUTH_CLIENT_ID"] and values["GOOGLE_OAUTH_CLIENT_SECRET"]))


def compose(*arguments: str):
    if not (SERVICE / ".env").exists():
        raise SetupError("Run bin/jarvis-google prepare first")
    subprocess.run(["docker", "compose", "--env-file", str(SERVICE / ".env"),
                    "-f", str(SERVICE / "compose.yaml"), *arguments], check=True, cwd=SERVICE)


def client() -> MCPRemoteClient:
    token = service_config().get("GOOGLE_WORKSPACE_MCP_TOKEN", "")
    if len(token) < 32:
        raise SetupError("Run bin/jarvis-google prepare first")
    return MCPRemoteClient("google_workspace", URL, "http",
                           {"Authorization": f"Bearer {token}"}, proxy_policy="off")


def stored_grant_status(config: dict[str, str]) -> dict:
    # Inspect only the configured account's grant, never expose its contents.
    account = config.get("GOOGLE_ACCOUNT", "")
    path = SERVICE / "data" / "credentials" / f"{quote(account, safe='@._-')}.json"
    if not account or not path.exists():
        return {"grant_stored": False, "refresh_token_present": False, "client_matches": False}
    data = json.loads(path.read_text())
    return {
        "grant_stored": True,
        "refresh_token_present": bool(data.get("refresh_token")),
        "client_matches": data.get("client_id") == config.get("GOOGLE_OAUTH_CLIENT_ID"),
    }


def check(live: bool = False):
    config = service_config()
    connection = client()
    try:
        from google_workspace import _service_url
        probes = (
            ("GET", _service_url(connection, "/health"), {}, 200),
            ("POST", connection.url, {"headers": {"Accept": "application/json, text/event-stream"},
                "json": {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "jarvis-auth-probe", "version": "1"},
                }}}, 401),
        )
        for method, url, options, expected in probes:
            response = connection._http_request(method, url, timeout=5, allow_redirects=False, **options)
            try:
                if response.status_code != expected:
                    raise SetupError("Google service health/auth boundary check failed")
            finally:
                response.close()
        print("HTTP boundary: public health healthy; unauthenticated MCP rejected")
        connection.start()
        tools = connection.list_tools()
        print("MCP connection: healthy; tools discovered:", len(tools))
        print(json.dumps(stored_grant_status(config)))
        if live:
            failed = []
            for tool_name, arguments in (
                ("list_gmail_labels", {}),
                ("search_drive_files", {"query": "trashed = false", "page_size": 1}),
                ("list_calendars", {"max_results": 1}),
            ):
                result = connection.call_tool(tool_name, {"user_google_email": config["GOOGLE_ACCOUNT"], **arguments})
                print(tool_name, "passed" if result.get("ok") else "failed")
                if not result.get("ok"):
                    # The setup operator can run auth for a fresh URL. Keep mailbox
                    # content and credential-bearing upstream errors out of diagnostics.
                    required = result.get("data", {}).get("configuration_required")
                    if isinstance(required, dict) and required.get("reason") == "api_disabled":
                        print(f"Enable {required['api_id']} in Google Cloud project {required['project_number']}.")
                        print(f"https://console.cloud.google.com/apis/library/{required['api_id']}?project={required['project_number']}")
                    elif result.get("data", {}).get("authentication_required"):
                        print("Google consent required: run bin/jarvis-google auth.")
                    failed.append(tool_name)
            if failed:
                raise SetupError("Google API checks failed; resolve the configuration above before enabling Jarvis")
    finally:
        connection.stop()


def authenticate():
    config = service_config()
    if not config.get("GOOGLE_OAUTH_CLIENT_ID") or not config.get("GOOGLE_OAUTH_CLIENT_SECRET"):
        raise SetupError("Create a Google OAuth Web application client, set its ID/secret in the selected ENV, then run prepare again")
    connection = client()
    try:
        connection.start()
        result = connection.call_tool("start_google_auth", {
            "service_name": "drive", "user_google_email": config["GOOGLE_ACCOUNT"],
        })
        links = result.get("data", {}).get("links", [])
        auth_urls = [row["url"] for row in links if row["url"].startswith("https://accounts.google.com/")]
        if not auth_urls:
            raise SetupError("OAuth link was not returned; confirm client settings and service health")
        print("From your desktop, keep this SSH tunnel open (replace user@server):")
        print("ssh -N -L 8765:127.0.0.1:8765 user@server")
        print("Open this URL in your desktop browser and authorize the dedicated Google account:")
        print(offline_consent_url(auth_urls[0]))
        print("After browser consent: bin/jarvis-google check --live, then bin/jarvis-google enable")
    finally:
        connection.stop()


def update_mode_settings(mode: str, settings: dict[str, str]):
    path = ROOT / "config" / f"{mode}.env"
    if not path.exists():
        raise SetupError(f"Create config/{mode}.env first")
    lines = path.read_text().splitlines()
    pattern = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=")
    lines = [line for line in lines if not ((match := pattern.match(line)) and match[1] in settings)]
    lines.extend(f"{key}={json.dumps(value)}" for key, value in settings.items())
    atomic_private_write(path, "\n".join(lines) + "\n")


def enable(mode: str):
    config = service_config()
    if not all(stored_grant_status(config).values()):
        raise SetupError("Complete Google consent and obtain a matching offline refresh token before enabling Jarvis")
    with config_scope(mode):
        account = get_config_value("GOOGLE_ACCOUNT", "")
    if str(account).lower() != config["GOOGLE_ACCOUNT"].lower():
        raise SetupError("Selected mode's GOOGLE_ACCOUNT must match the service account")
    check(live=True)
    update_mode_settings(mode, {
        "GOOGLE_WORKSPACE_MCP_ENABLED": "true",
        "GOOGLE_WORKSPACE_MCP_URL": URL,
        "GOOGLE_WORKSPACE_MCP_TOKEN": config["GOOGLE_WORKSPACE_MCP_TOKEN"],
    })
    print(f"Enabled in {mode}. Sync Tool RAG for that mode using ~/jarvis-venv, then restart Jarvis.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("cloud", "local"), default="cloud")
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Copy only selected OAuth settings into private service configuration")
    prep.add_argument("--client-json", type=Path)
    commands.add_parser("start", help="Build and start the optional standalone Docker service")
    commands.add_parser("stop", help="Stop the service, retaining stored Google grants")
    commands.add_parser("auth", help="Generate the Google browser consent link")
    probe = commands.add_parser("check", help="Check transport and stored grant without printing private data")
    probe.add_argument("--live", action="store_true", help="Read Gmail labels, one Drive result, and one calendar")
    commands.add_parser("enable", help="Verify live API access and enable MCP in the selected Jarvis mode")
    commands.add_parser("disable", help="Disable MCP in the selected Jarvis mode")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.mode, args.client_json)
        elif args.command == "start":
            compose("up", "-d", "--build")
        elif args.command == "stop":
            compose("down")
        elif args.command == "auth":
            authenticate()
        elif args.command == "check":
            check(args.live)
        elif args.command == "enable":
            enable(args.mode)
        elif args.command == "disable":
            update_mode_settings(args.mode, {"GOOGLE_WORKSPACE_MCP_ENABLED": "false"})
            print("Disabled for selected mode; sync Tool RAG and restart Jarvis.")
    except SetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, KeyError, OSError, json.JSONDecodeError, subprocess.CalledProcessError):
        # Do not echo config values, provider token responses, or Docker env.
        print("Setup step failed. Check the prerequisites and troubleshooting in google-workspace/README.md.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
