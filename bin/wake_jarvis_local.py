#!/usr/bin/env python3
"""Jarvis Voice Assistant - Local/Offline Wake Word Detection"""
import os, time, sys, subprocess, threading
import numpy as np
import sounddevice as sd
from openwakeword.model import Model

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value, get_int, get_float

import warnings
warnings.filterwarnings(
    "ignore",
    message=".*CUDAExecutionProvider.*",
    module="onnxruntime.capi.onnxruntime_inference_collection",
)

# Load configuration
print("🔧 Loading local configuration...")
load_config('local')

# ---- CONFIG (from env) ----
WAKE_MODEL = get_config_value("WAKE_MODEL", "hey_jarvis")
SAMPLE_RATE = get_int("SAMPLE_RATE", 16000)
BLOCK_SIZE = get_int("BLOCK_SIZE", 1024)
CHANNELS = get_int("CHANNELS", 1)

ARM_GRACE_SEC = get_float("ARM_GRACE_SEC", 1.2)
last_arm_ts = 0.0

TRIGGER_THRESHOLD = get_float("TRIGGER_THRESHOLD", 0.2)
HIT_FRAMES_REQUIRED = get_int("HIT_FRAMES_REQUIRED", 4)
MIN_RMS = get_float("MIN_RMS", 2e-4)
COOLDOWN_AFTER_QA = get_float("COOLDOWN_AFTER_QA", 2.8)
DEVICE_NAME_HINT = get_config_value("DEVICE_NAME_HINT", "TONOR")
VAD_THRESHOLD = get_float("VAD_THRESHOLD", 0.40)

# WAKE_GREETINGS loaded in handle_trigger() for random selection

# Script paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SAY = os.path.join(PROJECT_ROOT, "bin", "say-local.sh")
# Use orchestrator for intelligent tool calling
ASK = os.path.join(PROJECT_ROOT, "bin", "question-orchestrator-local.sh")
# -----------------

print("🔊 Loading openWakeWord model…")
oww = Model(vad_threshold=VAD_THRESHOLD)
print("Available wakewords:", list(oww.models.keys()))

# Display available tools
print("\n🛠️  Available Tools:")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))
from tool_schema import ToolRegistry
mcp_config = os.path.join(PROJECT_ROOT, "config", "mcp-servers.json")
registry = ToolRegistry(os.path.join(PROJECT_ROOT, "skills"), mcp_config)
tools = sorted(registry.list_tools())
for i, tool_name in enumerate(tools, 1):
    tool_schema = registry.get_tool(tool_name)
    # Show tool with icon based on permissions
    if tool_schema.permissions.get("dangerous"):
        icon = "🚨"
    elif tool_schema.permissions.get("network"):
        icon = "🌐"
    elif tool_schema.permissions.get("bash"):
        icon = "⚡"
    else:
        icon = "✅"
    print(f"  {i:2d}. {icon} {tool_name:20s} - {tool_schema.description[:60]}...")
print()


def pick_input_device():
    try:
        devs = sd.query_devices()
    except Exception as e:
        print(f"Could not query devices: {e}", file=sys.stderr)
        return None
    for idx, d in enumerate(devs):
        name = d.get("name","")
        if DEVICE_NAME_HINT.lower() in name.lower() and d.get("max_input_channels",0) > 0:
            print(f"🎤 Using input device {idx}: {name}")
            return idx
    default = sd.default.device[0]
    if default is not None:
        print(f"🎤 Using default input device index: {default}")
        return default
    for idx, d in enumerate(devs):
        if d.get("max_input_channels",0) > 0:
            print(f"🎤 Using first input-capable device {idx}: {d.get('name','')}")
            return idx
    print("❌ No input device found", file=sys.stderr)
    return None

in_dev = pick_input_device()
if in_dev is None:
    sys.exit(1)

# ---- state / sync ----
armed = True
consec_hits = 0
trigger_evt = threading.Event()
stream = None
lock = threading.Lock()

def build_stream():
    return sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=BLOCK_SIZE,
        callback=audio_callback,
        device=in_dev,
    )

def audio_callback(indata, frames, time_info, status):
    global armed, consec_hits, last_arm_ts
    if status:
        pass
    if not armed:
        return

    # Settle-time guard
    if (time.time() - last_arm_ts) < ARM_GRACE_SEC:
        return

    mono_f32 = indata[:, 0].astype(np.float32, copy=False)
    np.clip(mono_f32, -1.0, 1.0, out=mono_f32)

    # Noise gate
    rms = np.sqrt(np.mean(mono_f32**2))
    if rms < MIN_RMS:
        if consec_hits > 0:
            consec_hits -= 1
        return

    # Convert for openWakeWord
    audio_i16 = (mono_f32 * 32767.0).clip(-32768, 32767).astype(np.int16)
    scores = oww.predict(audio_i16)
    prob = float(scores.get(WAKE_MODEL, 0.0))

    if prob >= TRIGGER_THRESHOLD:
        consec_hits += 1
        if consec_hits >= HIT_FRAMES_REQUIRED:
            armed = False
            consec_hits = 0
            trigger_evt.set()
    else:
        if consec_hits > 0:
            consec_hits -= 1

def stop_stream():
    global stream
    if stream is not None:
        try: stream.stop()
        except Exception: pass
        try: stream.close()
        except Exception: pass
        stream = None
        time.sleep(0.15)

def start_stream():
    global stream
    stream = build_stream()
    stream.start()

def handle_trigger():
    print("🟢🟢🟢  Wake word detected → Q&A… 🟢🟢🟢")
    stop_stream()

    # Quick local acknowledgement with random greeting
    try:
        # Get random greeting from WAKE_GREETINGS (pipe-separated)
        greetings = get_config_value("WAKE_GREETINGS", "Hello").split('|')
        import random
        greeting = random.choice(greetings).strip()
        subprocess.run([SAY, greeting], check=False)
    except Exception as e:
        print(f"say-local.sh failed: {e}", file=sys.stderr)

    # Local pipeline
    try:
        subprocess.run([ASK], check=False)
    except Exception as e:
        print(f"question-mic-local.sh failed: {e}", file=sys.stderr)

    time.sleep(COOLDOWN_AFTER_QA)
    with lock:
        global armed, last_arm_ts
        armed = True
        last_arm_ts = time.time()
        start_stream()
    print("🟡 Re-armed, listening again 🎙️  Say --> Hey Jarvis")

def main():
    print(f"🎙️  Listening for '{WAKE_MODEL.replace('_',' ')}'... Ctrl+C to quit.")
    start_stream()
    try:
        while True:
            if trigger_evt.wait(timeout=0.2):
                trigger_evt.clear()
                handle_trigger()
    except KeyboardInterrupt:
        print("\n👋 Bye.")
    finally:
        stop_stream()

if __name__ == "__main__":
    main()

