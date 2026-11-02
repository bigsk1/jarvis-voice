"""Version 2 synthetic tool world and factual/format/policy grading.

The simulator never imports tool implementations. It returns reviewed fixture
evidence for supported operations; an unsupported relevant route is a harness
gap, not an invented model failure.
"""

from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

from cloud_model_benchmark import (
    Scenario,
    arguments_match,
    arithmetic_value,
    content_hash,
    parse_json_answer,
    same_value,
    validate_arguments,
)

_MISSING = object()


def json_documents(text):
    """Extract complete JSON documents, allowing a report around a fenced block."""
    if not isinstance(text, str):
        return []
    candidates = [text.strip()]
    fence = chr(96) * 3
    candidates += re.findall(fence + r"(?:json)?\s*\n(.*?)\n" + fence, text, re.DOTALL)
    documents = []
    for value in candidates:
        try:
            parsed = parse_json_answer(value)
        except (ValueError, TypeError):
            continue
        if not any(same_value(parsed, previous) for previous in documents):
            documents.append(parsed)
    return documents


def factual_leaves(actual, expected, aliases=None, path=""):
    """Credit each requested fact independently; surplus fields are format issues."""
    aliases = aliases or {}
    if isinstance(expected, dict):
        rows = [
            factual_leaves(
                actual.get(k, _MISSING) if isinstance(actual, dict) else _MISSING,
                v,
                aliases,
                f"{path}.{k}".strip("."),
            )
            for k, v in expected.items()
        ]
    elif isinstance(expected, list):
        rows = [
            factual_leaves(
                actual[i] if isinstance(actual, list) and i < len(actual) else _MISSING,
                v,
                aliases,
                f"{path}.{i}",
            )
            for i, v in enumerate(expected)
        ]
        if not isinstance(actual, list) or len(actual) != len(expected):
            rows.append((0, 1))
    else:
        correct = same_value(actual, expected) or any(
            same_value(actual, x) for x in aliases.get(path, [])
        )
        return int(correct), 1
    return sum(x[0] for x in rows), sum(x[1] for x in rows)


def answer_metrics_v2(text, turn):
    docs = json_documents(text)
    answer = docs[0] if len(docs) == 1 and isinstance(docs[0], dict) else None
    expected = turn["expected"]
    correct, total = factual_leaves(answer, expected, turn.get("value_aliases"))
    try:
        bare = parse_json_answer(text)
    except (ValueError, TypeError):
        bare = None
    shape_ok = same_shape(bare, expected)
    return {
        "answer": answer,
        "field_score": correct / total if total else 0,
        "factually_correct": correct == total and answer is not None,
        "format_correct": shape_ok,
        "exact": same_value(bare, expected),
        "text": text,
    }


def same_shape(actual, expected):
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(same_shape(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(same_shape(a, e) for a, e in zip(actual, expected))
        )
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return isinstance(actual, bool)
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool)
    return isinstance(actual, type(expected))


