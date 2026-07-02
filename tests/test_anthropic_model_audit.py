"""Regression tests for Anthropic model catalog drift auditing."""

from datetime import date

from lib.anthropic_model_audit import audit_anthropic_models


CAPABILITIES = {
    "batch": {"supported": True},
    "image_input": {"supported": True},
}


def _api_model(model_id: str = "claude-test-1", **overrides):
    model = {
        "id": model_id,
        "display_name": "Claude Test 1",
        "created_at": "2026-01-01T00:00:00Z",
        "max_input_tokens": 100_000,
        "max_tokens": 10_000,
        "capabilities": CAPABILITIES,
    }
    model.update(overrides)
    return model


def _catalog_model(model_id: str = "claude-test-1", **overrides):
    model = {
        "id": model_id,
        "name": "Claude Test 1",
        "context_tokens": 100_000,
        "max_output_tokens": 10_000,
        "capabilities": CAPABILITIES,
        "pricing": {"input": 1.0, "output": 2.0, "cached": 0.1},
        "pricing_verified": "2026-06-01",
        "pricing_source": "https://example.test/pricing",
    }
    model.update(overrides)
    return model


def test_matching_model_is_clean():
    report = audit_anthropic_models(
        [_api_model()],
        [_catalog_model()],
        today=date(2026, 7, 1),
    )

    assert report["status"] == "ok"
    assert report["drift"] == []
    assert report["warnings"] == []


def test_new_api_model_is_actionable_drift():
    report = audit_anthropic_models(
        [_api_model(), _api_model("claude-new-2")],
        [_catalog_model()],
        today=date(2026, 7, 1),
    )

    assert report["status"] == "drift"
    assert report["drift"][0]["type"] == "api_model_missing_from_catalog"
    assert report["drift"][0]["model_id"] == "claude-new-2"


def test_intentionally_excluded_api_model_is_not_drift():
    report = audit_anthropic_models(
        [_api_model(), _api_model("claude-retired-1")],
        [_catalog_model()],
        ignored_api_models={"claude-retired-1": "Deprecated upstream."},
        today=date(2026, 7, 1),
    )

    assert report["status"] == "ok"
    assert report["ignored_api_models"] == [
        {"model_id": "claude-retired-1", "reason": "Deprecated upstream."}
    ]


def test_token_and_capability_mismatches_are_reported():
    report = audit_anthropic_models(
        [
            _api_model(
                max_input_tokens=200_000,
                max_tokens=20_000,
                capabilities={"batch": {"supported": False}},
            )
        ],
        [_catalog_model()],
        today=date(2026, 7, 1),
    )

    assert {item["field"] for item in report["drift"]} == {
        "context_tokens",
        "max_output_tokens",
        "capabilities",
    }


def test_catalog_only_model_is_warning_not_drift():
    report = audit_anthropic_models(
        [],
        [_catalog_model()],
        today=date(2026, 7, 1),
    )

    assert report["status"] == "ok"
    assert report["warnings"][0]["type"] == "catalog_model_unavailable_to_key"


def test_stale_and_expired_pricing_are_warnings():
    report = audit_anthropic_models(
        [_api_model()],
        [
            _catalog_model(
                pricing_verified="2026-01-01",
                pricing_valid_until="2026-06-30",
            )
        ],
        today=date(2026, 7, 1),
        pricing_max_age_days=90,
    )

    warning_types = {item["type"] for item in report["warnings"]}
    assert warning_types == {"pricing_verification_stale", "pricing_expired"}
