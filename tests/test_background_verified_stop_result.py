"""Late supervisor evidence cannot override cancellation or disposition fences."""

from copy import deepcopy

import pytest
from test_background_tasks import ready
from test_background_tasks import store as store

from lib.background_tasks import LostLease, TaskError
from lib.background_tasks.models import MAX_RESULT_BYTES


def expired_local_attempt(store, *, cancelled=False):
    now = [1000.0]
    store.clock = lambda: now[0]
    job = ready(store, adapter="local_skill_v1")
    claim = store.claim("supervisor", {"local_skill_v1"}, lease_seconds=10)
    if cancelled:
        store.request_cancel(job["id"], store.get(job["id"])["revision"],
                             supported_adapters={"local_skill_v1"})
    now[0] += 20
    store.reconcile()
    assert store.get(job["id"])["state"] == "needs_attention"
    return job, claim


@pytest.mark.parametrize("cancelled", [True, False])
def test_verified_stop_retains_result_but_store_owns_final_state_and_cancellation(store, cancelled):
    job, claim = expired_local_attempt(store, cancelled=cancelled)
    result = {
        "ok": True, "cancelled": not cancelled, "completion": "completed",
        "speech": "The operation ended; result presentation is unavailable.",
        "data": {"receipt": "policy-evidence"},
    }
    before = deepcopy(result)
    store.record_local_stop(claim, result=result)
    settled = store.get(job["id"])
    assert settled["state"] == ("cancelled" if cancelled else "failed")
    assert settled["result"] == {**result, "ok": False, "cancelled": cancelled}
    assert settled["delivery_state"] == ("suppressed" if cancelled else "pending")
    assert settled["attention_reason"] is None
    assert result == before
    assert store.claim("another-worker", {"local_skill_v1"}) is None


@pytest.mark.parametrize("superseding_action", ["operator_disposition", "conversation_disposal"])
def test_late_result_cannot_cross_existing_disposition_or_conversation_fences(store, superseding_action):
    job, claim = expired_local_attempt(store)
    if superseding_action == "operator_disposition":
        store.reconcile_job(
            job["id"], store.get(job["id"])["revision"], disposition="failed",
            evidence="Operator independently verified that this task stopped.", stopped=True,
        )
    else:
        store.fence_conversation(job["conversation_id"], job["generation"], "clear", dispose=True)
    before = store.get(job["id"])
    with pytest.raises(LostLease):
        store.record_local_stop(claim, result={"ok": False, "speech": "Late policy receipt."})
    assert store.get(job["id"]) == before


def test_oversized_supervisor_result_rolls_back_without_losing_saved_evidence(store):
    job, claim = expired_local_attempt(store)
    before = store.get(job["id"])
    with pytest.raises(TaskError, match="storage limit"):
        store.record_local_stop(claim, result={"ok": False, "speech": "x" * MAX_RESULT_BYTES})
    assert store.get(job["id"]) == before
