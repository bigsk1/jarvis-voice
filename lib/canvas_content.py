"""Shared content mutation safeguards for Canvas APIs and tools."""

import re

SHRINK_GUARD_MIN_EXISTING_CHARS = 500
SHRINK_GUARD_MIN_REMOVED_CHARS = 500
SHRINK_GUARD_MAX_RETAINED_RATIO = 0.75


_URL_WITH_ELLIPSIS = re.compile(
    r'(?:https?://|www\.)[^\s)\]}>"\']*\.\.\.[^\s)\]}>"\']*',
    re.IGNORECASE,
)


def find_truncated_urls(content):
    """Return URL tokens whose ellipsis is clearly an incomplete placeholder.

    A bounded ``left...right`` range is valid URL syntax used by services such
    as GitHub compare links. Ellipses at a URL boundary, immediately after a
    slash, or immediately before a slash remain invalid because they represent
    placeholders such as ``https://...`` and ``https://example.com/...``.
    """
    if not content:
        return []

    bad_urls = []
    seen = set()
    for match in _URL_WITH_ELLIPSIS.finditer(str(content)):
        url = match.group(0)
        invalid = False
        marker_start = 0
        while True:
            marker_start = url.find('...', marker_start)
            if marker_start < 0:
                break
            before = url[:marker_start]
            after = url[marker_start + 3:]
            meaningful_after = after.rstrip('.,;:!?')
            if (
                not before
                or not meaningful_after
                or before.endswith(('://', '/'))
                or meaningful_after.startswith(('/', '?', '#'))
            ):
                invalid = True
                break
            marker_start += 3

        if invalid and url not in seen:
            seen.add(url)
            bad_urls.append(url)

    return bad_urls


def canvas_url_validation_error(content):
    """Return the shared Canvas URL validation error, or ``None`` when valid."""
    truncated_urls = find_truncated_urls(content)
    if not truncated_urls:
        return None
    return {
        'error': f"Canvas content contains truncated URLs: {truncated_urls[:3]}",
        'error_code': 'truncated_content_url',
        'truncated_urls': truncated_urls[:3],
        'hint': (
            'Use complete URLs. Bounded range syntax such as ref...ref is allowed.'
        ),
    }


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
