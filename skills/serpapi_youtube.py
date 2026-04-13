#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi YouTube
Fetch YouTube video details through SerpApi, with optional transcript fallback.
"""
import json
import os
import re
import sys
from typing import Any
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "no_cache",
    "v",
    "video_id",
    "gl",
    "hl",
    "language_code",
    "title",
    "type",
}

VALID_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

MAX_TRANSCRIPT_CHARS = 20000


def return_success(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": False, "speech": speech, "error": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def extract_video_id(url_or_id: str) -> str | None:
    raw = (url_or_id or "").strip()
    if not raw:
        return None

    # Accept bare YouTube IDs directly.
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw

    try:
        parsed = urlparse(raw)
    except Exception:
        return None

    host = parsed.netloc.lower()
    if host not in VALID_HOSTS:
        return None

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else None

    if parsed.path == "/watch":
        query = parse_qs(parsed.query or "")
        candidate = (query.get("v") or [None])[0]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
        candidate = parts[1]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else None

    return None


def _normalize_transcript_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for item in payload.get("available_transcripts") or []:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": item.get("title"),
                "language_name": item.get("language_name"),
                "language_code": item.get("language_code"),
                "type": item.get("type"),
                "selected": item.get("selected"),
                "serpapi_link": item.get("serpapi_link"),
            }
        )
    return results


def _join_transcript_snippets(transcript_items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in transcript_items:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if snippet:
            parts.append(snippet)
    return " ".join(parts).strip()


def fetch_transcript(
    video_id: str,
    language_code: str,
    transcript_title: str,
    transcript_type: str,
    no_cache: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "engine": "youtube_video_transcript",
        "v": video_id,
        "no_cache": "true" if no_cache else "false",
    }
    if language_code:
        params["language_code"] = language_code
    if transcript_title:
        params["title"] = transcript_title
    if transcript_type:
        params["type"] = transcript_type

    payload = request_serpapi(params)
    transcript_items = payload.get("transcript") or []
    transcript_text = _join_transcript_snippets(transcript_items)
    transcript_truncated = len(transcript_text) > MAX_TRANSCRIPT_CHARS
    if transcript_truncated:
        transcript_text = transcript_text[:MAX_TRANSCRIPT_CHARS].rstrip() + "..."

    return {
        "requested_language_code": language_code or None,
        "requested_title": transcript_title or None,
        "requested_type": transcript_type or None,
        "transcript_count": len(transcript_items) if isinstance(transcript_items, list) else 0,
        "transcript": transcript_items if isinstance(transcript_items, list) else [],
        "transcript_text": transcript_text or None,
        "transcript_text_truncated": transcript_truncated,
        "chapters": payload.get("chapters") or [],
        "available_transcripts": _normalize_transcript_list(payload),
        "search_metadata": payload.get("search_metadata", {}),
    }


def normalize_video_data(payload: dict[str, Any], video_id: str) -> dict[str, Any]:
    channel = payload.get("channel") if isinstance(payload.get("channel"), dict) else {}
    transcript = payload.get("transcript") if isinstance(payload.get("transcript"), dict) else {}

    thumbnail = payload.get("thumbnail")
    if isinstance(thumbnail, dict):
        thumbnail = thumbnail.get("static") or thumbnail.get("rich")

    related_videos = []
    for item in (payload.get("related_videos") or [])[:5]:
        if not isinstance(item, dict):
            continue
        related_videos.append(
            {
                "video_id": item.get("video_id"),
                "title": item.get("title"),
                "url": item.get("link"),
                "thumbnail": (
                    item.get("thumbnail", {}).get("static")
                    if isinstance(item.get("thumbnail"), dict)
                    else item.get("thumbnail")
                ),
                "published_date": item.get("published_date"),
                "views": item.get("views"),
                "extracted_views": item.get("extracted_views"),
                "length": item.get("length"),
                "channel": item.get("channel", {}).get("name")
                if isinstance(item.get("channel"), dict)
                else None,
            }
        )

    return {
        "video_id": video_id,
        "url": payload.get("link") or f"https://www.youtube.com/watch?v={video_id}",
        "title": payload.get("title"),
        "description": payload.get("description"),
        "thumbnail": thumbnail,
        "channel": channel.get("name"),
        "channel_url": channel.get("link"),
        "channel_thumbnail": channel.get("thumbnail"),
        "channel_verified": channel.get("verified"),
        "subscribers": channel.get("subscribers"),
        "extracted_subscribers": channel.get("extracted_subscribers"),
        "views": payload.get("views"),
        "extracted_views": payload.get("extracted_views"),
        "likes": payload.get("likes"),
        "extracted_likes": payload.get("extracted_likes"),
        "published_date": payload.get("published_date"),
        "duration": payload.get("length"),
        "live": payload.get("live"),
        "comment_count": payload.get("comment_count"),
        "extracted_comment_count": payload.get("extracted_comment_count"),
        "category": payload.get("category"),
        "keywords": payload.get("keywords"),
        "transcript_api_url": transcript.get("serpapi_link"),
        "related_videos": related_videos,
        "search_metadata": payload.get("search_metadata", {}),
        "search_information": payload.get("search_information", {}),
    }


def build_speech(video: dict[str, Any], transcript_data: dict[str, Any] | None) -> str:
    title = (video.get("title") or "that YouTube video").strip()
    channel = video.get("channel")
    views = video.get("views")
    published = video.get("published_date")

    details = []
    if channel:
        details.append(f"by {channel}")
    if published:
        details.append(published)
    if views:
        details.append(views)

    if transcript_data and transcript_data.get("transcript_count"):
        return (
            f"Fetched YouTube details for {title}"
            + (f" {' '.join(details)}" if details else "")
            + f". Transcript is available with {transcript_data['transcript_count']} segments."
        )

    if video.get("transcript_api_url"):
        return (
            f"Fetched YouTube details for {title}"
            + (f" {' '.join(details)}" if details else "")
            + ". Transcript lookup is available through SerpApi."
        )

    return f"Fetched YouTube details for {title}" + (f" {' '.join(details)}." if details else ".")


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        url = str(input_data.get("url", "")).strip()
        video_id_input = str(input_data.get("video_id", "")).strip()
        gl = str(input_data.get("gl", "")).strip()
        hl = str(input_data.get("hl", "en")).strip()
        language_code = str(input_data.get("language_code", "en")).strip()
        transcript_title = str(input_data.get("transcript_title", "")).strip()
        transcript_type = str(input_data.get("transcript_type", "")).strip()
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_transcript = parse_bool(input_data.get("include_transcript", True), default=True)
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        video_id = extract_video_id(video_id_input or url)
        if not video_id:
            return_error("Provide a valid YouTube URL or video_id.")
            return 1

        params: dict[str, Any] = {
            "engine": "youtube_video",
            "v": video_id,
            "no_cache": "true" if no_cache else "false",
        }
        if gl:
            params["gl"] = gl
        if hl:
            params["hl"] = hl

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(params)
        video_data = normalize_video_data(payload, video_id=video_id)

        transcript_data = None
        transcript_error = None
        if include_transcript and video_data.get("transcript_api_url"):
            try:
                transcript_data = fetch_transcript(
                    video_id=video_id,
                    language_code=language_code,
                    transcript_title=transcript_title,
                    transcript_type=transcript_type,
                    no_cache=no_cache,
                )
            except Exception as exc:
                transcript_error = str(exc)

        data: dict[str, Any] = {
            **video_data,
            "gl": gl or None,
            "hl": hl or None,
            "include_transcript": include_transcript,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi",
        }
        if transcript_data is not None:
            data["transcript_data"] = transcript_data
        if transcript_error:
            data["transcript_error"] = transcript_error
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(video_data, transcript_data), data=data)
        return 0

    except Exception as exc:
        msg = str(exc)
        if "timeout" in msg.lower():
            return_error("SerpApi YouTube request timed out.")
            return 1
        if "HTTP " in msg:
            return_error(msg)
            return 1
        return_error(f"SerpApi YouTube tool error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
