"""Closed operation schemas; engine commands and host paths are never API inputs."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

APPS = ("photocraft", "pdfcraft", "lightcraft", "filmcraft", "effectcraft")
TESTED_VERSIONS = {"photocraft": "v0.6.0", "pdfcraft": "v0.5.0", "lightcraft": "v0.5.0",
                   "filmcraft": "v0.5.0", "effectcraft": "v0.7.0"}
ID_PATTERN = r"^[a-f0-9]{32}$"

class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Operation(ClosedModel):
    app: Literal["photocraft", "pdfcraft", "lightcraft", "filmcraft", "effectcraft"]
    action: Literal["invert", "grayscale", "rotate", "extract", "combine", "render", "develop", "assemble", "title"]
    inputs: list[str] = Field(default_factory=list, max_length=16)
    degrees: Literal[90, 180, 270] = 90
    pages: list[int] = Field(default_factory=lambda: [1], min_length=1, max_length=200)
    exposure: float = Field(default=0.5, ge=-5, le=5)
    width: int = Field(default=640, ge=16, le=1920)
    height: int = Field(default=360, ge=16, le=1080)
    fps: int = Field(default=24, ge=1, le=60)
    duration: float = Field(default=3, ge=0.1, le=120)
    text: str = Field(default="Title", min_length=1, max_length=1000)
    font_size: int = Field(default=36, ge=1, le=300)
    color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(default="#122238", pattern=r"^#[0-9a-fA-F]{6}$")
    gpu: bool = False
    output: Literal["png", "mp4"] = "png"

    @model_validator(mode="after")
    def validate_action(self):
        actions = {"photocraft": {"invert", "grayscale"}, "pdfcraft": {"rotate", "extract", "combine", "render"},
                   "lightcraft": {"develop"}, "filmcraft": {"assemble"}, "effectcraft": {"title"}}
        if self.action not in actions[self.app]:
            raise ValueError("Action is not supported by this app adapter")
        if any(not re.fullmatch(ID_PATTERN, value) for value in self.inputs):
            raise ValueError("Inputs must be artifact IDs")
        if self.app == "effectcraft":
            if self.inputs:
                raise ValueError("Title composition does not accept external projects or inputs")
        elif self.action in {"combine", "assemble"}:
            if not self.inputs:
                raise ValueError("At least one input is required")
        elif len(self.inputs) != 1:
            raise ValueError("Exactly one input is required")
        if any(page < 1 or page > 100000 for page in self.pages):
            raise ValueError("Pages must be positive one-based integers")
        # Each adapter's options are explicit; reject irrelevant settings rather
        # than reporting success for an ignored instruction.
        allowed = {"photocraft": set(), "pdfcraft": {"degrees", "pages"}, "lightcraft": {"exposure"},
                   "filmcraft": {"width", "height", "fps", "duration", "output"},
                   "effectcraft": {"width", "height", "fps", "duration", "text", "font_size", "color", "background", "gpu", "output"}}
        if self.model_fields_set - {"app", "action", "inputs"} - allowed[self.app]:
            raise ValueError("Option does not apply to the selected app")
        return self

class Submission(ClosedModel):
    request_id: str = Field(pattern=ID_PATTERN)
    project_id: str = Field(pattern=ID_PATTERN)
    revision: int = Field(ge=0)
    operation: Operation
