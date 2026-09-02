"""Contracts for the shared SoX question-recording chain."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
QUESTION_SCRIPTS = (
    "question-orchestrator.sh",
    "question-orchestrator-local.sh",
    "question-mic.sh",
    "question-mic-local.sh",
)


def test_all_question_recorders_use_filtered_split_thresholds():
    for script_name in QUESTION_SCRIPTS:
        content = (ROOT / "bin" / script_name).read_text(encoding="utf-8")
        assert 'START_THRESH="${START_THRESH:-${THRESH:-3%}}"' in content
        assert 'STOP_THRESH="${STOP_THRESH:-${THRESH:-5%}}"' in content
        assert 'MIC_HIGHPASS_HZ="${MIC_HIGHPASS_HZ:-300}"' in content
        assert 'highpass "$MIC_HIGHPASS_HZ"' in content
        assert 'silence 1 "$PRE_SIL" "$START_THRESH" 1 "$POST_SIL" "$STOP_THRESH"' in content


def test_question_recording_defaults_are_reproducible_in_both_mode_templates():
    for mode in ("cloud", "local"):
        template = (ROOT / "config" / f"{mode}.env.example").read_text(encoding="utf-8")
        assert 'START_THRESH="3%"' in template
        assert 'STOP_THRESH="5%"' in template
        assert 'MIC_HIGHPASS_HZ="300"' in template
        assert 'POST_SIL="2.0"' in template