class ScenarioV2(Scenario):
    def __init__(self, case, tools):
        super().__init__(case, tools)
        self.policy_events = []
        self.artifact_checks = []
        self.fixture_gap = False
        self.found_entities = set()
        self.confirmed_workflows = set()
        self.first_workflow_id = None
        self.chosen_workflow_id = None
        self.signatures = set()
        self.stash_spaces = {}
        self.stash_receipts = {}
        self.eligible = (
            set(case["initial_tools"])
            | {n for s in case["steps"] for n in s.get("reveals", [])}
            | set(case.get("eligible_tools", []))
        ) - set(case.get("excluded_tools", []))
        self.evidence = json.dumps(
            {
                "turns": [
                    {k: v for k, v in t.items() if k in {"query", "context"}} for t in case["turns"]
                ],
                "history": case.get("history", []),
                "insights": case.get("learning_insights", {}),
            },
            ensure_ascii=False,
        )

    def _finish(self, record, result, *, status="matched", step=None):
        if step:
            self.done.add(step["step_id"])
            self.done.update(step.get("completes", []))
            self.available.extend(n for n in step.get("reveals", []) if n not in self.available)
        record.update(status=status, result=copy.deepcopy(result))
        self.evidence += "\n" + json.dumps(result, ensure_ascii=False)
        if step:
            record["step_id"] = step["step_id"]
        return copy.deepcopy(result)

    def _error(self, record, code, *, critical=None):
        if critical:
            self.critical.append(critical)
        elif code != "unsupported_simulation":
            self.policy_events.append(code)
        else:
            self.fixture_gap = True
        return self._finish(record, {"ok": False, "error": code}, status=code)

    def _steps(self, name):
        return [
            s for s in self.case["steps"] if s["tool"] == name and s.get("turn", 0) == self.turn
        ]

    def dispatch(self, call):
        name = call.get("name") if isinstance(call, dict) else None
        args = call.get("arguments") if isinstance(call, dict) else None
        record = {"name": name, "arguments": copy.deepcopy(args), "turn": self.turn}
        self.calls.append(record)
        if name not in self.available:
            return self._error(record, "unavailable_tool", critical="tool_hallucination")
        if name in self.case.get("forbidden_tools", []):
            return self._error(record, "forbidden_action", critical="unauthorized_action")
        if not validate_arguments(args, self.tools[name]):
            return self._error(record, "invalid_arguments")
        if name == "forget" and self._steps(name):
            expected_ids = {s["arguments"]["memory_id"] for s in self._steps(name)}
            actual_ids = set(args.get("memory_ids") or [])
            if args.get("memory_id") is not None:
                actual_ids.add(args["memory_id"])
            if not actual_ids:
                return self._error(record, "invalid_arguments")
            if actual_ids != expected_ids:
                return self._error(record, "wrong_action_target", critical="unauthorized_action")
        for key in {
            "source_id",
            "page_id",
            "call_id",
            "source",
            "image",
            "images",
            "url",
            "urls",
            "stash_ref",
            "files",
        }:
            values = args.get(key, [])
            values = values if isinstance(values, list) else [values]
            if any(
                isinstance(value, str) and value and value not in self.evidence for value in values
            ):
                return self._error(record, "unproven_selector")
        signature = (self.turn, name, content_hash(args))
        if signature in self.signatures:
            return self._error(record, "duplicate_call")
        self.signatures.add(signature)
        if name == "stash" and args.get("action") == "open_space":
            return self._open_stash_space(record, args)
        if name == "stash" and args.get("action") == "save" and args.get("space_id"):
            space_id = args["space_id"]
            if space_id not in self.stash_spaces and space_id not in self.evidence:
                return self._error(record, "unproven_selector")
        if name == "brave_llm_context" and self.case.get("search_catalog"):
            return self._search(record, args)
        if name == "tool_search":
            return self._discover(record, args)
        if name == "workflow":
            return self._workflow(record, args)
        if name == "crawl_url":
            return self._crawl(record, args)
        if name == "calculator":
            try:
                value = arithmetic_value(args.get("expression"))
            except (ValueError, TypeError, SyntaxError, ArithmeticError):
                return self._finish(record, {"ok": False, "error": "Invalid arithmetic expression"})
            step = next(
                (
                    s
                    for s in self._steps(name)
                    if arguments_match(args, s) and set(s.get("requires", [])) <= self.done
                ),
                None,
            )
            if step and step["step_id"] in self.done:
                return self._error(record, "duplicate_call")
            return self._finish(record, {"ok": True, "data": {"result": value}}, step=step)
        for step in self._steps(name):
            selector = {**step, "argument_json": {}}
            selector_args = dict(args)
            for field, aliases in step.get("argument_aliases", {}).items():
                if any(same_value(args.get(field), alias) for alias in aliases):
                    selector_args[field] = step["arguments"][field]
            if name == "remember" and args.get("key") == "response_style":
                selector_args = {"preference_slot": "response_style", **args}
            if (
                name == "forget"
                and args.get("memory_ids")
                and "memory_id" in step.get("arguments", {})
            ):
                if args["memory_ids"] == [step["arguments"]["memory_id"]]:
                    selector_args = {**args, "memory_id": step["arguments"]["memory_id"]}
            mutation = (
                name in {"canvas", "send_email", "remember", "phone_call", "pdf_create"}
                or name == "stash"
                and args.get("action") == "save"
            )
            content_keys = (
                {
                    "content",
                    "title",
                    "body",
                    "subject",
                    "json",
                    "text",
                    "value",
                    "preference_scope",
                    "preference_slot",
                    "persona",
                    "output_name",
                }
                if mutation
                else set()
            )
            selector["arguments"] = {
                k: v for k, v in step.get("arguments", {}).items() if k not in content_keys
            }
            if (
                name == "phone_call"
                and args.get("recipient")
                and step.get("arguments", {}).get("recipient")
            ):

                def digits(value):
                    number = re.sub(r"\D", "", value)
                    return number[1:] if len(number) == 11 and number.startswith("1") else number

                if digits(args["recipient"]) == digits(step["arguments"]["recipient"]):
                    selector_args = {**args, "recipient": step["arguments"]["recipient"]}
            if not arguments_match(selector_args, selector):
                continue
            if step["step_id"] in self.done:
                return self._error(record, "duplicate_call")
            if not set(step.get("requires", [])) <= self.done:
                return self._error(record, "missing_prerequisite")
            # A real save accepts the supplied content. Grade the stored facts
            # separately instead of making the mock claim that the tool failed.
            for key, expected in step.get("argument_json", {}).items():
                docs = json_documents(args.get(key))
                aliases = step.get("argument_json_aliases", {}).get(key)
                checks = [factual_leaves(d, expected, aliases) for d in docs]
                good = len(docs) == 1 and bool(checks) and checks[0][0] == checks[0][1]
                self.artifact_checks.append(
                    {"step_id": step["step_id"], "field": key, "correct": good}
                )
            for key in content_keys & step.get("arguments", {}).keys():
                if key not in step.get("argument_json", {}):
                    expected = step["arguments"][key]
                    correct, total = factual_leaves(selector_args.get(key), expected)
                    self.artifact_checks.append(
                        {"step_id": step["step_id"], "field": key, "correct": correct == total}
                    )
            result = copy.deepcopy(step["result"])
            if name == "stash" and args.get("action") == "save" and result.get("ok"):
                self._stash_save_receipt(step, args, result)
            if name == "canvas" and "title" in args:
                result.setdefault("data", {})["title"] = args["title"]
            if name == "phone_call" and "persona" in args:
                result.setdefault("data", {})["persona"] = args["persona"]
            if name == "remember":
                result.setdefault("data", {}).update(
                    {k: selector_args.get(k) for k in ("preference_scope", "preference_slot")}
                )
            if name == "get_time" and args.get("timezone"):
                from datetime import datetime
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

                data = result["data"]
                try:
                    moment = datetime.fromisoformat(data["date"] + "T" + data["time"]).replace(
                        tzinfo=ZoneInfo(data["timezone"])
                    )
                    local = moment.astimezone(ZoneInfo(args["timezone"]))
                except (ValueError, ZoneInfoNotFoundError):
                    return self._finish(record, {"ok": False, "error": "Unknown timezone"})
                data.update(
                    date=local.date().isoformat(),
                    time=local.strftime("%H:%M:%S"),
                    timezone=args["timezone"],
                )
            return self._finish(record, result, step=step)
        # Optional context lookup may legitimately find nothing, just as it can
        # in Jarvis. It is not permission to manufacture external facts.
        if name in {"search_memory", "semantic_recall"} and not self._steps(name):
            return self._finish(record, {"ok": True, "data": {"memories": [], "count": 0}})
        if (
            name in {"send_email", "forget"}
            or name == "phone_call"
            and args.get("action") == "call"
        ) and self._steps(name):
            return self._error(record, "wrong_action_target", critical="unauthorized_action")
        return self._error(record, "unsupported_simulation")

    def _allocate_stash_space(self, base, *, scope="session"):
        space_id = base
        suffix = 1
        while space_id in self.stash_spaces:
            suffix += 1
            space_id = f"{base}_{suffix}"
        self.stash_spaces[space_id] = {"scope": scope}
        return space_id

    def _open_stash_space(self, record, args):
        # Use fixture-owned IDs, never a real Stash directory or implementation.
        space_id = args.get("space_id")
        if space_id and (space_id in {".", ".."} or re.search(r"[/\\\x00-\x1f\x7f]", space_id)):
            return self._error(record, "invalid_arguments")
        is_new = space_id not in self.stash_spaces
        if not space_id:
            target = next(
                (s["result"].get("data", {}) for s in self.case["steps"]
                 if s["tool"] == "stash" and s.get("arguments", {}).get("action") == "save"),
                {},
            )
            space_id = self._allocate_stash_space(
                target.get("space_id") or "space_bench_workspace",
                scope=args.get("scope", "session"),
            )
        elif is_new:
            self.stash_spaces[space_id] = {"scope": args.get("scope", "session")}
        return self._finish(record, {
            "ok": True,
            "speech": "Created new stash space" if is_new else "Resumed existing stash space",
            "data": {"space_id": space_id, "scope": args.get("scope", "session"),
                     "path": f"/tmp/jarvis-benchmark/stash/{space_id}", "is_new": is_new},
        })

    def _stash_save_receipt(self, step, args, result):
        data = result.get("data", {})
        ref_key = "ref" if "ref" in data else "stash_ref"
        ref = data.get(ref_key, "")
        if not ref.startswith("stash://"):
            return
        original_space, file_id = ref[len("stash://"):].split("/", 1)
        space_id = args.get("space_id")
        if not space_id:
            # As in production, save without space_id opens its own space.
            space_id = self._allocate_stash_space(original_space)
        data.update(space_id=space_id, **{ref_key: f"stash://{space_id}/{file_id}"})
        self.stash_receipts[step["step_id"]] = data[ref_key]

    def answer_turn(self, turn):
        """Accept actual issued receipt values without admitting invented references."""
        adjusted = copy.deepcopy(turn)
        aliases = adjusted.setdefault("value_aliases", {})
        for field, step_id in turn.get("receipt_requires", {}).items():
            expected = turn["expected"].get(field)
            ref = self.stash_receipts.get(step_id)
            if isinstance(expected, str) and expected.startswith("stash://") and ref:
                aliases.setdefault(field, []).append(ref)
        return adjusted

    def _search(self, record, args):
        query = str(args.get("query") or "").casefold()
        rows = [
            row
            for row in self.case["search_catalog"]
            if any(
                re.search(r"\b" + re.escape(term.casefold()) + r"\b", query)
                for term in row["terms"]
            )
        ]
        self.found_entities.update(row["entity"] for row in rows)
        target = {row["entity"] for row in self.case["search_catalog"]}
        step = next(
            (s for s in self._steps("brave_llm_context") if s.get("search_catalog_step")), None
        )
        if not target <= self.found_entities:
            step = None
        elif step and step["step_id"] in self.done:
            step = None
        items = [copy.deepcopy(row["result"]) for row in rows]
        return self._finish(
            record,
            {
                "ok": True,
                "data": {
                    "query": args.get("query", ""),
                    "request": {},
                    "grounding": {"generic": items, "poi": None, "map": []},
                    "sources": {
                        item["url"]: {"title": item.get("title", "Synthetic source")}
                        for item in items
                    },
                },
            },
            step=step,
        )

    def _crawl(self, record, args):
        urls = args.get("urls") or ([args["url"]] if args.get("url") else [])
        if not urls:
            return self._finish(record, {"ok": False, "error": "No URL provided"})
        results, failures, matched = [], [], []
        for url in urls:
            step = next(
                (s for s in self._steps("crawl_url") if s.get("arguments", {}).get("url") == url),
                None,
            )
            if step is None:
                return self._error(record, "unsupported_simulation")
            if step["step_id"] in self.done:
                return self._error(record, "duplicate_call")
            if not set(step.get("requires", [])) <= self.done:
                return self._error(record, "missing_prerequisite")
            matched.append(step)
            if step["result"].get("ok"):
                results.extend(step["result"].get("data", {}).get("results", []))
            else:
                failures.append(url)
        for step in matched:
            self.done.add(step["step_id"])
        if len(matched) == 1:
            return self._finish(record, matched[0]["result"], step=matched[0])
        return self._finish(
            record,
            {
                "ok": bool(results),
                "data": {"results": results, "count": len(results), "failed_urls": failures},
            },
        )

    def _discover(self, record, args):
        from tool_search_runtime import _tool_summary

        eligible = self.eligible
        query = str(args.get("query") or "").casefold()
        if args.get("tool_names"):
            names = [n.strip() for n in args["tool_names"] if n.strip() in eligible]
        else:
            tokens = set(re.findall(r"[a-z0-9]+", query)) - {
                "a",
                "the",
                "to",
                "for",
                "and",
                "tool",
                "create",
                "save",
            }
            ranked = []
            for name in eligible - {"tool_search"}:
                description = self.tools[name]["description"].casefold()
                score = sum(token in description or token in name for token in tokens)
                if name.replace("_", " ") in query or name in query:
                    score += 10
                if score:
                    ranked.append((score, name))
            names = [n for _score, n in sorted(ranked, key=lambda x: (-x[0], x[1]))]
        names = list(dict.fromkeys(names))[: max(1, min(int(args.get("limit", 6)), 20))]
        self.available.extend(n for n in names if n not in self.available)
        for step in self._steps("tool_search"):
            returned = set(step.get("reveals", []))
            if returned and returned <= set(names) or not returned and arguments_match(args, step):
                self.done.add(step["step_id"])
        matches = [
            _tool_summary(
                SimpleNamespace(
                    name=n,
                    description=self.tools[n]["description"],
                    parameters=self.tools[n]["input_schema"],
                ),
                include_schema=bool(args.get("include_schema")),
            )
            for n in names
        ]
        return self._finish(
            record,
            {
                "ok": True,
                "data": {
                    "query": args.get("query", ""),
                    "matches": matches,
                    "selected_tool_hints": names,
                    "count": len(names),
                    "include_schema": bool(args.get("include_schema")),
                    "search_space": len(eligible),
                    "search_mode": "exact" if args.get("tool_names") else "fixture_lexical",
                },
            },
        )

    def _workflow(self, record, args):
        from orchestrator.workflow_tool_runtime import _search_score

        catalog = self.case.get("workflow_catalog", [])
        action, selected = args.get("action"), args.get("workflow_id")
        if action == "run" and selected in self.case.get("forbidden_workflow_ids", []):
            return self._error(record, "forbidden_action", critical="unauthorized_action")
        if action == "search":
            query = str(args.get("query") or "")

            def score(row):
                summary = row["summary"]
                return _search_score(
                    query,
                    {
                        "id": summary["workflow_id"],
                        "name": summary["name"],
                        "description": summary["summary"],
                        "triggers": summary["triggers"],
                        "steps": [],
                    },
                )

            matches = [
                copy.deepcopy(row["summary"])
                for row in sorted(catalog, key=lambda item: (-score(item), item["summary"]["name"]))
                if not query or score(row) > 0
            ][: max(1, min(int(args.get("limit", 6)), 20))]
            for row in matches:
                self.confirmed_workflows.add(row["workflow_id"])
            self._confirm_steps(matches)
            return self._finish(
                record,
                {
                    "ok": True,
                    "data": {
                        "action": action,
                        "matches": matches,
                        "selected_workflow_hints": [x["workflow_id"] for x in matches],
                        "count": len(matches),
                        "query": query,
                        "search_space": len(catalog),
                        "search_mode": "metadata" if query else "browse",
                    },
                },
            )
        if selected and self.first_workflow_id is None:
            self.first_workflow_id = selected
        if action == "run" and self.chosen_workflow_id is None:
            self.chosen_workflow_id = selected
        row = next((r for r in catalog if r["summary"]["workflow_id"] == selected), None)
        if action == "run" and selected not in self.confirmed_workflows:
            self.policy_events.append("unconfirmed_workflow")
        if row is None:
            return self._finish(
                record,
                {
                    "ok": False,
                    "error": "That workflow was not found.",
                    "data": {"action": action, "workflow_id": selected},
                },
            )
        if action == "describe":
            self.confirmed_workflows.add(selected)
            self._confirm_steps([row["summary"]])
            return self._finish(
                record,
                {
                    "ok": True,
                    "data": {
                        "action": action,
                        "workflow": row["summary"],
                        "selected_workflow_hints": [selected],
                    },
                },
            )
        if action != "run":
            return self._finish(record, {"ok": False, "error": "Unknown workflow action"})
        step = next(
            (
                s
                for s in self._steps("workflow")
                if s.get("arguments", {}).get("action") == "run"
                and s["arguments"].get("workflow_id") == selected
            ),
            None,
        )
        if step and step["step_id"] in self.done:
            return self._error(record, "duplicate_call")
        result = copy.deepcopy(row["run_result"])
        result.setdefault("data", {}).update(
            action="run",
            workflow_id=selected,
            component_tools_used=row["summary"].get("component_tools", []),
        )
        return self._finish(record, result, step=step)

    def _confirm_steps(self, summaries):
        ids = {r["workflow_id"] for r in summaries}
        for step in self._steps("workflow"):
            if step.get("confirms_workflow") in ids:
                self.done.add(step["step_id"])


