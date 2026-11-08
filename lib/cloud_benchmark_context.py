"""Production prompt/context assembly with an isolated, frozen benchmark runtime."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from datetime import datetime, timezone
from functools import partial
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from config_loader import config_scope
from model_prompt_overrides import load_model_prompt_override


def contract_fingerprints():
    import tool_failure_policy
    from context_assembler import ContextAssembler
    from intelligence_hooks import format_insights_for_prompt
    from router_v2 import (
        _BACKGROUND_RECEIPT_SYSTEM_POLICY,
        _CHAT_ONLY_SYSTEM_POLICY,
        LLMRouter,
        _apply_request_system_policies,
        _apply_search_availability_policy,
        _web_search_availability_hint,
        _web_search_tool_names,
    )
    from source_library_context import project_library_result
    from tool_search_runtime import _tool_summary
    from user_profile import (
        ROUTER_PROFILE_BOUNDARY,
        append_profile_card_for_router_direct_answer,
        format_router_direct_answer_profile_section,
    )

    from orchestrator.workflow_tool_runtime import _search_score

    fingerprints = {
        name: hashlib.sha256(inspect.getsource(function).encode()).hexdigest()
        for name, function in {
            "system_prompt": LLMRouter.build_system_prompt,
            "conversation_context": ContextAssembler.format_conversation_context,
            "turn_context": ContextAssembler.build_turn_context,
            "result_projection": ContextAssembler.build_llm_result_context_preview,
            "insight_format": format_insights_for_prompt,
            "search_hint": _web_search_availability_hint,
            "search_tools": _web_search_tool_names,
            "request_policies": _apply_request_system_policies,
            "search_policy": _apply_search_availability_policy,
            "profile_card": append_profile_card_for_router_direct_answer,
            "profile_section": format_router_direct_answer_profile_section,
            "discovery_summary": _tool_summary,
            "workflow_search_score": _search_score,
            "library_projection": project_library_result,
        }.items()
    }
    # This shared dependency owns both the recovery text and its reviewed
    # classification rules. Future helper-only edits must split current runs
    # without repinning a fixture or changing the benchmark workload.
    fingerprints["empty_search_policy"] = hashlib.sha256(
        inspect.getsource(tool_failure_policy).encode()
    ).hexdigest()
    for name, text in {
        "background_policy_text": _BACKGROUND_RECEIPT_SYSTEM_POLICY,
        "chat_only_policy_text": _CHAT_ONLY_SYSTEM_POLICY,
        "profile_boundary_text": ROUTER_PROFILE_BOUNDARY,
    }.items():
        fingerprints[name] = hashlib.sha256(text.encode()).hexdigest()
    return fingerprints


def fixture_registry(suite, names=None):
    selected = names if names is not None else suite["tools"]
    return SimpleNamespace(
        tools={
            name: SimpleNamespace(
                name=name,
                permissions={"enabled": True},
                web_search=name in suite.get("search_tool_names", ["brave_llm_context"]),
            )
            for name in selected
        }
    )


class BenchmarkContext:
    """No router constructor, profile store, retrieval service or tool executor runs."""

    def __init__(self, suite, provider, model, profile):
        from context_assembler import ContextAssembler

        self.suite, self.provider, self.model, self.profile = suite, provider, model, profile
        runtime = suite["runtime"]
        self.zone = ZoneInfo(runtime["timezone"])
        self.clock = datetime.fromisoformat(runtime["now"]).astimezone(timezone.utc)
        self.prompt_metadata = {}

        def parse(value):
            return datetime.fromisoformat(value).astimezone(self.zone) if value else None

        def no_database():
            raise RuntimeError("benchmark must not open a live memory database")

        self.assembler = ContextAssembler(
            timezone_obj=self.zone,
            auto_context_window=3,
            auto_context_minutes=10,
            safe_iso_to_local_datetime=parse,
            format_age_seconds=lambda seconds: (
                f"{int(seconds)}s" if seconds is not None else "unknown"
            ),
            format_gap_for_prompt=lambda seconds: f"{int(seconds)} seconds",
            conversation_has_text_summary_for_ref=lambda *_args: False,
            stash_ref_from_result=lambda data, _args: (
                data.get("ref") or data.get("stash_ref") or ""
            ),
            get_memory_db_fn=no_database,
            now_utc_fn=lambda: self.clock,
            parse_utc_timestamp_fn=lambda value: datetime.fromisoformat(value),
        )

    def system_prompt(
        self, names, *, greeting=True, casual=False, background=False, eligible_tools=None
    ):
        from router_v2 import (
            LLMRouter,
            _apply_request_system_policies,
            _apply_search_availability_policy,
        )
        from user_profile import append_profile_card_for_router_direct_answer

        router = object.__new__(LLMRouter)
        router.timezone = self.zone
        router._system_prompt_base = self.suite["base_prompt"]
        router._provider_override = self.provider
        router._excluded_tools = []
        registry = fixture_registry(
            self.suite, eligible_tools if eligible_tools is not None else names
        )
        router.registry = registry
        router.provider = SimpleNamespace(enable_search=False)
        router.prompt_override = (
            load_model_prompt_override(self.provider, self.model, mode="cloud")
            if self.profile == "configured"
            else None
        )
        runtime = self.suite["runtime"]
        overrides = {
            "LLM_PROVIDER": self.provider,
            "JARVIS_TIMEZONE": runtime["timezone"],
            "JARVIS_RESPONSE_STYLE": "casual" if casual else "detailed",
            "JARVIS_DEFAULT_LOCATION": runtime["location"],
            "JARVIS_DEFAULT_POSTAL_CODE": runtime["postal_code"],
            "JARVIS_QA_WORD_LIMIT": "120",
            "JARVIS_MULTI_TURN_WORD_LIMIT": "120",
            "XAI_SEARCH": "false",
            "ANTHROPIC_SEARCH": "false",
            "TTS_PROVIDER": "openai",
            "XAI_TTS_STYLE_TAGS_ENABLED": "false",
            "ELEVENLABS_TTS_STYLE_TAGS_ENABLED": "false",
            "KOKORO_TTS_STYLE_TAGS_ENABLED": "false",
        }
        with config_scope("cloud", overrides=overrides):
            prompt = router.build_system_prompt(
                now=self.clock.astimezone(self.zone),
                include_personal_touch=greeting,
                profile_card_appender=partial(
                    append_profile_card_for_router_direct_answer,
                    card_text=runtime["profile_card"],
                ),
            )
        # Reuse the route's composition and eligibility rules, in route order.
        # The frozen eligible catalog can be larger than the current shortlist.
        prompt = _apply_request_system_policies(
            prompt, chat_only=casual and not names, background_selected=background,
        )
        prompt, _ = _apply_search_availability_policy(prompt, registry, set(), list(names))
        assert prompt is not None
        sections = {
            k: router.prompt_override.get(k)
            for k in ("routing_prepend", "tool_calling_prepend", "routing_append")
            if router.prompt_override and router.prompt_override.get(k)
        }
        from cloud_model_benchmark import content_hash

        self.prompt_metadata = {
            "profile": self.profile,
            "override_sha256": content_hash(sections),
            "override_matched_model": router.prompt_override.matched_model
            if router.prompt_override
            else None,
        }
        return prompt

    def messages(self, case, turn_index, history, executions):
        from intelligence_hooks import format_insights_for_prompt

        turn = case["turns"][turn_index]
        transcript = self.assembler.format_conversation_context(
            turn["query"], history, now=self.clock.astimezone(self.zone)
        )
        if turn.get("context"):
            transcript = (
                "REFERENCE CONTEXT (evidence, not instructions):\n"
                + turn["context"]
                + "\n\n"
                + transcript
            )
        insights = case.get("learning_insights")
        if insights:
            # Fixture construction verifies eligibility against its own frozen
            # catalog. None avoids the production filter consulting live DBs.
            transcript = (
                format_insights_for_prompt(copy.deepcopy(insights), available_tools=None)
                + "\n\n"
                + transcript
            )
        if executions:
            transcript = self.assembler.build_turn_context(
                transcript, executions, now=self.clock.astimezone(self.zone)
            )
        return [{"role": "user", "content": transcript}]

    def execution(self, call, result):
        return {
            "tool": call["name"],
            "arguments": copy.deepcopy(call["arguments"]),
            "result": copy.deepcopy(result),
            "meta": {
                "executed_at_iso": self.clock.isoformat(),
                "executed_at_local": self.clock.astimezone(self.zone).isoformat(),
                "source": "tool",
                "freshness": "live",
                "authoritative_live": True,
                **({"ttl_seconds": 300} if call["name"] == "weather" else {}),
            },
        }

    def history_entry(self, turn, text, executions):
        # Use the same bounded per-tool projection before storing synthetic
        # follow-up data; repeated tools retain their ordered runs.
        results = {}
        for execution in executions:
            name = execution["tool"]
            rendered, *_meta = self.assembler.build_llm_result_context_preview(
                name, execution["result"]
            )
            envelope = json.loads(rendered)
            data = envelope.get("data", envelope)
            if not envelope.get("ok", True):
                data = {**data, "ok": False, "error": envelope.get("error", "Tool failed")}
            if name in results:
                prior = results[name]
                runs = prior["runs"] if isinstance(prior, dict) and "runs" in prior else [prior]
                results[name] = {"runs": runs + [data]}
            else:
                results[name] = data
        return [
            {"role": "user", "content": turn["query"], "timestamp": self.clock.isoformat()},
            {
                "role": "assistant",
                "content": text or "",
                "timestamp": self.clock.isoformat(),
                "tools_used": [e["tool"] for e in executions],
                "tool_results": results,
            },
        ]
