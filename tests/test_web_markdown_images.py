"""Regression coverage for images embedded in Web chat Markdown."""

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
MAIN_CSS = ROOT / "jarvis-web" / "client" / "css" / "main.css"


def test_assistant_markdown_images_stay_within_the_message_bubble():
    css = MAIN_CSS.read_text(encoding="utf-8")
    rule = re.search(
        r"\.message\.assistant\s+\.message-bubble\s+img\s*\{(?P<body>[^}]*)\}",
        css,
    )

    assert rule is not None
    declarations = rule.group("body")
    assert "max-width: 100%;" in declarations
    assert "height: auto;" in declarations
    assert "display: block;" in declarations
