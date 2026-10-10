#!/usr/bin/env python3
"""Install official Craft releases under a user's apps directory; no sudo."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zlib
from pathlib import Path, PurePosixPath

APPS = ("filmcraft", "photocraft", "pdfcraft", "effectcraft", "lightcraft")
VERSION = re.compile(r"v?\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.-]+)?\Z")


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Craft-Remote-Setup", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def release(app, version="latest"):
    if version != "latest" and not VERSION.fullmatch(version):
        raise ValueError("Invalid release version")
    endpoint = "latest" if version == "latest" else f"tags/{version}"
    data = get_json(f"https://api.github.com/repos/storytold/{app}/releases/{endpoint}")
    tag = data["tag_name"]
    if not VERSION.fullmatch(tag):
        raise ValueError(f"Unexpected release tag: {tag}")
    arch = {"x86_64": "x86_64", "aarch64": "aarch64"}.get(platform.machine())
    if platform.system() != "Linux" or arch is None:
        raise RuntimeError("Deployment supports Linux x86_64/aarch64; clients can use Windows/macOS")
    name = f"{app}-{tag.removeprefix('v')}-linux-{arch}.tar.gz"
    asset = next((item for item in data["assets"] if item["name"] == name), None)
    if asset is None:
        raise RuntimeError(f"Release {tag} has no {name}")
    digest = asset.get("digest") or ""
    if not digest.startswith("sha256:"):
        sums = next(item for item in data["assets"] if item["name"] == "SHA256SUMS.txt")
        request = urllib.request.Request(sums["browser_download_url"], headers={"User-Agent": "Craft-Remote-Setup"})
        with urllib.request.urlopen(request, timeout=60) as response:
            lines = response.read(1024 * 1024).decode().splitlines()
        digest = "sha256:" + next(line.split()[0] for line in lines if line.split()[-1].lstrip("*") == name)
    sha = digest.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("Release has no valid SHA256 checksum")
    return {"version": tag, "asset": name, "url": asset["browser_download_url"], "sha256": sha, "release_url": data["html_url"]}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_path(record, cache):
    name = record["asset"]
    if Path(name).name != name or not name.endswith(".tar.gz"):
        raise ValueError("Invalid asset name")
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if target.exists():
        if sha256(target) != record["sha256"]:
            raise RuntimeError(f"Cached package checksum failed: {target}; leave it for inspection")
        return target
    url = record["url"]
    if not url.startswith("https://github.com/storytold/"):
        raise ValueError("Expected an official storytold GitHub download URL")
    temporary = cache / (name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Craft-Remote-Setup"})
    try:
        with urllib.request.urlopen(request, timeout=60) as source, temporary.open("wb") as dest:
            count = 0
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > 300 * 1024 * 1024:
                    raise RuntimeError("Release package exceeds 300 MiB")
                dest.write(chunk)
        if sha256(temporary) != record["sha256"]:
            raise RuntimeError("Downloaded release checksum failed")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def extract_package(archive, destination):
    """Flatten the one package root; disallow links, traversal and special files."""
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 2 * 1024**3:
            raise RuntimeError("Release archive exceeds extraction limits")
        roots = set()
        checked = []
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"Unsafe archive path: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsupported archive entry: {member.name}")
            roots.add(path.parts[0])
            checked.append((member, path.parts[1:]))
        if len(roots) != 1:
            raise ValueError("Expected one top-level package directory")
        for member, parts in checked:
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as stream, target.open("wb") as output:
                    shutil.copyfileobj(stream, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def mcp_args(app, workspace):
    if app == "photocraft":
        return ["mcp", "--automation-read-root", str(workspace), "--automation-write-root", str(workspace)]
    if app == "pdfcraft":
        return ["mcp", "--root", str(workspace), "--compact"]
    if app == "lightcraft":
        return ["mcp", "--compact"]
    return ["mcp"]


def write_fixtures(work):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    pixels = b"".join(b"\0" + bytes((80, 60, 40)) * 64 for _ in range(36))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 36, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    (work / "source.png").write_bytes(png)
    text = b"BT /F1 12 Tf 20 50 Td (Craft workflow check) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 128 72] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>", b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    pdf += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    (work / "source.pdf").write_bytes(pdf)


def workflow_smoke(app, binary, work, env):
    """Small real edits/save/reopen/render using only installed binaries."""
    write_fixtures(work)
    def call(*arguments):
        result = subprocess.run([str(binary), *arguments], cwd=work, env=env, capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(f"Workflow failed ({arguments[0]}): {(result.stderr + result.stdout)[-2000:]}")
        return result.stdout
    if app == "photocraft":
        call("run", "--new", json.dumps({"width": 64, "height": 36}), "--cmd", "layer.newFillLayer.solidColor", "--params", json.dumps({"color": "#3366aa"}), "--out", "smoke.pcraft")
        call("convert", "smoke.pcraft", "smoke.png")
    elif app == "pdfcraft":
        call("edit", "source.pdf", "--rotate", "1:90", "--out", "smoke.pdf")
        call("render", "smoke.pdf", "--page", "1", "--out", "smoke.png")
    elif app == "lightcraft":
        call("render", "source.png", "-o", "smoke.png", "--set", "light.exposure=0.5")
    elif app == "effectcraft":
        call("run", "comp.new", json.dumps({"name": "Smoke", "width": 64, "height": 36, "frameRate": 12, "duration": 1}), "layer.newText", json.dumps({"text": "Craft", "size": 12, "position": [4, 20]}), "--save-as", "smoke.ecproj")
        call("--project", "smoke.ecproj", "render-frame", "--time", "0", "--out", "smoke.png")
    else:
        commands = [
            {"id": "file.import", "params": {"paths": [str(work / "source.png")]}},
            {"id": "file.newSequence", "params": {"name": "Smoke", "width": 64, "height": 36, "fps": 12, "video": 1, "audio": 1}},
            {"id": "timeline.place", "params": {"item": 1, "track": "V1", "seconds": 0, "insert": False, "duration": 254016000000}},
        ]
        (work / "steps.jsonl").write_text("".join(json.dumps(item) + "\n" for item in commands))
        call("--save-as", "smoke.fcproj", "run", "steps.jsonl")
        call("--project", "smoke.fcproj", "render", "--seconds", "0", "--out", "smoke.png")
    output = work / "smoke.png"
    with output.open("rb") as stream:
        header = stream.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or len(header) != 24 or min(struct.unpack(">II", header[16:24])) < 1:
        raise RuntimeError("Workflow did not produce a valid PNG header")
    return "passed"


def smoke(app, folder):
    binary = folder / "bin" / f"{app}-cli"
    desktop = folder / "bin" / app
    if not binary.is_file() or not desktop.is_file():
        raise RuntimeError(f"Package is missing desktop or CLI executable: {app}")
    with tempfile.TemporaryDirectory(prefix="craft-smoke-") as temporary:
        work = Path(temporary)
        env = {key: value for key, value in os.environ.items() if key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH")}
        env.update(HOME=temporary, XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"), XDG_DATA_HOME=str(work / "data"), TMPDIR=temporary)
        help_arg = "help" if app == "filmcraft" else "--help"
        result = subprocess.run([str(binary), help_arg], cwd=work, env=env, capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError(f"CLI failed: {(result.stderr or result.stdout)[-2000:]}")
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "craft-setup", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        result = subprocess.run([str(binary), *mcp_args(app, work)], input="".join(json.dumps(item) + "\n" for item in messages), cwd=work, env=env, capture_output=True, text=True, timeout=45)
        replies = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        by_id = {item.get("id"): item for item in replies}
        if result.returncode or "result" not in by_id.get(1, {}) or "result" not in by_id.get(2, {}):
            raise RuntimeError(f"MCP initialization/discovery failed: {result.stderr[-2000:]} {replies}")
        tools = by_id[2]["result"].get("tools", [])
        if not tools:
            raise RuntimeError("MCP advertised no tools")
        workflow = workflow_smoke(app, binary, work, env)
        return {"cli": "passed", "mcp": "passed", "edit_save_render": workflow, "tool_count": len(tools), "tool_names": [tool["name"] for tool in tools]}


def activate(app_dir, target):
    current = app_dir / "current"
    if current.exists() and not current.is_symlink():
        raise RuntimeError(f"Refusing to replace a non-symlink: {current}")
    temporary = app_dir / ".current-new"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(os.path.relpath(target, app_dir))
    temporary.replace(current)


def install(app, root, record, cache):
    if not VERSION.fullmatch(record["version"]):
        raise ValueError("Invalid locked version")
    app_dir = root / app
    app_dir.mkdir(parents=True, exist_ok=True)
    target = app_dir / "releases" / record["version"]
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = target / "craft-install.json"
    if target.exists():
        if not manifest.is_file() or json.loads(manifest.read_text())["release"] != record:
            raise RuntimeError(f"Existing release is unmanaged or differs: {target}")
        checks = smoke(app, target)
    else:
        archive = package_path(record, cache)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=target.parent))
        try:
            extract_package(archive, staging)
            checks = smoke(app, staging)
            (staging / "craft-install.json").write_text(json.dumps({"app": app, "release": record, "checks": checks}, indent=2) + "\n")
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    previous = (app_dir / "current").resolve() if (app_dir / "current").is_symlink() else None
    activate(app_dir, target)
    return {"app": app, "version": record["version"], "current": str(target), "previous": str(previous) if previous else None, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "update", "status", "check", "rollback"))
    parser.add_argument("apps", nargs="*", choices=APPS)
    parser.add_argument("--root", type=Path, default=Path.home() / "apps")
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("releases.lock.json"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--version", help="Explicit release tag for update or rollback")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    apps = args.apps or list(APPS)
    if args.action == "rollback" and (len(apps) != 1 or not args.version):
        parser.error("rollback requires one app and --version")
    if args.version and not VERSION.fullmatch(args.version):
        parser.error("Invalid version")
    if args.action in ("install", "update", "rollback"):
        root.mkdir(parents=True, exist_ok=True)
    lock = json.loads(args.lock.read_text()) if args.action == "install" else {}
    cache = (args.cache or root / "craft-admin" / "downloads").expanduser().resolve()
    failures = []
    results = []
    with contextlib.ExitStack() as stack:
        if args.action in ("install", "update", "rollback"):
            import fcntl
            lock_dir = root / "craft-admin"
            lock_dir.mkdir(exist_ok=True)
            stream = stack.enter_context((lock_dir / "deployment.lock").open("a"))
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            (root / "craft-workspace" / "projects").mkdir(parents=True, exist_ok=True)
        for app in apps:
            try:
                current = root / app / "current"
                if args.action in ("install", "update"):
                    record = lock[app] if args.action == "install" else release(app, args.version or "latest")
                    result = install(app, root, record, cache)
                    web_manager = root / "craft-admin" / "web_manage.py"
                    if web_manager.is_file() and (root / "craft-web" / "compose.yaml").is_file():
                        web = subprocess.run([sys.executable, str(web_manager), "sync", app, "--root", str(root)], capture_output=True, text=True, timeout=300)
                        if web.returncode:
                            raise RuntimeError(f"Native {app} {record['version']} selected, but browser update failed; previous browser release remains. {web.stderr[-2000:]}")
                        result["browser_update"] = "passed"
                elif args.action == "rollback":
                    target = root / app / "releases" / args.version
                    if not (target / "craft-install.json").is_file():
                        raise RuntimeError("Rollback target is not a managed installed release")
                    checks = smoke(app, target)
                    activate(root / app, target)
                    result = {"app": app, "current": str(target), "checks": checks}
                elif args.action == "check":
                    result = {"app": app, "checks": smoke(app, current.resolve())}
                else:
                    result = {"app": app, "installed": current.is_symlink(), "current": str(current.resolve()) if current.is_symlink() else None}
                    if (current / "craft-install.json").is_file():
                        result["release"] = json.loads((current / "craft-install.json").read_text())["release"]
                results.append(result)
                print(json.dumps(result), flush=True)
            except Exception as exc:
                failures.append(app)
                print(json.dumps({"app": app, "error": str(exc)}), file=sys.stderr, flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
