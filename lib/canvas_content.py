"""Shared content mutation safeguards for Canvas APIs and tools."""

SHRINK_GUARD_MIN_EXISTING_CHARS = 500
SHRINK_GUARD_MIN_REMOVED_CHARS = 500
SHRINK_GUARD_MAX_RETAINED_RATIO = 0.75


def is_suspicious_content_shrink(existing_content, new_content):
    """Flag likely accidental full-page replacement while allowing small edits."""
    existing_length = len(existing_content or '')
    new_length = len(new_content or '')
    if existing_length == 0 or new_length >= existing_length:
        return False
    if new_length == 0:
        return True
    removed = existing_length - new_length
    return (
        existing_length >= SHRINK_GUARD_MIN_EXISTING_CHARS
        and removed >= SHRINK_GUARD_MIN_REMOVED_CHARS
        and new_length / existing_length < SHRINK_GUARD_MAX_RETAINED_RATIO
    )


def append_content(existing_content, additional_content):
    """Join a new Markdown section without requiring the caller to resend the page."""
    existing = (existing_content or '').rstrip()
    additional = (additional_content or '').strip()
    if not existing:
        return additional
    if not additional:
        return existing
    return f"{existing}\n\n{additional}"
