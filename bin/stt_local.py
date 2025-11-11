#!/usr/bin/env python3
"""Jarvis Voice Assistant - Local STT (faster-whisper)"""
import sys
import os
from faster_whisper import WhisperModel

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value

# Load configuration
load_config('local')

# Args: audio_path
if len(sys.argv) < 2:
    print("Usage: stt_local.py <audio.wav>", file=sys.stderr)
    sys.exit(1)

audio_path = sys.argv[1]

# Get config
STT_MODEL = get_config_value("STT_MODEL", "small.en")
STT_DEVICE = get_config_value("STT_DEVICE", "cpu")
STT_COMPUTE_TYPE = get_config_value("STT_COMPUTE_TYPE", "int8")

# Load model
model = WhisperModel(STT_MODEL, device=STT_DEVICE, compute_type=STT_COMPUTE_TYPE)

segments, info = model.transcribe(
    audio_path,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=300)
)

text = "".join(s.text for s in segments).strip()
print(text)

