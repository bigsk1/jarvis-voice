"""Source ranges and editable, timed graphic overlays for FilmCraft."""
from typing import Literal

from pydantic import Field, model_validator

from .image_models import EditModel


class ClipRange(EditModel):
    source: int = Field(default=0, ge=0, le=15)
    start: float = Field(default=0, ge=0, le=86400)
    end: float = Field(gt=0, le=86400)

    @model_validator(mode='after')
    def range(self):
        if self.end <= self.start:
            raise ValueError('Clip end must be after its source start')
        return self


class VideoText(EditModel):
    action: Literal['title', 'caption', 'update_text']
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    clip: int | None = Field(default=None, ge=1)
    layer: int = Field(default=0, ge=0, le=15)
    start: float = Field(default=0, ge=0, le=120)
    duration: float | None = Field(default=None, gt=0, le=120)
    placement: Literal['top', 'center', 'bottom'] | None = None
    font_size: float | None = Field(default=None, ge=8, le=300)
    color: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')

    @model_validator(mode='after')
    def target(self):
        if (self.text is not None and not self.text.strip()) or (self.action != 'update_text' and self.text is None):
            raise ValueError('Overlay must contain visible text')
        if (self.action == 'update_text') != (self.clip is not None):
            raise ValueError('Only update_text selects an existing graphic clip ID')
        # Revision timing must be checked against the selected native clip.
        # Both schema defaults and echoes of its actual timing are harmless.
        return self
