"""Watch handles and truthful delivery state survive chat persistence."""

import json

from lib.watch_state_context import project_watch_runs


def test_receipts_keep_exact_handles_across_compare_commit_and_ack():
    rows = [
        {"action": "compare", "key": "prices", "run_id": "run_exact", "base_revision": 1,
         "changes": [{"kind": "changed", "record_id": "0007", "fields": {"price": {"old": 10, "new": 0}}}]},
        {"action": "commit", "key": "prices", "run_id": "run_exact", "committed": True,
         "events": [{"event_id": "evt_exact", "record_id": "0007"}]},
        {"action": "ack", "key": "prices", "event_id": "evt_exact", "channel": "email",
         "destination": "fixture@example.test", "success": False, "state": "retry", "attempts": 1},
    ]
    compact = json.loads(json.dumps(project_watch_runs(rows), allow_nan=False))
    assert compact["runs_count"] == 3
    assert compact["results"][0]["changes"][0]["record_id"] == "0007"
    assert compact["results"][0]["changes"][0]["fields"]["price"]["new"] == 0
    assert compact["results"][1]["events"][0]["event_id"] == "evt_exact"
    assert compact["results"][2]["success"] is False
    assert compact["results"][2]["channel"] == "email"


def test_large_records_are_omitted_with_visible_truncation():
    compact = project_watch_runs({"key": "prices", "run_id": "run_exact", "records": [
        {"id": str(i), "body": "untrusted text " * 10000} for i in range(12)
    ]})
    assert compact["run_id"] == "run_exact"
    assert compact["context_truncated"] is True
    assert compact["records_count"] == 12
    assert len(json.dumps(compact)) < 10000


def test_claim_token_survives_and_repeated_runs_share_one_context_budget():
    rows = [{"key": "w" * 450, "run_id": "r" * 450, "claim_token": f"claim_{i}",
             "event_id": "e" * 450, "owner": "o" * 450, "status": "s" * 450,
             "channel": "c" * 450, "destination": "d" * 450,
             "definition": {"description": "untrusted " * 120}}
            for i in range(8)]
    result = project_watch_runs(rows)
    assert len(json.dumps(result, ensure_ascii=False)) <= 10000
    assert result["context_truncated"] is True
    assert result["results"][-1]["claim_token"] == "claim_7"


def test_pending_handles_survive_large_untrusted_record_content():
    result = project_watch_runs({"action": "pending", "key": "prices", "items": [
        {"event_id": "event_exact", "record_id": "0007", "channel": "email",
         "destination": "reader@example.test", "status": "pending",
         "before": {"body": "untrusted " * 10000}, "after": {"price": 0}},
    ]})
    row = result["items"][0]
    assert row["event_id"] == "event_exact"
    assert row["record_id"] == "0007"
    assert row["status"] == "pending" and row["after"]["price"] == 0
    assert row["before_omitted"] is True and row["context_truncated"] is True


def test_successful_health_read_keeps_unhealthy_status_and_claim_rejection():
    health = project_watch_runs({"ok": True, "data": {
        "action": "health", "ok": False, "error_count": 1, "counts_complete": True,
    }})
    assert health["ok"] is True and health["health_ok"] is False
    claim = project_watch_runs({"action": "claim", "claimed": False, "status": "parked"})
    assert claim["claimed"] is False and claim["status"] == "parked"
