"""Prompt-contract coverage for the Jarvis Helper smoke benchmark."""

import hashlib
import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

from helper_task_prompts import (  # noqa: E402
    STATUS_REWRITE_INSTRUCTION,
    STASH_SUMMARY_SYSTEM_PROMPT,
    TEXT_SUMMARY_SYSTEM_PROMPT,
)


BENCHMARK_PATH = ROOT / "bin" / "benchmark-helper-llm"
LOADER = SourceFileLoader("benchmark_helper_llm", str(BENCHMARK_PATH))
SPEC = importlib.util.spec_from_loader(
    LOADER.name,
    LOADER,
)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_published_v3_prompt_contract_is_immutable():
    prompt_module = LIB_DIR / "helper_task_prompts.py"
    digest = hashlib.sha256(prompt_module.read_bytes()).hexdigest()

    assert digest == "587cccdbaa271cfa12a363341e00d39f3324a0df502eaa4e83cf9fe8aa8aa619", (
        "Published Jarvis Helper V3 was trained against the exact contents of "
        "lib/helper_task_prompts.py. Do not edit it in place; introduce a new "
        "versioned prompt contract and helper-model tag, then migrate production "
        "call sites and benchmarks together."
    )


def test_benchmark_uses_published_status_contract():
    assert benchmark.STATUS_REWRITE_INSTRUCTION == STATUS_REWRITE_INSTRUCTION
    assert benchmark.STATUS_REWRITE_INSTRUCTION.startswith("TASK=status_rewrite.")


def test_benchmark_uses_deployed_stash_summary_shape():
    messages = benchmark.build_summary_messages("stash_summary", "Atlas remains active.")

    assert messages[0] == {"role": "system", "content": STASH_SUMMARY_SYSTEM_PROMPT}
    assert messages[1]["content"].startswith(
        'Summarize this content from "benchmark.txt" in under 1200 characters, '
        "preserving all key facts:"
    )
    assert messages[1]["content"].endswith("Atlas remains active.")


def test_benchmark_uses_deployed_text_summary_shape():
    messages = benchmark.build_summary_messages("text_summary", "Atlas remains active.")

    assert messages[0] == {"role": "system", "content": TEXT_SUMMARY_SYSTEM_PROMPT}
    assert messages[1]["content"].startswith(
        "Summarize this text from benchmark text in no more than 160 words."
    )
    assert "\nTEXT:\nAtlas remains active.\n" in messages[1]["content"]


def test_benchmark_classification_matches_v3_eval_contract():
    assert benchmark.CLASSIFICATION_EVAL_SYSTEM_PROMPT.startswith(
        "TASK=content_classification."
    )
    assert "An instruction is a preference" in benchmark.CLASSIFICATION_EVAL_SYSTEM_PROMPT
