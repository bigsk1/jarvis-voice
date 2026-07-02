"""Regression tests for conservative OpenAI model catalog auditing."""

from lib.openai_model_audit import audit_openai_models


def _api(model_id: str, created: int, owned_by: str = "system"):
    return {"id": model_id, "created": created, "object": "model", "owned_by": owned_by}


def _catalog(model_id: str, aliases=None):
    return {
        "id": model_id,
        "name": model_id,
        "context_tokens": 100_000,
        "pricing": {"input": 1.0, "output": 2.0},
        "aliases": aliases or [],
    }


def test_matching_catalog_ignores_older_and_specialized_models():
    report = audit_openai_models(
        [
            _api("gpt-5.4", 300),
            _api("gpt-image-2", 400),
            _api("gpt-realtime-2", 500),
            _api("text-embedding-3-small", 600),
            _api("gpt-4.1", 100),
        ],
        [_catalog("gpt-5.4")],
    )

    assert report["status"] == "ok"
    assert report["review_candidates"] == []
    assert report["warnings"] == []


def test_new_general_family_is_grouped_for_review():
    report = audit_openai_models(
        [
            _api("gpt-5.4", 300),
            _api("gpt-5.5", 400),
            _api("gpt-5.5-2026-04-23", 401),
            _api("gpt-5.5-pro", 402),
        ],
        [_catalog("gpt-5.4")],
    )

    assert report["status"] == "drift"
    assert len(report["review_candidates"]) == 1
    candidate = report["review_candidates"][0]
    assert candidate["family"] == "gpt-5.5"
    assert [model["id"] for model in candidate["models"]] == [
        "gpt-5.5",
        "gpt-5.5-2026-04-23",
    ]


def test_catalog_alias_can_satisfy_account_availability():
    report = audit_openai_models(
        [_api("gpt-test-latest", 100)],
        [_catalog("gpt-test", aliases=["gpt-test-latest"])],
    )

    assert report["warnings"] == []


def test_missing_curated_model_is_account_specific_warning():
    report = audit_openai_models([], [_catalog("gpt-5.4")])

    assert report["status"] == "ok"
    assert report["warnings"][0]["type"] == "catalog_model_unavailable_to_key"
