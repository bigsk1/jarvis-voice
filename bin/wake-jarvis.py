#!/usr/bin/env python3
"""Jarvis Voice Assistant - Cloud/OpenAI Wake Word Detection"""
import os, time, sys, subprocess, threading
import numpy as np
import sounddevice as sd
from openwakeword.model import Model

# Resolve symlinks to get the REAL script location (critical for symlinks like ./jarvis)
SCRIPT_PATH = os.path.realpath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)

# Add lib to path
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'lib'))
from config_loader import load_config, get_config_value, get_int, get_float
from head_events import emit as emit_head_event
from model_catalog import get_provider_fallback_model
from tts_normalizer import normalize_tts_text

import warnings
warnings.filterwarnings(
    "ignore",
    message=".*CUDAExecutionProvider.*",
    module="onnxruntime.capi.onnxruntime_inference_collection",
)

# Read Jarvis version
from pathlib import Path as _P
try:
    _jarvis_version = (_P(SCRIPT_DIR).parent / 'VERSION').read_text().strip()
except Exception:
    _jarvis_version = '0.0.0'

# Load configuration
print("🔧 Loading cloud configuration...")
load_config('cloud')

# Display mode and model info
provider = get_config_value('LLM_PROVIDER', 'anthropic')
if provider == 'xai':
    model = get_config_value('XAI_MODEL', get_provider_fallback_model('xai'))
elif provider == 'anthropic':
    model = get_config_value('ANTHROPIC_MODEL', get_provider_fallback_model('anthropic'))
elif provider == 'openai':
    model = get_config_value('OPENAI_MODEL', get_provider_fallback_model('openai'))
else:
    model = 'unknown'
print(f"🤖 Jarvis v{_jarvis_version}")
print(f"📡 Mode: cloud")
print(f"🤖 LLM Provider: {provider}")
print(f"🧠 Model: {model}")
print()

# ---- CONFIG (from env) ----
WAKE_MODEL = get_config_value("WAKE_MODEL", "hey_jarvis")
SAMPLE_RATE = get_int("SAMPLE_RATE", 16000)
BLOCK_SIZE = get_int("BLOCK_SIZE", 1024)
CHANNELS = get_int("CHANNELS", 1)

ARM_GRACE_SEC = get_float("ARM_GRACE_SEC", 1.0)
last_arm_ts = 0.0

TRIGGER_THRESHOLD = get_float("TRIGGER_THRESHOLD", 0.2)
HIT_FRAMES_REQUIRED = get_int("HIT_FRAMES_REQUIRED", 4)
MIN_RMS = get_float("MIN_RMS", 2e-4)
COOLDOWN_AFTER_QA = get_float("COOLDOWN_AFTER_QA", 2.8)
HEAD_QA_KEEPALIVE_INTERVAL = 30.0
DEVICE_NAME_HINT = get_config_value("DEVICE_NAME_HINT", "TONOR")
VAD_THRESHOLD = get_float("VAD_THRESHOLD", 0.40)
PREAMP = get_float("PREAMP", 1.8)

# WAKE_GREETINGS loaded in handle_trigger() for random selection

# Script paths (using resolved symlink path)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
SAY = os.path.join(PROJECT_ROOT, "bin", "say.sh")
# Use orchestrator for intelligent tool calling
ASK = os.path.join(PROJECT_ROOT, "bin", "question-orchestrator.sh")
# -----------------

print("🔊 Loading openWakeWord model…")
oww = Model(vad_threshold=VAD_THRESHOLD)
# print("Available wakewords:", list(oww.models.keys()))

# Display available tools (excluding blocked tools)
print("\n🛠️  Available Tools:")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))
from tool_schema import ToolRegistry
mcp_config = os.path.join(PROJECT_ROOT, "config", "mcp-servers.json")
registry = ToolRegistry(os.path.join(PROJECT_ROOT, "skills"), mcp_config)

