"""Trusted Apify binding: one paid start, resumable native-run observation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib.apify import TERMINAL, ApifyClient, ApifyError, ApifySettings

from .local_skill import argument_validators
from .models import AdmissionDenied
from .worker import (
    CancellationRequested,
    KnownFailure,
    KnownRemoteCancelled,
    ResumableRemoteAdapter,
    UncertainOutcome,
)

ADAPTER = "apify_actor_v1"
TOOL = "apify_run_actor"
ROOT = Path(__file__).resolve().parents[2]


def policy(root: Path = ROOT):
    """Explicitly reviewed remote effects, not the local read-only skill policy."""
    from tool_availability import check_tool_availability
    from tool_profiles import effective_enabled, load_active_profile_overrides
    from tool_schema import ToolSchema

    try:
        path = root / "skills" / f"{TOOL}.tool.json"
        raw = path.read_bytes()
        manifest = json.loads(raw)
        script = root / "skills" / f"{TOOL}.py"
        settings = manifest["execution"]["background"]
        permissions = manifest["permissions"]
        if (manifest["name"] != TOOL or manifest["script"] != script.name
                or not effective_enabled(TOOL, manifest.get("enabled", True), load_active_profile_overrides())
                or not check_tool_availability(manifest).available
                or permissions.get("dangerous") is not True
                or permissions.get("auto_approve") is not True
                or permissions.get("network") is not True
                or settings.get("adapter") != ADAPTER
                or settings.get("supported") is not True
                or settings.get("completion_scope") != "remote_work"
                or type(settings.get("timeout_seconds")) is not int
                or not 1 <= settings["timeout_seconds"] <= 86400):
            raise AdmissionDenied("Apify execution is disabled or its reviewed policy changed")
        argument_validators(manifest["parameters"], None)
        schema = ToolSchema(TOOL, manifest["description"], manifest["parameters"], str(script),
                            permissions=permissions, execution=manifest["execution"], proxy_policy="off")
        # Bind the trusted provider code too: a script hash alone would miss edits
        # to the shared in-process execution boundary.
        evidence = {"adapter": ADAPTER, "timeout_seconds": settings["timeout_seconds"],
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "provider_sha256": hashlib.sha256((root / "lib" / "apify.py").read_bytes()).hexdigest(),
            "binding_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        return schema, evidence
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, AdmissionDenied):
            raise
        raise AdmissionDenied("Apify policy is unavailable or invalid") from None


def _authorize_start(context):
    schema, evidence = policy()
    job = context.claim.job
    authorization = context.store.authorization(job["admission"]["authorization_id"])
    if (not authorization or authorization.get("operator") != "installation"
            or authorization.get("source") != "web"
            or TOOL not in authorization.get("selected", [])
            or authorization.get("tool_policy") == "none"
            or authorization.get("tool_policies", {}).get(TOOL) != evidence
            or job["admission"]["timeout_seconds"] != evidence["timeout_seconds"]
            or any(authorization.get(key) != job["admission"][key]
                   for key in ("conversation_id", "generation", "request_id", "mode"))):
        raise AdmissionDenied("Saved Apify submission authorization no longer matches its policy")
    config_path = ROOT / "jarvis-web" / "config" / "web_config.json"
    web_config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if TOOL in web_config.get("tools", {}).get("blocked", []):
        raise AdmissionDenied("Apify was blocked after admission")
    for validator in argument_validators(schema.parameters, None):
        validator.validate(job["admission"]["arguments"])


def start(context):
    # The normal registry/config helpers use their established top-level import.
    # Worker config_scope already owns the package import; scope both to this
    # saved mode without hydrating process environment or another mode's token.
    from config_loader import config_scope

    context.remote_submission_started = False
    try:
        with config_scope(context.claim.job["mode"], overrides=context.config_values):
            _authorize_start(context)
        client = ApifyClient()
        arguments = context.claim.job["admission"]["arguments"]
        prepared = client.prepare(arguments["actor"], arguments["input"])
        context.checkpoint()
        # Once this starts, cancellation/shutdown without a native checkpoint is
        # uncertain, even if the POST eventually returns after lease loss.
        context.remote_submission_started = True
        handle = client.start(prepared)
        context.persist_remote_checkpoint(handle)
        return handle
    except (ApifyError, AdmissionDenied) as exc:
        if isinstance(exc, ApifyError) and exc.uncertain:
            raise UncertainOutcome("Apify submission may have started; no native run was saved. "
                                   "Inspect Apify Console before retrying.") from None
        raise KnownFailure({"ok": False, "completion": "rejected", "speech": str(exc),
                            "error": str(exc)}) from None


def observe(context, checkpoint):
    """Read-only restart path except for an explicitly requested native abort."""
    from config_loader import config_scope

    with config_scope(context.claim.job["mode"], overrides=context.config_values):
        return _observe(context, checkpoint)


def _observe(context, checkpoint):
    # Revoking submission opt-in does not abandon an already-owned provider run.
    # The saved job mode still controls the credential; no fallback mode lookup.
    client = ApifyClient(ApifySettings.load(require_enabled=False))
    run_id = checkpoint["run_id"]
    abort_sent = False
    failures = 0
    while True:
        context.checkpoint(allow_cancel=True)
        cancellation = False
        try:
            context.checkpoint()
        except CancellationRequested:
            cancellation = True
        try:
            run = client.get_run(run_id, expected_actor=checkpoint.get("actor_id"))
            failures = 0
            if checkpoint.get("build_id") and run.get("buildId") != checkpoint["build_id"]:
                raise UncertainOutcome("The saved Apify run changed builds; inspect the existing run.",
                                       result={"data": {"run_id": run_id}})
            if run["status"] in TERMINAL:
                if cancellation and run["status"] == "ABORTED":
                    raise KnownRemoteCancelled(run_id)
                result = client.result(run)
                if run["status"] == "SUCCEEDED":
                    try:
                        if client.storages(run, "datasets"):
                            result = client.result(run, action="dataset", limit=client.settings.page_size)
                    except ApifyError:
                        # The run completed; output collection can be retried by
                        # native ID without falsely asking to submit another run.
                        result["data"]["limits"]["collection_incomplete"] = True
                        result["speech"] += " Output retrieval needs another read of this run."
                    return result
                raise KnownFailure({**result, "completion": "completed"})
            if cancellation and not abort_sent:
                # Even if the abort receipt is lost, poll rather than repeat it.
                abort_sent = True
                client.abort(run_id)
            context.progress({"phase": "cancelling" if cancellation else "observing",
                              "status": run["status"], "recovery": {"run_id": run_id}},
                             allow_cancel=True)
        except ApifyError:
            # GET/status failure is not a terminal Actor failure. The same handle
            # remains valid until the independent observation deadline.
            failures = min(failures + 1, 5)
            context.progress({"phase": "status temporarily unavailable",
                              "recovery": {"run_id": run_id}}, allow_cancel=True)
        delay = min(300, client.settings.poll_seconds * (2 ** failures))
        # Short first checks keep quick Actors responsive; sustained observation
        # can use an operator-configured five-minute poll interval.
        try:
            context.wait(delay, allow_cancel=cancellation)
        except CancellationRequested:
            continue  # Reach native abort promptly, even with a five-minute poll.


def worker_adapter():
    return ResumableRemoteAdapter(start, observe)
