"""Validate one-request image settings before Web stages a provider call."""

from config_loader import get_config_value
from model_catalog import get_media_model_env_key, get_media_model_metadata, resolve_media_model


def validate_gif_analysis_frame(settings: dict, images: list[dict]) -> int | None:
    """A frame number belongs to one authoritative uploaded GIF, never a batch."""
    gif_frame = settings.get("gif_frame")
    if gif_frame is None:
        return None
    if len(images) != 1 or images[0].get("mime_type") != "image/gif":
        raise ValueError("gif_frame requires exactly one uploaded GIF source")
    if type(gif_frame) is not int or gif_frame < 0:
        raise ValueError("gif_frame must be a non-negative integer")
    frame_count = images[0].get("source_frame_count")
    if type(frame_count) is not int or frame_count < 1:
        raise ValueError("Could not verify the source GIF frame count")
    if gif_frame >= frame_count:
        raise ValueError(f"gif_frame must be less than the source's {frame_count} frames")
    return gif_frame


def validate_image_generation_settings(
    settings: dict, *, source_gif: bool = False, source_frame_count: int | None = None,
) -> None:
    """Reject unsupported formats/animation controls; the tool also validates."""
    provider = settings.get("provider") or get_config_value("IMAGE_TOOL_PROVIDER", "gemini")
    model_key = get_media_model_env_key("image", provider)
    configured_model = get_config_value(model_key, "") if model_key else ""
    model = resolve_media_model("image", provider, settings.get("model") or configured_model)
    metadata = get_media_model_metadata("image", provider, model) or {}
    output_format = settings.get("output_format") or "png"
    formats = metadata.get("output_formats") or ["png", "jpeg", "webp"]
    if settings.get("output_format") is not None and (
        provider != "openai" or output_format not in formats
    ):
        raise ValueError(f"{provider}/{model} does not support output_format={output_format}")
    if source_gif and (provider != "openai" or "gif" not in formats):
        raise ValueError("GIF reference generation requires an OpenAI GIF-capable model")
    complexity = settings.get("complexity")
    if complexity is not None and (
        provider != "openai" or complexity not in metadata.get("complexities", [])
    ):
        raise ValueError(f"{provider}/{model} does not support complexity={complexity}")
    for key, minimum, maximum in (
        ("frame_count", 2, 16), ("frame_duration_ms", 20, 655350),
    ):
        value = settings.get(key)
        if value is None:
            continue
        if provider != "openai" or output_format != "gif":
            raise ValueError(f"{key} requires OpenAI GIF output")
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be an integer from {minimum} to {maximum}")
    reference_frame = settings.get("reference_frame")
    if reference_frame is not None and not source_gif:
        raise ValueError("reference_frame requires a GIF source image")
    if reference_frame is not None and (
        type(reference_frame) is not int or reference_frame < 0
    ):
        raise ValueError("reference_frame must be a non-negative integer")
    if (
        source_gif and type(source_frame_count) is int and source_frame_count > 0
        and (reference_frame or 0) >= source_frame_count
    ):
        raise ValueError(f"reference_frame must be less than the source's {source_frame_count} frames")
    if output_format == "gif" and settings.get("transparent"):
        raise ValueError("Transparent backgrounds require PNG or WebP output")
