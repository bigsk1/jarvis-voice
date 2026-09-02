"""Operator-facing setup failures shared by the renderers.

Kept free of numpy/Pillow imports so the launcher can catch these without
loading a renderer's dependencies.
"""

from __future__ import annotations


class DisplaySetupError(RuntimeError):
    """The display cannot start; the message is safe to print to the operator."""
