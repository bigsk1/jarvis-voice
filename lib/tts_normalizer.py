#!/usr/bin/env python3
"""Shared text normalization for spoken TTS output."""

from __future__ import annotations

import re
from datetime import datetime

ALLOWED_TTS_PROFILES = {
    "weather_watch",
    "camera_alert",
    "price_quote",
    "timestamped",
}

MONTH_ABBREVIATIONS = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "sept": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}

DAY_ABBREVIATIONS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "tues": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "thur": "Thursday",
    "thurs": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}

SIMPLE_FRACTIONS = {
    "1/2": "one half",
    "1/4": "one quarter",
    "3/4": "three quarters",
    "1/8": "one eighth",
    "3/8": "three eighths",
}

FRACTION_WORD_PATTERN = (
    r'(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+'
    r'(?:half|halves|third|thirds|quarter|quarters|fifth|fifths|sixth|sixths|'
    r'seventh|sevenths|eighth|eighths|ninth|ninths|tenth|tenths|eleventh|elevenths|'
    r'twelfth|twelfths)'
)

NUMBER_WORDS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}

DENOMINATOR_WORDS = {
    2: ("half", "halves"),
    3: ("third", "thirds"),
    4: ("quarter", "quarters"),
    5: ("fifth", "fifths"),
    6: ("sixth", "sixths"),
    7: ("seventh", "sevenths"),
    8: ("eighth", "eighths"),
    9: ("ninth", "ninths"),
    10: ("tenth", "tenths"),
    11: ("eleventh", "elevenths"),
    12: ("twelfth", "twelfths"),
}


def validate_tts_profile(profile: str | None) -> str | None:
    """Return a validated TTS profile or raise for unsupported values."""
    if profile is None:
        return None

    normalized = profile.strip()
    if not normalized:
        return None

    if normalized not in ALLOWED_TTS_PROFILES:
        allowed = ", ".join(sorted(ALLOWED_TTS_PROFILES))
        raise ValueError(
            f"Unsupported TTS profile '{profile}'. Allowed profiles: {allowed}"
        )

    return normalized


def _replace_iso_datetime(match: re.Match[str]) -> str:
    """Convert ISO-style dates and datetimes into speech-friendly text."""
    raw = match.group(0)
    normalized = raw.strip()
    is_utc = normalized.endswith("Z")
    normalized = normalized.replace("Z", "+00:00")

    try:
        if "T" in normalized or " " in normalized[10:]:
            dt = datetime.fromisoformat(normalized)
            hour_24 = dt.hour
            minute = dt.minute
            hour_12 = hour_24 % 12 or 12
            am_pm = "AM" if hour_24 < 12 else "PM"
            spoken = f"{dt.strftime('%B')} {dt.day}, {dt.year} at {hour_12}:{minute:02d} {am_pm}"
            if is_utc or normalized.endswith("+00:00"):
                spoken += " UTC"
            return spoken

        date_only = datetime.strptime(normalized[:10], "%Y-%m-%d")
        return f"{date_only.strftime('%B')} {date_only.day}, {date_only.year}"
    except ValueError:
        return raw


# Broad emoji coverage for TTS (display text elsewhere is unchanged).
# Does not use \U00010000-\U0010ffff — that would drop many non-emoji chars.
_EMOJI_FOR_SPEECH_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # misc symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # regional indicators (flags)
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FAFF"  # extended-A / chess etc.
    "\U00002600-\U000026FF"  # misc symbols
    "\U0001F7E0-\U0001F7FF"  # geometric shapes extended
    "\U00002300-\U000023FF"  # technical
    "\U0001F000-\U0001F0FF"  # mahjong, playing cards
    "\U0001F200-\U0001F2FF"  # enclosed ideographic supplement
    "\u203C\u2049\u2122\u2139\u2194-\u2199\u21A9\u21AA\u231A\u231B"
    "\u2328\u23CF\u23E9-\u23F3\u23F8-\u23FA\u24C2"
    "\u25AA\u25AB\u25B6\u25C0\u25FB-\u25FE\u2600-\u27BF"
    "\u2934\u2935\u2B05-\u2B07\u2B1B\u2B1C\u2B50\u2B55"
    "\u3030\u303D\u3297\u3299"
    "\uFE0F"  # variation selector-16 (emoji style)
    "\u200D"  # ZWJ (emoji sequences)
    "\U0001F3FB-\U0001F3FF"  # skin tone modifiers
    "\u20E3"  # combining enclosing keycap
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji_for_speech(text: str) -> str:
    """Remove emoji so TTS does not pronounce or pause on them; UI can still show raw text."""
    if not text:
        return text
    # 🚨 U+1F6A8 — must run before bulk strip; _normalize_camera_alert also maps it to Alert
    text = text.replace("\U0001F6A8", "Alert ")
    text = _EMOJI_FOR_SPEECH_RE.sub("", text)
    text = re.sub(r" +", " ", text)
    return text


