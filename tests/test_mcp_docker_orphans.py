"""Orphan cleanup must fail closed around live owners and foreign namespaces."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import mcp_docker  # noqa: E402


def labels(pid="123", birth="456", scope="same-host-namespace"):
    return {mcp_docker.OWNER_SCOPE: scope, mcp_docker.OWNER_PID: pid, mcp_docker.OWNER_START: birth}


@pytest.mark.parametrize(("identity", "dead"), [
    (("S", "456"), False),  # Healthy owner.
    (("S", "789"), True),  # PID reused by a different process.
    (("Z", "456"), True),
    (FileNotFoundError(), True),
    (PermissionError(), False),
    (ValueError(), False),
])
def test_owner_death_requires_positive_evidence(monkeypatch, identity, dead):
    def read(_):
        if isinstance(identity, Exception):
            raise identity
        return identity
    monkeypatch.setattr(mcp_docker, "_process_identity", read)
    assert mcp_docker._owner_is_dead(labels(), "same-host-namespace") is dead


@pytest.mark.parametrize("entry", [labels(scope="another-namespace"), labels(pid="0"), labels(birth=""), {}])
def test_unknown_or_foreign_owner_is_never_reaped(monkeypatch, entry):
    monkeypatch.setattr(mcp_docker, "_process_identity", lambda _: pytest.fail("must not inspect a foreign PID"))
    assert not mcp_docker._owner_is_dead(entry, "same-host-namespace")


def test_cleanup_removes_only_dead_owners_using_realistic_docker_ids(monkeypatch):
    entries = [
        {"id": "a" * 64, "labels": labels(pid="123")},
        {"id": "b" * 64, "labels": labels(pid="124")},
        {"id": "c" * 64, "labels": labels(scope="another-namespace")},
        {"id": "d" * 64, "labels": {}},
    ]
    calls = []
    def identity(pid):
        if pid == 123:
            raise FileNotFoundError()
        return "S", "456"
    monkeypatch.setattr(mcp_docker, "_process_identity", identity)
    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["env"] == {"EXPLICIT_SETTING": "only"}
        if args[1] == "ps":
            output = "\n".join(e["id"][:12] for e in entries)
        elif args[1] == "inspect":
            output = "\n".join(json.dumps(e) for e in entries)
        else:
            assert args == ["docker", "rm", "-f", "a" * 64]
            output = ""
        return SimpleNamespace(stdout=output, stderr="", returncode=0)
    monkeypatch.setattr(mcp_docker.subprocess, "run", run)
    assert mcp_docker.reap_orphans(labels(), env={"EXPLICIT_SETTING": "only"}) == 1
    assert len(calls) == 3


def test_no_verified_domain_never_scans_docker(monkeypatch):
    monkeypatch.setattr(mcp_docker.subprocess, "run", lambda *a, **k: pytest.fail("unverified domain"))
    assert mcp_docker.reap_orphans({}, env={}) == 0


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux owner-domain metadata')
def test_owner_scope_separates_users_in_the_same_pid_namespace(monkeypatch):
    original = mcp_docker.owner_labels()
    assert original
    uid = mcp_docker.os.getuid()
    monkeypatch.setattr(mcp_docker.os, 'getuid', lambda: uid + 1)
    other_user = mcp_docker.owner_labels()
    assert original[mcp_docker.OWNER_SCOPE] != other_user[mcp_docker.OWNER_SCOPE]
    assert original[mcp_docker.OWNER_PID] == other_user[mcp_docker.OWNER_PID]
