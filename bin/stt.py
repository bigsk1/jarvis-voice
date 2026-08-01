#!/usr/bin/env python3
"""Mode-aware Jarvis speech-to-text command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


JARVIS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(JARVIS_ROOT / "lib"))

from config_loader import get_config_value, load_config  # noqa: E402
from stt_client import (  # noqa: E402
    STTProviderError,
    default_model_for_provider,
    normalize_stt_provider,
    parse_stt_timeout,
    run_with_stt_fallback,
    transcribe_openai_compatible,
)


def _transcribe_faster_whisper(audio_path: str, model_name: str) -> str:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise ValueError("faster-whisper is not installed") from exc

    device = get_config_value("STT_DEVICE", "cpu")
    compute_type = get_config_value("STT_COMPUTE_TYPE", "int8")
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as exc:
        raise STTProviderError(
            f"faster-whisper model initialization failed: {exc}", retryable=False
        ) from exc

    try:
        segments, _ = model.transcribe(
            audio_path,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return "".join(segment.text for segment in segments).strip()
    except Exception as exc:
        raise STTProviderError(
            f"faster-whisper failed: {exc}", retryable=False
        ) from exc


def _transcribe_provider(provider: str, audio_path: str, model_name: str) -> str:
    provider = normalize_stt_provider(provider)
    timeout = parse_stt_timeout(get_config_value("STT_TIMEOUT_SECONDS", "30"))

    if provider == "faster-whisper":
        return _transcribe_faster_whisper(audio_path, model_name)

    if provider == "openai":
        api_key = get_config_value("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        return transcribe_openai_compatible(
            audio_path,
            base_url="https://api.openai.com/v1",
            api_key=api_key,
            model=model_name,
            timeout=timeout,
        )

    base_url = get_config_value("STT_BASE_URL", "")
    api_key = get_config_value("STT_API_KEY", "")
    return transcribe_openai_compatible(
        audio_path,
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        timeout=timeout,
    )


def _fallback_notice(
    primary: str, fallback: str, error: STTProviderError
) -> None:
    print(
        f"[STT] {primary} temporarily unavailable; falling back to {fallback}: {error}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe an audio file")
    parser.add_argument("audio_path")
    parser.add_argument("--mode", choices=("cloud", "local"), required=True)
    parser.add_argument("--provider", help="Override STT_PROVIDER and disable fallback")
    parser.add_argument("--model", help="Override STT_MODEL")
    args = parser.parse_args(argv)

    load_config(args.mode)

    explicit_provider = args.provider is not None
    default_provider = "openai" if args.mode == "cloud" else "faster-whisper"
    provider = normalize_stt_provider(
        args.provider or get_config_value("STT_PROVIDER", default_provider)
    )
    model_name = (
        args.model
        or get_config_value("STT_MODEL", "")
        or default_model_for_provider(provider)
    )

    fallback_provider = ""
    if not explicit_provider:
        fallback_provider = get_config_value("STT_FALLBACK_PROVIDER", "").strip()

    fallback_model = get_config_value("STT_FALLBACK_MODEL", "").strip()

    def transcribe(selected_provider: str) -> str:
        selected_model = model_name
        if selected_provider != provider:
            selected_model = fallback_model or default_model_for_provider(selected_provider)
        return _transcribe_provider(selected_provider, args.audio_path, selected_model)

    transcript = run_with_stt_fallback(
        provider,
        fallback_provider,
        transcribe,
        on_fallback=_fallback_notice,
    )
    print(transcript)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"STT failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except STTProviderError as exc:
        print(f"STT failed: {exc}", file=sys.stderr)
        raise SystemExit(3 if exc.retryable else 2)