def _replace_simple_fraction(match: re.Match[str]) -> str:
    """Convert simple numeric fractions into spoken English."""
    numerator = int(match.group(1))
    denominator = int(match.group(2))

    numerator_word = NUMBER_WORDS.get(numerator)
    denominator_words = DENOMINATOR_WORDS.get(denominator)
    if numerator_word is None or denominator_words is None:
        return match.group(0)

    singular, plural = denominator_words
    if numerator == 1:
        article = "an" if singular[0] in "aeiou" else "one"
        if denominator == 2:
            article = "one"
        return f"{article} {singular}"

    return f"{numerator_word} {plural}"


def _strip_visual_noise(text: str) -> str:
    """Remove links, markdown, emoji, and other visual-only noise from spoken output."""
    text = re.sub(r'(?im)^\s*Sources?:\s*.*$', '', text)
    text = re.sub(r'(?i)\s+Sources?:\s*[^.\n]*(?:\.)?', '', text)
    text = re.sub(
        r'\(\s*(?:e\.g\.,?\s*)?(?:https?://|www\.|(?:[a-z0-9-]+\.)+[a-z]{2,})(?:/[^\s)]*)?\s*\)',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'(?i)\s*(?:Post|Tweet|Thread|Status|Message)\s+ID:\s*[A-Za-z0-9_-]{6,}\.?',
        '',
        text,
    )
    text = re.sub(
        r'(?im)^\s*[-*]\s*(?:https?://|www\.|(?:[a-z0-9-]+\.)+[a-z]{2,})(?:\S*)\s*$',
        '',
        text,
    )
    text = re.sub(r'[*_`]+', '', text)
    text = re.sub(r'(?m)^\s*#+\s*', '', text)
    text = re.sub(r'(?m)^\s*>\s*', '', text)
    text = re.sub(r'\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:https?://|www\.)[^\s]+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'stash://[^\s]+', 'saved to stash', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?', '', text)
    text = re.sub(r'(?<!\w)/(?:[\w.-]+/)*[\w.-]+', '', text)
    text = re.sub(r'[A-Za-z0-9]{32,}', '', text)
    text = re.sub(r'(?im)^\s*[-*]\s*$', '', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\[\s*\]', '', text)
    text = _strip_emoji_for_speech(text)
    return text


def _normalize_english_verbalization(text: str) -> str:
    """Expand common English abbreviations and date phrasing for speech."""
    text = re.sub(r'(?<!\w)i\.\s*e\.(?!\w)', 'that is', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<!\w)e\.\s*g\.(?!\w)', 'for example', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<!\w)etc\.(?!\w)', 'et cetera', text, flags=re.IGNORECASE)
    text = re.sub(r'\s&\s', ' and ', text)
    text = re.sub(r'\bNos?\.\s+(?=\d)', lambda m: 'numbers ' if m.group(0).lower().startswith('nos') else 'number ', text)
    text = re.sub(r'\bversion\s+v(?=\d)', 'version ', text, flags=re.IGNORECASE)
    text = re.sub(r'\btemp\.?(?!\w)', 'temperature', text, flags=re.IGNORECASE)
    text = re.sub(r'\bext\.(?=\s*\d)', 'extension', text, flags=re.IGNORECASE)
    text = re.sub(r'\bx\.(?=\s*\d)', 'extension', text, flags=re.IGNORECASE)
    text = re.sub(
        r'(?i)\b(\d{1,2}(?::\d{2})?)\s*([ap])(?:\s*\.?\s*m\.?)\b',
        lambda m: f"{m.group(1)} {'AM' if m.group(2).lower() == 'a' else 'PM'}",
        text,
    )
    text = re.sub(r'\b(AM|PM)\.(?=\s+[a-z])', r'\1', text)
    text = re.sub(
        r'\b(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)\.?(?=,\s|\s+[A-Z][a-z]+\s+\d)',
        lambda m: DAY_ABBREVIATIONS[m.group(0).strip().rstrip('.').lower()],
        text,
    )
    text = re.sub(
        r'\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(?=\d{1,2}(?:st|nd|rd|th)?\b)',
        lambda m: MONTH_ABBREVIATIONS[m.group(0).strip().rstrip('.').lower()] + ' ',
        text,
    )
    for fraction, spoken in SIMPLE_FRACTIONS.items():
        text = re.sub(rf'(?<!\d){re.escape(fraction)}(?!\d)', spoken, text)
    text = re.sub(r'(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)', _replace_simple_fraction, text)
    text = re.sub(r'\b(in|after)\s+00:(\d{2})\b', r'\1 \2 seconds', text, flags=re.IGNORECASE)
    return text


def _normalize_common_speech_patterns(text: str) -> str:
    """Convert common symbols and machine formatting into more natural speech."""
    text = _normalize_english_verbalization(text)
    text = re.sub(r'(?:(?<=\s)|(?<=[(:=]))>(?=\s*\S)', 'greater than ', text)
    text = re.sub(r'(?:(?<=\s)|(?<=[(:=]))<(?=\s*\S)', 'less than ', text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*°\s*F\b', r'\1 degrees', text, flags=re.IGNORECASE)
    text = re.sub(
        r'(\d+(?:\.\d+)?)\s*°\s*C\b',
        r'\1 degrees Celsius',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%(?=\s|$)', r'\1 percent', text)
    text = re.sub(r'(\d+)\s*[–-]\s*(\d+)\s*mph\b', r'\1 to \2 miles per hour', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*mph\b', r'\1 miles per hour', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*GB/s\b', r'\1 gigabytes per second', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*GB\b', r'\1 gigabytes', text, flags=re.IGNORECASE)
    text = re.sub(rf'({FRACTION_WORD_PATTERN})\s*GB\b', r'\1 gigabytes', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*TB\b', r'\1 terabytes', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*RAM\b', r'\1 gigabytes RAM', text, flags=re.IGNORECASE)
    return text


def _normalize_general_currency(text: str) -> str:
    """Normalize common currency symbols for general-purpose speech."""
    def replace_dollars(match: re.Match[str]) -> str:
        amount = match.group(1)
        if "." in amount:
            dollars, cents = amount.split(".", 1)
            if int(dollars.replace(",", "")) == 0 and len(cents) > 2:
                return f"{amount} dollars"
            if cents == "00":
                return f"{dollars} dollars"
            return f"{dollars} dollars and {cents} cents"
        return f"{amount} dollars"

    def replace_euros(match: re.Match[str]) -> str:
        amount = match.group(1)
        if "." in amount:
            euros, cents = amount.split(".", 1)
            if int(euros.replace(",", "")) == 0 and len(cents) > 2:
                return f"{amount} euros"
            if cents == "00":
                return f"{euros} euros"
            return f"{euros} euros and {cents} cents"
        return f"{amount} euros"

    text = re.sub(r'\$([0-9][0-9,]*(?:\.\d+)?)\b', replace_dollars, text)
    text = re.sub(r'€([0-9][0-9,]*(?:\.\d+)?)\b', replace_euros, text)
    return text


def _normalize_price_quote(text: str) -> str:
    """Make market and price phrasing more natural for TTS."""
    text = re.sub(r'\b24\s*h(?:r|rs)?\b', '24 hours', text, flags=re.IGNORECASE)
    text = re.sub(r'\+(\d+(?:\.\d+)?)\s*percent\b', r'up \1 percent', text, flags=re.IGNORECASE)
    text = re.sub(r'-(\d+(?:\.\d+)?)\s*percent\b', r'down \1 percent', text, flags=re.IGNORECASE)

    def replace_currency(match: re.Match[str]) -> str:
        dollars = match.group(1)
        decimals = match.group(2)
        if decimals is None:
            return f"{dollars} dollars"
        if decimals == "00":
            return f"{dollars} dollars"
        if len(decimals) == 2 and int(dollars.replace(",", "")) >= 1:
            return f"{dollars} dollars and {decimals} cents"
        return f"{dollars}.{decimals} dollars"

    text = re.sub(r'\$([0-9][0-9,]*)(?:\.(\d+))?\b', replace_currency, text)
    text = re.sub(r'\bUSD\b', 'dollars', text, flags=re.IGNORECASE)
    return text


def _normalize_timestamped(text: str) -> str:
    """Convert machine timestamps into natural spoken dates/times."""
    text = re.sub(
        r'\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?\b',
        _replace_iso_datetime,
        text,
    )
    text = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', _replace_iso_datetime, text)
    return text


def _normalize_camera_alert(text: str) -> str:
    """Smooth out camera and safety alert phrasing for TTS."""
    text = text.replace("🚨", "Alert")
    text = re.sub(r'\b(Person|Package|Vehicle|Animal|Motion):\s+', r'\1 at ', text)
    text = re.sub(r'\bCamera Offline:\s+', 'Camera offline at ', text)
    text = re.sub(r'\bSensor Offline:\s+', 'Sensor offline at ', text)
    text = re.sub(r'\bSMOKE/CO ALARM\b', 'smoke or carbon monoxide alarm', text, flags=re.IGNORECASE)
    text = re.sub(r'\bCO\b', 'carbon monoxide', text)
    text = re.sub(r'\bUniFi\b', 'UniFi', text)
    return text


def _apply_profile_rules(text: str, profile: str | None) -> str:
    """Apply profile-specific cleanup for known speech contexts."""
    if profile == "weather_watch":
        text = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', text)
    elif profile == "price_quote":
        text = _normalize_price_quote(text)
    elif profile == "timestamped":
        text = _normalize_timestamped(text)
    elif profile == "camera_alert":
        text = _normalize_camera_alert(text)
    return text


def _normalize_whitespace(text: str) -> str:
    """Clean punctuation and spacing after substitutions."""
    text = re.sub(r'\s+([,.;:!?])', r'\1', text)
    text = re.sub(r'([,.;:!?]){2,}', r'\1', text)
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def normalize_tts_text(text: str, profile: str | None = None) -> str:
    """Normalize text for natural, safe TTS playback (emoji stripped; UI may keep raw text)."""
    if not text:
        return ""

    text = _strip_visual_noise(text)
    text = _normalize_common_speech_patterns(text)
    text = _normalize_general_currency(text)
    text = _apply_profile_rules(text, profile)
    return _normalize_whitespace(text)
