"""Bounded image edits; callers never supply native commands or host paths."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EditModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class TextEdit(EditModel):
    action: Literal['text', 'update_text']
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    layer: int | str | None = None
    name: str = Field(default='Caption', min_length=1, max_length=80)
    placement: Literal['top', 'center', 'bottom'] | None = None
    align: Literal['left', 'center', 'right'] | None = None
    font_size: float | None = Field(default=None, ge=8, le=300)
    color: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')
    outline_color: str = Field(default='#000000', pattern=r'^#[0-9a-fA-F]{6}$')
    outline_width: float = Field(default=2, ge=0, le=12)

    @model_validator(mode='after')
    def target(self):
        if self.text is not None and not self.text.strip():
            raise ValueError('Caption must contain visible text')
        if self.action == 'text' and (self.text is None or self.layer is not None):
            raise ValueError('New text requires text and must not select an existing layer')
        if self.action == 'update_text' and self.layer is None:
            raise ValueError('update_text requires the existing layer ID or exact name')
        if isinstance(self.layer, str) and not 1 <= len(self.layer) <= 80:
            raise ValueError('Layer name must contain 1..80 characters')
        return self


class CropEdit(EditModel):
    action: Literal['crop']
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=8192)


class ResizeEdit(EditModel):
    action: Literal['resize']
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=8192)


class RotateEdit(EditModel):
    action: Literal['rotate']
    degrees: Literal[90, 180, 270]


class PlaceEdit(EditModel):
    action: Literal['overlay']
    source: int = Field(ge=1, le=15, description='Zero-based index into sources; 0 is the base image/project')
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)


ImageEdit = Annotated[TextEdit | CropEdit | ResizeEdit | RotateEdit | PlaceEdit, Field(discriminator='action')]
