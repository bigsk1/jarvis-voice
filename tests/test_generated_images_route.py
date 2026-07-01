"""Contract tests for the generated-images FastAPI route."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from api.routes import generated_images


def test_generate_route_passes_shared_gemini_options_to_tool():
    request = generated_images.GenerateRequest(
        prompt="Change the sky to sunset",
        reference_image="stash://space/file",
        aspect_ratio="4:5",
        image_size="4K",
        style="photorealistic",
        negative_prompt="watermark",
        use_grounding=True,
        provider="gemini",
        mode="local",
    )
    completed = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"ok": True, "speech": "done", "data": {"provider": "gemini"}}),
        stderr="",
    )

    with patch.object(generated_images.subprocess, "run", return_value=completed) as run:
        response = asyncio.run(generated_images.generate_image(request))

    command = run.call_args.args[0]
    payload = json.loads(command[2])
    assert command[0] == "python3"
    assert payload == {
        "prompt": "Change the sky to sunset",
        "aspect_ratio": "4:5",
        "image_size": "4K",
        "save": True,
        "use_grounding": True,
        "reference_image": "stash://space/file",
        "style": "photorealistic",
        "negative_prompt": "watermark",
        "provider": "gemini",
    }
    assert run.call_args.kwargs["env"]["JARVIS_MODE"] == "local"
    assert response.ok is True
    assert response.data == {"provider": "gemini"}