# Get blocked tools list from config
blocked_tools_str = get_config_value("BLOCKED_TOOLS", "")
blocked_tools = set(t.strip() for t in blocked_tools_str.split(",") if t.strip())

tools = sorted(registry.list_tools())
displayed = 0
for tool_name in tools:
    # Skip blocked tools
    if tool_name in blocked_tools:
        continue
    displayed += 1
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
    print(f"  {displayed:2d}. {icon} {tool_name:20s} - {tool_schema.description[:100]}...")

if blocked_tools:
    print(f"\n  (🚫 {len(blocked_tools)} blocked tool(s) hidden)")
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

def audio_callback(indata, _frames, _time_info, status):
    global armed, consec_hits
    if status:
        pass
    if not armed:
        return
    
    # Settle-time guard
    if (time.time() - last_arm_ts) < ARM_GRACE_SEC:
        return

    mono_f32 = indata[:, 0].astype(np.float32, copy=False)
    mono_f32 *= PREAMP
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
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        stream = None
        time.sleep(0.5)  # Let ALSA release before sox opens the mic

def start_stream():
    global stream
    stream = build_stream()
    stream.start()

def run_question_with_head_keepalive(command):
    """Run one Q&A process while renewing the optional head's listen lease."""
    stop_keepalive = threading.Event()

    def keep_head_listening():
        while not stop_keepalive.wait(HEAD_QA_KEEPALIVE_INTERVAL):
            emit_head_event("listen")

    keepalive = threading.Thread(
        target=keep_head_listening,
        name="jarvis-head-qa-keepalive",
        daemon=True,
    )
    keepalive.start()
    try:
        return subprocess.run(command, check=False)
    finally:
        stop_keepalive.set()
        keepalive.join(timeout=1.0)

def handle_trigger():
    print("🟢🟢🟢  Wake word detected → Q&A… 🟢🟢🟢", flush=True)
    emit_head_event("listen")
    stop_stream()

    # Quick acknowledgment with random greeting
    try:
        # Get random greeting from WAKE_GREETINGS (pipe-separated)
        greetings = get_config_value("WAKE_GREETINGS", "Hello").split('|')
        import random
        greeting = normalize_tts_text(random.choice(greetings).strip())
        if greeting:
            subprocess.run([SAY, greeting], check=False)
    except Exception as e:
        print(f"say.sh failed: {e}", file=sys.stderr, flush=True)

    # Run Q&A flow
    should_exit = False
    try:
        print("🎤 Starting question capture…", flush=True)
        result = run_question_with_head_keepalive(["bash", ASK])
        should_exit = result.returncode == 20
        if result.returncode not in (0, 20):
            print(
                f"⚠️  Q&A failed (exit {result.returncode}). "
                f"Check mic access or run: bash {ASK} \"test question\"",
                file=sys.stderr,
                flush=True,
            )
    except Exception as e:
        print(f"question-orchestrator.sh failed: {e}", file=sys.stderr, flush=True)

    if should_exit:
        emit_head_event("sleep")
        print("🛑 Wake loop stopped by voice command.")
        return False

    # Cooldown + re-arm
    time.sleep(COOLDOWN_AFTER_QA)
    with lock:
        global armed, last_arm_ts
        armed = True
        last_arm_ts = time.time()
        start_stream()
    emit_head_event("sleep")
    print("🟡 Re-armed, listening again 🎙️  Say --> Hey Jarvis")
    return True

def main():
    print(f"🎙️  Listening for '{WAKE_MODEL.replace('_',' ')}'... Ctrl+C to quit.")
    try:
        start_stream()
        while True:
            if trigger_evt.wait(timeout=0.2):
                trigger_evt.clear()
                if handle_trigger() is False:
                    break
    except KeyboardInterrupt:
        print("\n👋 Bye.")
    finally:
        try:
            stop_stream()
        finally:
            emit_head_event("sleep")

if __name__ == "__main__":
    main()
