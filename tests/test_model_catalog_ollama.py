#!/usr/bin/env python3
"""Regression tests for model catalog behavior with non-catalog Ollama models."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from model_catalog import get_model_context_label, get_model_metadata  # noqa: E402


def test_ollama_metadata_returns_none_without_warning_path():
    assert get_model_metadata("ollama", "qwen3:latest") is None
    assert get_model_context_label("ollama", "qwen3:latest") is None
