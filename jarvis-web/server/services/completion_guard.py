"""
Completion Guard policy and analysis helpers.

This module owns the decisioning layer for Completion Guard:
- effective config assembly
- applicability checks
- auto-eval parsing/scoring
- repair delta analysis
- repair strategy classification

Socket events, conversation-store writes, and background-task coordination stay
in ChatHandler so the live websocket flow remains easy to follow.
"""

import ast
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / "lib"))

from config_loader import get_config_value, load_config

from ..config import load_jarvis_config, load_web_config

_CG_TIGHTEN_ONLY_ANSWER_SIMILARITY_THRESHOLD = 0.88
_CG_MANUAL_PROMPT_TTL_SECONDS_DEFAULT = 10 * 60


@dataclass
class CompletionGuardPolicy:
    """Decisioning helpers for Completion Guard."""

    parse_bool_fn: Callable[[object, bool], bool]
    normalize_server_side_tool_names_fn: Callable[[dict | None], list[str]]
    combine_feedback_tools_fn: Callable[[list[str] | None, list[str] | None], list[str]]
    default_excluded_tools: set[str]

    def get_config(self, mode: str) -> dict:
        """Get effective Completion Guard settings for the current mode."""
        load_jarvis_config(mode)
        web_config = load_web_config()
        mode_overrides = web_config.get(mode, {})

        enabled = mode_overrides.get("completion_guard_enabled")
        mode_setting = mode_overrides.get("completion_guard_mode")
        ticket_on_fail = mode_overrides.get("completion_guard_ticket_on_fail")
        show_ui_prompt = mode_overrides.get("completion_guard_show_ui_prompt")
        include_qa = mode_overrides.get("completion_guard_include_qa")
        include_tool_tasks = mode_overrides.get("completion_guard_include_tool_tasks")
        auto_threshold = mode_overrides.get("completion_guard_auto_threshold")
        eval_provider = mode_overrides.get("completion_guard_eval_provider")
        eval_model = mode_overrides.get("completion_guard_eval_model")
        excluded_tools_raw = (
            get_config_value("COMPLETION_GUARD_EXCLUDED_TOOLS")
            or get_config_value("JARVIS_COMPLETION_GUARD_EXCLUDED_TOOLS")
            or ""
        )
        excluded_tools = set(self.default_excluded_tools)
        if excluded_tools_raw:
            excluded_tools.update(
                item.strip() for item in str(excluded_tools_raw).split(",") if item and item.strip()
            )
        try:
            manual_prompt_ttl_seconds = int(
                get_config_value(
                    "JARVIS_COMPLETION_GUARD_MANUAL_TTL_SECONDS",
                    str(_CG_MANUAL_PROMPT_TTL_SECONDS_DEFAULT),
                )
                or _CG_MANUAL_PROMPT_TTL_SECONDS_DEFAULT
            )
        except (TypeError, ValueError):
            manual_prompt_ttl_seconds = _CG_MANUAL_PROMPT_TTL_SECONDS_DEFAULT

        return {
            "enabled": enabled
            if enabled is not None
            else self.parse_bool_fn(get_config_value("JARVIS_COMPLETION_GUARD_ENABLED", "false")),
            "mode": mode_setting or get_config_value("JARVIS_COMPLETION_GUARD_MODE", "manual"),
            "ticket_on_fail": ticket_on_fail
            if ticket_on_fail is not None
            else self.parse_bool_fn(get_config_value("JARVIS_COMPLETION_GUARD_TICKET_ON_FAIL", "true"), True),
            "show_ui_prompt": show_ui_prompt
            if show_ui_prompt is not None
            else self.parse_bool_fn(get_config_value("JARVIS_COMPLETION_GUARD_SHOW_UI_PROMPT", "true"), True),
            "include_qa": include_qa
            if include_qa is not None
            else self.parse_bool_fn(get_config_value("JARVIS_COMPLETION_GUARD_INCLUDE_QA", "true"), True),
            "include_tool_tasks": include_tool_tasks
            if include_tool_tasks is not None
            else self.parse_bool_fn(get_config_value("JARVIS_COMPLETION_GUARD_INCLUDE_TOOL_TASKS", "true"), True),
            "auto_threshold": float(
                auto_threshold
                if auto_threshold is not None
                else get_config_value("JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD", "0.70")
            ),
            "eval_provider": eval_provider
            or get_config_value("JARVIS_COMPLETION_GUARD_EVAL_PROVIDER", "ollama" if mode == "local" else "openai"),
            "eval_model": eval_model or get_config_value("JARVIS_COMPLETION_GUARD_EVAL_MODEL", ""),
            "manual_prompt_ttl_seconds": max(0, manual_prompt_ttl_seconds),
            "excluded_tools": sorted(excluded_tools),
        }

    def applies(self, config: dict, tools_used: list[str]) -> bool:
        """Check whether Completion Guard applies to this response at all."""
        if not config.get("enabled"):
            return False
        excluded = set(config.get("excluded_tools", self.default_excluded_tools))
        if any(tool in excluded for tool in (tools_used or [])):
            return False

        has_tools = bool(tools_used)
        if has_tools:
            return config.get("include_tool_tasks", True)
        return config.get("include_qa", True)

    def should_prompt(self, config: dict, tools_used: list[str]) -> bool:
        """Decide whether to show the completion prompt for this response."""
        if config.get("mode") != "manual":
            return False
        if not config.get("show_ui_prompt"):
            return False
        return self.applies(config, tools_used)

    def should_auto_evaluate(self, config: dict, tools_used: list[str]) -> bool:
        """Decide whether auto mode should evaluate a response in the background."""
        if config.get("mode") != "auto":
            return False
        return self.applies(config, tools_used)

    @staticmethod
    def record_expired(record: dict) -> bool:
        expires_at = record.get("expires_at")
        try:
            import time

            return bool(expires_at and time.time() >= float(expires_at))
        except (TypeError, ValueError):
            return False

    def build_feedback_context(self, record: dict, status: str) -> dict:
        """Summarize Completion Guard state so feedback can grade the settled outcome."""
        original_tools = list(record.get("tools_used", []) or [])
        repair_tools = list((record.get("repair_result") or {}).get("tools_used", []) or [])
        original_native_tools = self.normalize_server_side_tool_names_fn(record.get("server_side_tools"))
        repair_native_tools = self.normalize_server_side_tool_names_fn(
            (record.get("repair_result") or {}).get("server_side_tools")
        )
        return {
            "status": status,
            "note": record.get("user_note", ""),
            "auto_triggered": bool(record.get("auto_evaluation")),
            "auto_evaluation": record.get("auto_evaluation"),
            "repair_strategy": record.get("repair_strategy"),
            "repair_result": record.get("repair_result"),
            "ticket_path": record.get("ticket_path", ""),
            "combined_tools_used": self.combine_feedback_tools_fn(
                original_tools + original_native_tools,
                repair_tools + repair_native_tools,
            ),
            "original_response": {
                "speech": record.get("speech", ""),
                "raw_llm_response": record.get("raw_llm_response", ""),
                "tools_used": original_tools + original_native_tools,
            },
            "repair_tools_used": repair_tools + repair_native_tools,
        }

    @staticmethod
    def normalize_comparison_text(text: str) -> str:
        """Normalize text before comparing answer similarity."""
        if not text:
            return ""
        text = str(text)
        text = re.sub(r"[*_`#>]+", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip().lower()

    @classmethod
    def text_similarity(cls, left: str, right: str) -> float:
        """Return a coarse similarity score between two strings."""
        a = cls.normalize_comparison_text(left)
        b = cls.normalize_comparison_text(right)
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    @staticmethod
    def prepare_repair_data_for_delta(data) -> str:
        """Normalize result payloads before comparing evidence changes."""
        if data is None:
            return ""
        try:
            if isinstance(data, dict):
                cleaned = {
                    key: value
                    for key, value in data.items()
                    if key not in {"speech", "raw_llm_response", "usage", "_web_message_id", "_completion_guard"}
                }
            else:
                cleaned = data
            text = json.dumps(cleaned, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            text = str(data)
        return re.sub(r"\s+", " ", text).strip()

    def analyze_delta(self, record: dict, result: dict) -> dict:
        """
        Determine whether a repair materially improved the task with new evidence
        or a different tool path, rather than only rewording the answer.
        """
        original_tools = [str(item).strip() for item in (record.get("tools_used") or []) if str(item).strip()]
        repair_tools = [str(item).strip() for item in (result.get("tools_used") or []) if str(item).strip()]
        original_tools.extend(self.normalize_server_side_tool_names_fn(record.get("server_side_tools")))
        repair_tools.extend(self.normalize_server_side_tool_names_fn(result.get("server_side_tools")))

        original_tool_set = set(original_tools)
        repair_tool_set = set(repair_tools)
        tool_path_delta = original_tools != repair_tools and (
            bool(repair_tool_set - original_tool_set) or len(repair_tools) != len(original_tools) or not original_tools
        )

        original_data = self.prepare_repair_data_for_delta(record.get("data"))
        repair_data = self.prepare_repair_data_for_delta(result.get("data"))
        data_similarity = self.text_similarity(original_data, repair_data) if original_data and repair_data else 0.0
        evidence_delta = bool(repair_data) and (
            not original_data or data_similarity < 0.94 or len(repair_data) > len(original_data) + 120
        )

        original_answer = record.get("raw_llm_response") or record.get("speech") or ""
        repaired_answer = result.get("raw_llm_response") or result.get("speech") or ""
        answer_similarity = self.text_similarity(original_answer, repaired_answer)

        return {
            "operational_correction": bool(tool_path_delta or evidence_delta),
            "tool_path_delta": bool(tool_path_delta),
            "evidence_delta": bool(evidence_delta),
            "answer_similarity": round(answer_similarity, 4),
            "data_similarity": round(data_similarity, 4) if original_data and repair_data else None,
            "original_tools": original_tools,
            "repair_tools": repair_tools,
        }

    @staticmethod
    def tighten_instead_of_substantive_repair(delta: dict) -> bool:
        """
        True when a 'repair' run did not change the tool path and the answer text is
        nearly the same—treat as tighten_only (wording/hedging), not a better answer.
        """
        if not delta.get("operational_correction"):
            return False
        if delta.get("tool_path_delta"):
            return False
        try:
            asim = float(delta.get("answer_similarity") or 0)
        except (TypeError, ValueError):
            asim = 0.0
        return asim >= _CG_TIGHTEN_ONLY_ANSWER_SIMILARITY_THRESHOLD

    @staticmethod
    def get_location_context(mode: str) -> str:
        """Provide location fallback context so Completion Guard audits local queries fairly."""
        try:
            load_config(mode)
        except Exception:
            pass

        default_location = str(get_config_value("JARVIS_DEFAULT_LOCATION", "") or "").strip()
        if not default_location:
            return """Configured default location:
(not set)

Location handling:
- Jarvis may answer location-relative questions only when it has explicit location context
- If no configured default location is set, do not treat an unstated fallback location as supported
- Flag location issues when the answer invents a location or implies live/current geolocation without support"""

        return f"""Configured default location:
{default_location}

Location handling:
- The configured default location above is valid runtime context for Jarvis, even when no location tool was used
- If the user asked a location-relative question like "near me" and the answer uses the configured default location above, that is an allowed fallback
- Do not treat use of the configured default location above as a hallucinated location claim when the answer is clearly using that default
- Flag location issues only when the answer claims live/current geolocation, or switches to a different unsupported location"""

    @staticmethod
    def parse_auto_eval(raw_text: str) -> dict:
        """Parse the auto-evaluator JSON response."""
        if not raw_text:
            return {}

        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<reasoning>.*?</reasoning>\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<think>[^{]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<reasoning>[^{]*", "", text, flags=re.IGNORECASE)
        text = text.strip()

        try:
            data = json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                text_lower = text.lower()
                recommended_action = ""
                if "tighten_only" in text_lower or "tighten only" in text_lower:
                    recommended_action = "tighten_only"
                elif "repair_required" in text_lower or "repair required" in text_lower:
                    recommended_action = "repair_required"
                elif ("recommended_action" in text_lower or "recommended action" in text_lower) and "accept" in text_lower:
                    recommended_action = "accept"

                if not recommended_action:
                    return {}

                task_status = ""
                for candidate in ("complete", "partial", "unsupported", "failed"):
                    if candidate in text_lower:
                        task_status = candidate
                        break

                risk_level = ""
                for candidate in ("low", "medium", "high", "critical"):
                    if candidate in text_lower:
                        risk_level = candidate
                        break

                return {
                    "recommended_action": recommended_action or "accept",
                    "task_status": task_status or ("complete" if recommended_action != "repair_required" else "partial"),
                    "risk_level": risk_level or ("medium" if recommended_action == "repair_required" else "low"),
                    "repair_worthwhile": recommended_action == "repair_required",
                    "failure_types": [],
                    "missing_requirements": [],
                    "unsupported_claims": [],
                    "contradictions": [],
                    "evidence_gaps": [],
                    "reason": text.strip()[:500],
                    "suggested_note": "",
                }
            try:
                data = json.loads(match.group(0))
            except Exception:
                try:
                    candidate = match.group(0)
                    candidate = re.sub(r"\btrue\b", "True", candidate)
                    candidate = re.sub(r"\bfalse\b", "False", candidate)
                    candidate = re.sub(r"\bnull\b", "None", candidate)
                    data = ast.literal_eval(candidate)
                except Exception:
                    return {}

        if not isinstance(data, dict):
            return {}

        def normalize_list(value):
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str):
                value = value.strip()
                return [value] if value else []
            return [str(value).strip()]

        task_status = str(data.get("task_status", "")).strip().lower()
        risk_level = str(data.get("risk_level", "")).strip().lower()
        recommended_action = str(data.get("recommended_action", "")).strip().lower()
        if task_status not in {"complete", "partial", "unsupported", "failed"}:
            task_status = "partial" if data else ""
        if risk_level not in {"low", "medium", "high", "critical"}:
            risk_level = "medium" if data else ""
        if recommended_action not in {"accept", "tighten_only", "repair_required"}:
            recommended_action = "repair_required" if task_status in {"partial", "unsupported", "failed"} else "accept"

        repair_worthwhile = data.get("repair_worthwhile")
        if isinstance(repair_worthwhile, str):
            repair_worthwhile = repair_worthwhile.strip().lower() in ("true", "1", "yes", "on")
        else:
            repair_worthwhile = bool(repair_worthwhile)

        return {
            "recommended_action": recommended_action,
            "task_status": task_status,
            "risk_level": risk_level,
            "repair_worthwhile": repair_worthwhile,
            "failure_types": normalize_list(data.get("failure_types")),
            "missing_requirements": normalize_list(data.get("missing_requirements")),
            "unsupported_claims": normalize_list(data.get("unsupported_claims")),
            "contradictions": normalize_list(data.get("contradictions")),
            "evidence_gaps": normalize_list(data.get("evidence_gaps")),
            "reason": str(data.get("reason", "")).strip(),
            "suggested_note": str(data.get("suggested_note", "")).strip(),
        }

    @staticmethod
    def score_auto_eval(evaluation: dict) -> tuple[float, list[str]]:
        """Convert structured audit output into a deterministic repair score."""
        recommended_action = evaluation.get("recommended_action", "")
        task_status = evaluation.get("task_status", "")
        risk_level = evaluation.get("risk_level", "")
        failure_types = evaluation.get("failure_types", []) or []
        missing_requirements = evaluation.get("missing_requirements", []) or []
        unsupported_claims = evaluation.get("unsupported_claims", []) or []
        contradictions = evaluation.get("contradictions", []) or []
        evidence_gaps = evaluation.get("evidence_gaps", []) or []
        repair_worthwhile = bool(evaluation.get("repair_worthwhile"))

        score = 0.0
        reasons = []

        status_weights = {"complete": 0.05, "partial": 0.35, "unsupported": 0.58, "failed": 0.72}
        risk_weights = {"low": 0.0, "medium": 0.08, "high": 0.18, "critical": 0.28}
        score += status_weights.get(task_status, 0.20)
        score += risk_weights.get(risk_level, 0.0)

        if recommended_action == "tighten_only":
            score = min(score, 0.62)
            reasons.append("recommended_action:tighten_only")
        elif recommended_action == "repair_required":
            score += 0.10
            reasons.append("recommended_action:repair_required")

        if repair_worthwhile:
            score += 0.10
            reasons.append("repair_worthwhile")
        if task_status in ("partial", "unsupported", "failed"):
            reasons.append(f"task_status:{task_status}")
        if risk_level in ("high", "critical"):
            reasons.append(f"risk_level:{risk_level}")

        score += min(0.24, 0.08 * len(failure_types))
        score += min(0.18, 0.06 * len(missing_requirements))
        score += min(0.24, 0.12 * len(unsupported_claims))
        score += min(0.24, 0.12 * len(contradictions))
        score += min(0.18, 0.06 * len(evidence_gaps))

        if failure_types:
            reasons.extend(f"failure_type:{item}" for item in failure_types[:4])
        if unsupported_claims:
            reasons.append("unsupported_claims")
        if contradictions:
            reasons.append("contradictions")
        if missing_requirements:
            reasons.append("missing_requirements")
        if evidence_gaps:
            reasons.append("evidence_gaps")

        if task_status == "failed":
            score = max(score, 0.92)
        elif contradictions:
            score = max(score, 0.88)
        elif unsupported_claims and risk_level in ("high", "critical"):
            score = max(score, 0.85)
        elif task_status in ("partial", "unsupported") and failure_types and (missing_requirements or evidence_gaps):
            score = max(score, 0.74)

        return min(1.0, score), reasons

    @staticmethod
    def classify_strategy(record: dict, note: str = "") -> dict:
        """Choose a repair strategy family and tool-family hints for the next pass."""
        query = (record.get("query") or "").lower()
        note_lower = (note or "").lower()
        raw = (record.get("raw_llm_response") or "").lower()
        combined = " ".join(part for part in [query, note_lower, raw] if part)

        strategy = {
            "family": "generic_repair",
            "reason": "General repair pass using the previous answer and tool outputs.",
            "preferred_tools": [],
            "avoid_tools": [],
            "completion_hint": "If a tool result already contains the answer, stop and answer directly from that result.",
        }

        if any(token in combined for token in ["jarvis-intel", "user_profile", "user profile", ".md", "profile"]):
            strategy.update(
                {
                    "family": "intel_file_lookup",
                    "reason": "The user referenced a specific intel/profile file, so direct file inspection should come before semantic recall.",
                    "preferred_tools": ["manage_intel"],
                    "avoid_tools": ["semantic_recall", "search_memory", "deep_memory_search"],
                    "completion_hint": "If manage_intel returns file content with the answer, answer from that content directly instead of calling another memory tool.",
                }
            )
            return strategy

        asks_for_fresh_research = any(
            token in combined
            for token in ["what size", "which size", "amazon product", "purchase", "buy", "compatible", "spec", "specs", "recommend", "compare", "price", "pricing"]
        )

        overtooled_complaint = any(
            token in combined
            for token in [
                "max out tool turns",
                "maxed out tool turns",
                "max tool turns",
                "too many tool",
                "tool happy",
                "used canvas 3 times",
                "used canvas three times",
                "same tool",
                "duplicate tool",
                "repeated tool",
                "re-read",
                "reread",
                "should have had enough info",
                "stop calling tools",
                "stop using tools",
            ]
        )

        if overtooled_complaint:
            strategy.update(
                {
                    "family": "minimal_repair",
                    "reason": "The complaint is about over-tooling or repeated tool calls, so the repair should avoid artifact churn and answer from existing evidence unless one clearly different tool is needed.",
                    "preferred_tools": [],
                    "avoid_tools": ["canvas", "search_memory", "semantic_recall"],
                    "completion_hint": "Audit the previous tool results first. If they already contain enough evidence, answer directly. If not, use at most one clearly different tool call and then stop.",
                }
            )
            return strategy

        strong_claim_terms = ["shutdown", "shut down", "deprecated", "removed", "disabled", "not available", "sent", "updated", "created", "saved"]
        if any(term in combined for term in strong_claim_terms):
            strategy.update(
                {
                    "family": "verification_repair",
                    "reason": "The prior answer made or challenged a strong factual claim that should be verified before repeating.",
                    "preferred_tools": ["brave_search", "fetch_url", "bash"],
                    "avoid_tools": ["semantic_recall", "search_memory"],
                    "completion_hint": "Do not repeat strong claims unless the repair pass verifies them with a relevant live or direct inspection tool.",
                }
            )
            return strategy

        if any(token in combined for token in ["canvas", "canva", "page", "slides", "doc", "update the page", "update canvas"]):
            if asks_for_fresh_research:
                strategy.update(
                    {
                        "family": "verification_repair",
                        "reason": "The note mentions an artifact, but the unresolved task is still a fresh factual/product question that needs verification before any artifact update.",
                        "preferred_tools": ["brave_search", "fetch_url"],
                        "avoid_tools": ["semantic_recall"],
                        "completion_hint": "Verify the missing product/spec facts first. Only update Canvas after you have verified findings worth saving.",
                    }
                )
                return strategy
            strategy.update(
                {
                    "family": "artifact_update",
                    "reason": "The failure likely involves an artifact that may need to be checked or updated instead of just re-explained.",
                    "preferred_tools": ["canvas"],
                    "avoid_tools": ["semantic_recall"],
                    "completion_hint": "If the artifact is wrong and you have enough context, update it and then clearly summarize the correction.",
                }
            )
            return strategy

        if any(token in combined for token in ["memory", "remember", "asked me before", "call me", "what is my name"]):
            strategy.update(
                {
                    "family": "memory_lookup",
                    "reason": "The question asks about prior user information, so recall-style tools are appropriate unless a direct file lead exists.",
                    "preferred_tools": ["deep_memory_search", "semantic_recall", "search_memory"],
                    "avoid_tools": [],
                    "completion_hint": "If memory tools remain weak and the user supplied a concrete source, switch to that source instead of repeating recall.",
                }
            )
            return strategy

        return strategy

    @staticmethod
    def format_strategy(strategy: dict) -> str:
        """Render repair strategy hints into prompt-ready text."""
        preferred = ", ".join(strategy.get("preferred_tools", [])) or "(none)"
        avoid = ", ".join(strategy.get("avoid_tools", [])) or "(none)"
        return (
            f"- Strategy family: {strategy.get('family', 'generic_repair')}\n"
            f"- Why: {strategy.get('reason', '')}\n"
            f"- Prefer these tools or tool families first: {preferred}\n"
            f"- Avoid starting with: {avoid}\n"
            f"- Completion hint: {strategy.get('completion_hint', '')}"
        )
