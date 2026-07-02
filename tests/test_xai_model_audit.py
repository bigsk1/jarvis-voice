"""Regression tests for xAI model catalog drift auditing."""

from lib.xai_model_audit import audit_xai_models, pricing_from_api


def _language(model_id="grok-test-1", **overrides):
    model = {
        "id": model_id,
        "aliases": ["grok-test-latest"],
        "created": 1,
        "version": "1.0",
        "fingerprint": "fp_test",
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "prompt_text_token_price": 12_500,
        "cached_prompt_text_token_price": 2_000,
        "prompt_image_token_price": 12_500,
        "completion_text_token_price": 25_000,
        "search_price": 0,
        "prompt_text_token_price_long_context": 25_000,
        "cached_prompt_text_token_price_long_context": 4_000,
        "completion_text_token_price_long_context": 50_000,
        "long_context_threshold": 200_000,
    }
    model.update(overrides)
    return model


def _basic(model_id="grok-test-1", **overrides):
    model = _language(model_id)
    model.pop("input_modalities")
    model.pop("output_modalities")
    model.pop("version")
    model.pop("fingerprint")
    model["context_length"] = 1_000_000
    model.update(overrides)
    return model


def _catalog(model_id="grok-test-1", **overrides):
    model = {
        "id": model_id,
        "name": "Grok Test",
        "aliases": ["grok-test-latest"],
        "context_tokens": 1_000_000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "pricing": pricing_from_api(_language(model_id)),
    }
    model.update(overrides)
    return model


def test_xai_price_units_and_long_context_are_normalized():
    pricing = pricing_from_api(_language())

    assert pricing == {
        "input": 1.25,
        "output": 2.5,
        "cached": 0.2,
        "image_input": 1.25,
        "search": 0.0,
        "long_context": {
            "threshold": 200_000,
            "input": 2.5,
            "output": 5.0,
            "cached": 0.4,
        },
    }


def test_matching_xai_catalog_is_clean():
    report = audit_xai_models([_basic()], [_language()], [_catalog()])

    assert report["status"] == "ok"
    assert report["drift"] == []
    assert report["warnings"] == []


def test_new_and_ignored_api_models_are_distinguished():
    report = audit_xai_models(
        [_basic(), _basic("grok-new"), _basic("grok-special")],
        [_language(), _language("grok-new"), _language("grok-special")],
        [_catalog()],
        ignored_api_models={"grok-special": "Requires a separate integration."},
    )

    assert report["status"] == "drift"
    assert any(item.get("model_id") == "grok-new" for item in report["drift"])
    assert report["ignored_api_models"] == [
        {"model_id": "grok-special", "reason": "Requires a separate integration."}
    ]


def test_context_modalities_pricing_and_alias_drift_are_reported():
    report = audit_xai_models(
        [_basic(context_length=256_000)],
        [_language(input_modalities=["text"], prompt_text_token_price=10_000)],
        [_catalog(aliases=["retired-alias"])],
    )

    drift_types = [item["type"] for item in report["drift"]]
    assert drift_types.count("model_metadata_mismatch") == 3
    assert "catalog_aliases_not_reported_by_api" in drift_types


def test_catalog_only_model_is_warning_not_drift():
    report = audit_xai_models([], [], [_catalog()])

    assert report["status"] == "ok"
    assert report["warnings"][0]["type"] == "catalog_model_unavailable_to_key"