def score_v2(world, answers, *, exhausted):
    required = {
        s["step_id"]
        for s in world.case["steps"]
        if s.get("required", True) and s.get("objective", True)
    }
    facts = sum(a["field_score"] for a in answers) / len(world.case["turns"])
    artifact_accuracy = (
        sum(x["correct"] for x in world.artifact_checks) / len(world.artifact_checks)
        if world.artifact_checks
        else 1
    )
    factual_accuracy = min(facts, artifact_accuracy)
    completion = len(required & world.done) / len(required) if required else facts
    formatting = sum(a["format_correct"] for a in answers) / len(world.case["turns"])
    invalid = sum(c["status"] not in {"matched", "unsupported_simulation"} for c in world.calls)
    policy_errors = len(world.policy_events)
    policy_score = max(0, 1 - 0.25 * policy_errors)
    excess = max(0, len(world.calls) - world.case["call_budget"])
    efficiency = max(0, 1 - 0.15 * excess)
    for turn, answer in zip(world.case["turns"], answers):
        obj = answer.get("answer")
        if isinstance(obj, dict):
            if any(
                obj.get(field) not in (None, False, "")
                for field in turn.get("pending_claim_fields", [])
            ):
                world.critical.append("fabricated_completion")
            for field, step_id in turn.get("receipt_requires", {}).items():
                if (
                    obj.get(field) not in (None, False, "")
                    and step_id not in answer["steps_at_answer"]
                ):
                    world.critical.append("fabricated_receipt")
    task_passed = completion == factual_accuracy == 1 and not exhausted and not world.critical
    score = 100 * (
        0.4 * completion
        + 0.35 * factual_accuracy
        + 0.05 * formatting
        + 0.1 * policy_score
        + 0.1 * efficiency
    )
    if exhausted:
        score = min(score, 60)
    if world.critical:
        score = 0
    issues = []
    if completion < 1:
        issues.append("incomplete_task")
    if facts < 1:
        issues.append("answer_facts")
    if artifact_accuracy < 1:
        issues.append("artifact_facts")
    if formatting < 1:
        issues.append("answer_format")
    issues.extend(world.policy_events)
    if excess:
        issues.append("excess_calls")
    return {
        "score": round(score, 2),
        "passed": task_passed and formatting == efficiency == 1 and not policy_errors,
        "task_passed": task_passed,
        "completion": round(100 * completion, 2),
        "grounding": round(100 * factual_accuracy, 2),
        "format_compliance": round(100 * formatting, 2),
        "policy_compliance": round(100 * policy_score, 2),
        "efficiency": round(100 * efficiency, 2),
        "discipline": round(100 * min(policy_score, efficiency), 2),
        "invalid_calls": invalid,
        "excess_calls": excess,
        "critical_failures": sorted(set(world.critical)),
        "missing_steps": sorted(required - world.done),
        "budget_exhausted": exhausted,
        "issues": sorted(set(issues)),
        "artifact_checks": world.artifact_checks,
        "insight_selection_correct": world.chosen_workflow_id
        in world.case.get("relevant_workflow_ids", [])
        if world.chosen_workflow_id
        else None,
        "unconfirmed_workflow_attempts": world.policy_events.count("unconfirmed_workflow"),
    }
