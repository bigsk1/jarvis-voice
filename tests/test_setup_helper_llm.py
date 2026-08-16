import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "setup-helper-llm"


def test_setup_helper_llm_pulls_model_from_selected_daemon(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ollama = fake_bin / "ollama"
    fake_ollama.write_text(
        "#!/bin/sh\n"
        "printf '%s|%s\\n' \"${OLLAMA_HOST:-}\" \"$*\" >> \"$FAKE_OLLAMA_LOG\"\n"
    )
    fake_ollama.chmod(0o755)
    call_log = tmp_path / "ollama-calls.log"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_OLLAMA_LOG"] = str(call_log)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--mode",
            "cloud",
            "--model",
            "test/jarvis-helper:v1",
            "--base-url",
            "http://helper.test:11434",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert call_log.read_text().splitlines() == [
        "http://helper.test:11434|pull test/jarvis-helper:v1",
        "http://helper.test:11434|show test/jarvis-helper:v1",
    ]
    assert "Ready: test/jarvis-helper:v1 on http://helper.test:11434" in result.stdout


def test_setup_helper_llm_help_has_no_legacy_download_path():
    result = subprocess.run(
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "ollama" in result.stdout.lower()
    assert "Hugging Face" not in result.stdout
    assert "--force-download" not in result.stdout
