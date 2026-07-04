#!/usr/bin/env bash
set -e

# Activate venv and go to project
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$HOME/jarvis-venv/bin/activate"
cd "$REPO_ROOT"

python3 << 'EOF'
import os
import sys
import time
sys.path.insert(0, 'lib')
from config_loader import load_config
load_config('cloud')
os.environ['STATUS_LOGGING_ENABLED'] = 'false'

# Capture spoken messages
spoken_messages = []

def run_test(test_name, settings, categories_to_test):
    """Run a test with specific settings."""
    global spoken_messages
    spoken_messages = []
    
    # Apply settings
    for key, val in settings.items():
        os.environ[key] = str(val)
    
    # Reimport to get fresh instances with new settings
    import importlib
    import status_llm
    import status_updater
    importlib.reload(status_llm)
    importlib.reload(status_updater)
    
    from status_updater import StatusUpdater
    
    # Patch speak
    def patched_speak(self, msg, blocking=False):
        spoken_messages.append(msg)
    StatusUpdater._speak = patched_speak
    
    updater = StatusUpdater(mode='cloud')
    updater.reset()
    updater.interval = 0  # No rate limiting
    
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"Settings: {settings}")
    print(f"Updater enabled: {updater.enabled}")
    if hasattr(updater, 'summarizer'):
        print(f"LLM enabled: {updater.summarizer.enabled}")
        if updater.summarizer.enabled:
            print(f"LLM personality: {updater.summarizer.phrase_mode}")
    print(f"{'='*60}")
    
    for cat, tool in categories_to_test:
        updater.update(category=cat, tool_name=tool)
        # Status generation is intentionally asynchronous and deadline-bound.
        time.sleep(max(updater.llm_deadline_ms, updater.debounce_ms) / 1000 + 0.1)
    
    print("Messages spoken:")
    for i, msg in enumerate(spoken_messages, 1):
        print(f"  {i}. {msg}")
    
    return spoken_messages

# Test categories matching the doc trigger matrix
TRIGGERS = [
    ('task_start', 'get_time'),           # Task Start
    ('searching', 'mcp_brave_search_brave_web_search'),  # Web Search
    ('building', 'opencode'),             # OpenCode Start
    ('progress', 'opencode'),             # OpenCode Progress
    ('multi_turn', 'api_call'),           # Multi-Turn 3+
    ('error_retry', None),                # Tool Retry
    ('near_complete', None),              # Near Complete
    ('long_wait', None),                  # Long Wait
]

print("\n" + "="*70)
print("COMPREHENSIVE STATUS UPDATE TESTS")
print("="*70)

# ============================================================
# TEST 1: LLM Enabled - Normal mode (humor + sass + encouragement)
# ============================================================
run_test(
    "LLM + Normal Mode (humor/sass/encouragement)",
    {
        'STATUS_UPDATES_ENABLED': 'true',
        'STATUS_LLM_ENABLED': 'true',
        'STATUS_PHRASE_MODE': 'normal',
        'STATUS_HUMOR_ENABLED': 'true',
        'STATUS_SASS_LEVEL': '1',
        'STATUS_ENCOURAGEMENT_ENABLED': 'true',
    },
    TRIGGERS
)

# ============================================================
# TEST 2: LLM Enabled - Unhinged mode
# ============================================================
run_test(
    "LLM + UNHINGED Mode 🔥",
    {
        'STATUS_UPDATES_ENABLED': 'true',
        'STATUS_LLM_ENABLED': 'true',
        'STATUS_PHRASE_MODE': 'unhinged',
    },
    TRIGGERS[:4]  # Just test a few for unhinged
)

# ============================================================
# TEST 3: LLM Enabled - Professional mode (no humor/sass)
# ============================================================
run_test(
    "LLM + Professional Mode",
    {
        'STATUS_UPDATES_ENABLED': 'true',
        'STATUS_LLM_ENABLED': 'true',
        'STATUS_PHRASE_MODE': 'normal',
        'STATUS_HUMOR_ENABLED': 'false',
        'STATUS_SASS_LEVEL': '0',
        'STATUS_ENCOURAGEMENT_ENABLED': 'false',
    },
    TRIGGERS[:4]
)

# ============================================================
# TEST 4: Static Phrases - Normal mode (LLM disabled)
# ============================================================
run_test(
    "Static Phrases - Normal Mode (LLM disabled)",
    {
        'STATUS_UPDATES_ENABLED': 'true',
        'STATUS_LLM_ENABLED': 'false',
        'STATUS_PHRASE_MODE': 'normal',
    },
    TRIGGERS
)

# ============================================================
# TEST 5: Static Phrases - Unhinged mode (LLM disabled)
# ============================================================
run_test(
    "Static Phrases - UNHINGED Mode (LLM disabled)",
    {
        'STATUS_UPDATES_ENABLED': 'true',
        'STATUS_LLM_ENABLED': 'false',
        'STATUS_PHRASE_MODE': 'unhinged',
    },
    TRIGGERS[:4]
)

# ============================================================
# TEST 6: Status Updates DISABLED (original behavior)
# ============================================================
results = run_test(
    "Status Updates DISABLED (silent mode)",
    {
        'STATUS_UPDATES_ENABLED': 'false',
    },
    TRIGGERS
)
if len(results) == 0:
    print("  ✅ No messages spoken (correct!)")

print("\n" + "="*70)
print("ALL TESTS COMPLETE")
print("="*70)
EOF
