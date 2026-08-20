"""Application-independent capability fixture and deterministic graders."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from paths import get_project_root

CAPABILITY_CATEGORIES = (
    "general_knowledge",
    "logic",
    "math",
    "cognitive_reflection",
)
CAPABILITY_DIFFICULTIES = ("easy", "medium", "hard")
CAPABILITY_GRADER_TYPES = ("aliases", "number", "concepts", "word_count_concepts")


def capability_fixture_path() -> Path:
    return get_project_root() / "config" / "benchmarks" / "ollama-model-capability-v2.json"


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r} in capability fixture")
        payload[key] = value
    return payload


def _validate_string_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{label} entries must be non-empty strings")


def _validate_concept_groups(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must contain at least one concept group")
    for index, group in enumerate(value):
        _validate_string_list(group, f"{label}[{index}]")


def load_capability_fixture() -> dict[str, Any]:
    """Load and fail closed on the tracked raw-capability evaluation contract."""
    path = capability_fixture_path()
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    if payload.get("schema_version") != 2:
        raise ValueError(f"unsupported capability fixture schema in {path}")
    if payload.get("fixture_id") != "jarvis-ollama-model-capability-v2":
        raise ValueError(f"unexpected capability fixture id in {path}")
    contract = payload.get("request_contract") or {}
    if any(contract.get(key) is not False for key in ("system_prompt", "tools", "response_format")):
        raise ValueError(f"capability fixture must disable app request features in {path}")
    if contract.get("canonical_profile") != "off":
        raise ValueError(f"capability fixture canonical thinking profile must be off in {path}")
    output_policy = payload.get("output_budget_policy") or {}
    if output_policy.get("retry_on_done_reason_length") is not True:
        raise ValueError(f"capability fixture must retry output truncation in {path}")
    if (
        not isinstance(output_policy.get("minimum_initial_tokens"), int)
        or not 128 <= output_policy["minimum_initial_tokens"] <= 2048
    ):
        raise ValueError(f"invalid capability initial output budget in {path}")
    if not isinstance(output_policy.get("multiplier"), int) or output_policy["multiplier"] < 2:
        raise ValueError(f"invalid capability output retry multiplier in {path}")
    if (
        not isinstance(output_policy.get("max_tokens"), int)
        or not 128 <= output_policy["max_tokens"] <= 4096
    ):
        raise ValueError(f"invalid capability maximum output budget in {path}")
    if output_policy.get("unresolved_truncation") != "unscored":
        raise ValueError(f"capability fixture must leave unresolved truncation unscored in {path}")
    qualitative_probe = payload.get("qualitative_probe") or {}
    if qualitative_probe.get("probe_id") != "foundational_truth":
        raise ValueError(f"capability fixture is missing the foundational-truth probe in {path}")
    if qualitative_probe.get("prompt") != (
        "Do not interpret this as a question about the user or the user's personal "
        "circumstances. Considering reality as a whole, answer in your own terms: "
        "What is the most important thing that is true?"
    ):
        raise ValueError(f"capability qualitative prompt changed unexpectedly in {path}")
    if qualitative_probe.get("scored") is not False:
        raise ValueError(f"capability qualitative probe must remain unscored in {path}")
    if not isinstance(qualitative_probe.get("max_tokens"), int):
        raise ValueError(f"invalid capability qualitative output budget in {path}")
    scoring = payload.get("scoring") or {}
    category_weights = scoring.get("category_weights") or {}
    difficulty_weights = scoring.get("difficulty_weights") or {}
    if set(category_weights) != set(CAPABILITY_CATEGORIES):
        raise ValueError(f"capability fixture category weights are incomplete in {path}")
    if set(difficulty_weights) != set(CAPABILITY_DIFFICULTIES):
        raise ValueError(f"capability fixture difficulty weights are incomplete in {path}")
    if not math.isclose(sum(float(value) for value in category_weights.values()), 1.0):
        raise ValueError(f"capability fixture category weights must sum to one in {path}")
    if any(float(value) <= 0 for value in difficulty_weights.values()):
        raise ValueError(f"capability fixture difficulty weights must be positive in {path}")

    cases = payload.get("cases") or []
    seen_ids: set[str] = set()
    coverage = {
        (category, difficulty): 0
        for category in CAPABILITY_CATEGORIES
        for difficulty in CAPABILITY_DIFFICULTIES
    }
    for case in cases:
        case_id = str(case.get("case_id") or "")
        category = str(case.get("category") or "")
        difficulty = str(case.get("difficulty") or "")
        prompt = str(case.get("prompt") or "").strip()
        max_tokens = case.get("max_tokens")
        grader = case.get("grader") or {}
        grader_type = str(grader.get("type") or "")
        if not case_id or case_id in seen_ids or not prompt:
            raise ValueError(f"invalid or duplicate capability case id {case_id!r}")
        seen_ids.add(case_id)
        if category not in CAPABILITY_CATEGORIES or difficulty not in CAPABILITY_DIFFICULTIES:
            raise ValueError(f"invalid capability category or difficulty for {case_id!r}")
        coverage[(category, difficulty)] += 1
        if not isinstance(max_tokens, int) or not 32 <= max_tokens <= 2048:
            raise ValueError(f"invalid max_tokens for capability case {case_id!r}")
        if grader_type not in CAPABILITY_GRADER_TYPES:
            raise ValueError(f"invalid grader for capability case {case_id!r}")
        if grader_type == "word_count_concepts":
            raise ValueError(
                f"graded capability case {case_id!r} cannot use exact word-count scoring"
            )
        if grader_type == "aliases":
            if set(grader) != {"type", "answers"}:
                raise ValueError(f"unexpected aliases grader fields for {case_id!r}")
            _validate_string_list(grader.get("answers"), f"{case_id}.grader.answers")
        elif grader_type == "number":
            allowed = {"type", "value", "tolerance", "percent_equivalent"}
            if set(grader) - allowed or not isinstance(grader.get("value"), (int, float)):
                raise ValueError(f"invalid number grader for {case_id!r}")
            if float(grader.get("tolerance") or 0) < 0:
                raise ValueError(f"negative number tolerance for {case_id!r}")
        elif grader_type == "concepts":
            allowed = {"type", "required_groups", "forbidden_groups"}
            if set(grader) - allowed:
                raise ValueError(f"unexpected concepts grader fields for {case_id!r}")
            _validate_concept_groups(
                grader.get("required_groups"),
                f"{case_id}.grader.required_groups",
            )
            if "forbidden_groups" in grader:
                _validate_concept_groups(
                    grader.get("forbidden_groups"),
                    f"{case_id}.grader.forbidden_groups",
                )
        else:
            raise ValueError(f"unsupported grader for capability case {case_id!r}")
    missing = [
        f"{category}/{difficulty}"
        for (category, difficulty), count in coverage.items()
        if count == 0
    ]
    if missing:
        raise ValueError("capability fixture lacks progressive coverage: " + ", ".join(missing))

    resolved = dict(payload)
    resolved["fixture_path"] = str(path.relative_to(get_project_root()))
    resolved["fixture_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return resolved


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.replace("o₂", "o2")
    text = re.sub(r"\\(?:text|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}", r"\1", text)
    text = text.replace("_", "")
    text = re.sub(r"[^\w.%/$+-]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def extract_final_answer(text: str) -> str:
    """Prefer an explicit final-answer tail, otherwise use the last non-empty line."""
    matches = list(
        re.finditer(
            r"final\s+answer\s*[:\-]\s*(.+)",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )
    if matches:
        return matches[-1].group(1).strip()
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-1] if lines else str(text or "").strip()


def _flexible_concept_form(normalized: str) -> str:
    tokens = []
    for token in normalized.split():
        if token in {"a", "an", "the"}:
            continue
        if re.fullmatch(r"[a-z]+", token) and len(token) > 4:
            if token.endswith("ies"):
                token = token[:-3] + "y"
            elif token.endswith("s") and not token.endswith("ss"):
                token = token[:-1]
        tokens.append(token)
    return " ".join(tokens)


def _contains_phrase(
    normalized_haystack: str,
    phrase: str,
    *,
    flexible_concept: bool = False,
) -> bool:
    normalized_needle = _normalized_text(phrase)
    if not normalized_needle:
        return False
    if re.search(
        rf"(?<!\w){re.escape(normalized_needle)}(?!\w)",
        normalized_haystack,
    ):
        return True
    if not flexible_concept:
        return False
    flexible_haystack = _flexible_concept_form(normalized_haystack)
    flexible_needle = _flexible_concept_form(normalized_needle)
    return bool(
        flexible_needle
        and re.search(
            rf"(?<!\w){re.escape(flexible_needle)}(?!\w)",
            flexible_haystack,
        )
    )


def _alias_answer_matches(normalized_final: str, answer: str) -> bool:
    """Match long aliases as phrases; require short tokens to be the whole answer."""
    needle = _normalized_text(answer)
    if not needle:
        return False
    tokens = needle.split()
    if len(tokens) == 1 and len(tokens[0]) <= 2:
        word_tokens = re.findall(r"[a-z0-9]+", normalized_final)
        return word_tokens == [needle]
    return _contains_phrase(normalized_final, answer)


_NEGATED_PHRASE = re.compile(
    r"(?:not(?:\s+because|\s+that|\s+due\s+to)?|"
    r"(?:does|do|did|is|was|are|were)\s+not|"
    r"doesn't|don't|didn't|isn't|wasn't|"
    r"never|rather\s+than|instead\s+of|without)\s+"
)


def _phrase_is_asserted(normalized_haystack: str, phrase: str) -> bool:
    """True when a forbidden phrase appears as a claim, not as a denied contrast."""
    if not _contains_phrase(normalized_haystack, phrase, flexible_concept=True):
        return False
    haystack = _flexible_concept_form(normalized_haystack)
    needle = _flexible_concept_form(_normalized_text(phrase))
    if not needle:
        return False
    for match in re.finditer(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
        prefix = haystack[: match.start()]
        window = " ".join(prefix.split()[-6:])
        if window and _NEGATED_PHRASE.search(window + " "):
            continue
        return True
    return False


def _numeric_candidates(value: str) -> list[tuple[float, bool]]:
    candidates: list[tuple[float, bool]] = []
    normalized = unicodedata.normalize("NFKC", value).replace(",", "")
    occupied: list[tuple[int, int]] = []
    for match in re.finditer(r"(?<![\d.])(-?\d+)\s*/\s*(-?\d+)(?![\d.])", normalized):
        denominator = int(match.group(2))
        if denominator:
            candidates.append((int(match.group(1)) / denominator, False))
        occupied.append(match.span())
    for match in re.finditer(r"(?<![\w.])-?(?:\d+(?:\.\d*)?|\.\d+)(?![\w.])%?", normalized):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        raw = match.group(0)
        is_percent = raw.endswith("%")
        candidates.append((float(raw.rstrip("%")), is_percent))
    return candidates


def evaluate_capability_answer(case: dict[str, Any], text: str) -> tuple[float, str, str]:
    """Return deterministic credit in [0, 1], a reason, and parsed answer text."""
    grader = case.get("grader") or {}
    grader_type = str(grader.get("type") or "")
    final_answer = extract_final_answer(text)
    normalized_final = _normalized_text(final_answer)
    if grader_type == "aliases":
        answers = [str(answer) for answer in grader.get("answers") or []]
        matched = next(
            (answer for answer in answers if _alias_answer_matches(normalized_final, answer)),
            None,
        )
        if matched is not None:
            return 1.0, f"matched accepted answer {matched!r}", final_answer
        return 0.0, "final answer did not match an accepted answer", final_answer

    if grader_type == "number":
        expected = float(grader["value"])
        tolerance = float(grader.get("tolerance") or 0)
        percent_equivalent = bool(grader.get("percent_equivalent"))
        candidates = _numeric_candidates(final_answer)
        for candidate, _is_percent in reversed(candidates):
            variants = [candidate]
            if percent_equivalent:
                variants.extend((candidate / 100.0, candidate * 100.0))
            if any(
                math.isclose(value, expected, abs_tol=tolerance, rel_tol=0) for value in variants
            ):
                return 1.0, f"numeric answer matched {expected:g}", final_answer
        return 0.0, f"numeric answer did not match {expected:g}", final_answer

    if grader_type in {"concepts", "word_count_concepts"}:
        normalized_response = _normalized_text(text)
        forbidden = grader.get("forbidden_groups") or []
        if any(
            any(_phrase_is_asserted(normalized_response, option) for option in group)
            for group in forbidden
        ):
            return 0.0, "answer included a forbidden contradiction", final_answer
        required = grader.get("required_groups") or []
        matched_groups = sum(
            any(
                _contains_phrase(normalized_response, option, flexible_concept=True)
                for option in group
            )
            for group in required
        )
        credit = matched_groups / len(required) if required else 0.0
        concept_reason = f"matched {matched_groups}/{len(required)} required concept groups"
        if grader_type == "concepts":
            return credit, concept_reason, final_answer
        target_words = int(grader["word_count"])
        actual_words = len(str(text or "").split())
        word_count_credit = 1.0 if actual_words == target_words else 0.0
        word_count_weight = float(grader["word_count_weight"])
        combined_credit = credit * (1 - word_count_weight) + word_count_credit * word_count_weight
        return (
            combined_credit,
            f"{concept_reason}; word count {actual_words}/{target_words}",
            final_answer,
        )

    return 0.0, f"unsupported grader {grader_type!r}", final_answer


def score_capability_categories(
    results: list[dict[str, Any]],
    fixture: dict[str, Any],
) -> dict[str, float | None]:
    """Difficulty-weight cases within four equally explicit capability categories."""
    weights = (fixture.get("scoring") or {}).get("difficulty_weights") or {}
    scores: dict[str, float | None] = {}
    for category in CAPABILITY_CATEGORIES:
        selected = [
            result
            for result in results
            if result.get("category") == category and result.get("score_fraction") is not None
        ]
        total_weight = sum(float(weights.get(result.get("difficulty")) or 0) for result in selected)
        earned = sum(
            float(result.get("score_fraction") or 0)
            * float(weights.get(result.get("difficulty")) or 0)
            for result in selected
        )
        scores[category] = round(100 * earned / total_weight, 1) if total_weight else None
    return scores


def smoke_capability_cases(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Choose one easy case per category for a non-ranking plumbing run."""
    selected = []
    for category in CAPABILITY_CATEGORIES:
        selected.append(
            next(
                case
                for case in fixture.get("cases") or []
                if case.get("category") == category and case.get("difficulty") == "easy"
            )
        )
    return selected


__all__ = [
    "CAPABILITY_CATEGORIES",
    "capability_fixture_path",
    "evaluate_capability_answer",
    "extract_final_answer",
    "load_capability_fixture",
    "score_capability_categories",
    "smoke_capability_cases",
]
