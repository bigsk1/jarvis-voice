#!/usr/bin/env python3
"""Jarvis Skill: structured Google Sports data through SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, quote, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


GOOGLE_SPORTS_TIMEOUT = 90
DEFAULT_MAX_RESULTS = 12
LOCALE_RE = re.compile(r"^[a-z]{2}$")
KGMID_RE = re.compile(r"^/(?:m|g)/[A-Za-z0-9_\-]+$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

SPORTS = {
    "football": ("american_football", "af"),
    "soccer": ("football", "ft"),
    "association_football": ("football", "ft"),
    "association football": ("football", "ft"),
    "ft": ("football", "ft"),
    "basketball": ("basketball", "bs"),
    "nba": ("basketball", "bs"),
    "bs": ("basketball", "bs"),
    "baseball": ("baseball", "bb"),
    "mlb": ("baseball", "bb"),
    "bb": ("baseball", "bb"),
    "cricket": ("cricket", "cr"),
    "cr": ("cricket", "cr"),
    "american_football": ("american_football", "af"),
    "american football": ("american_football", "af"),
    "nfl": ("american_football", "af"),
    "af": ("american_football", "af"),
    "ice_hockey": ("ice_hockey", "ih"),
    "ice hockey": ("ice_hockey", "ih"),
    "hockey": ("ice_hockey", "ih"),
    "nhl": ("ice_hockey", "ih"),
    "ih": ("ice_hockey", "ih"),
    "rugby": ("rugby", "rg"),
    "rg": ("rugby", "rg"),
}
TABS = {
    "games": ("games", "gm"),
    "game": ("games", "gm"),
    "schedule": ("games", "gm"),
    "scores": ("games", "gm"),
    "gm": ("games", "gm"),
    "standings": ("standings", "sn"),
    "standing": ("standings", "sn"),
    "sn": ("standings", "sn"),
    "players": ("players", "pl"),
    "roster": ("players", "pl"),
    "pl": ("players", "pl"),
    "brackets": ("brackets", "br"),
    "bracket": ("brackets", "br"),
    "playoffs": ("brackets", "br"),
    "br": ("brackets", "br"),
    "stats": ("stats", "st"),
    "statistics": ("stats", "st"),
    "st": ("stats", "st"),
    "rankings": ("rankings", "rn"),
    "ranking": ("rankings", "rn"),
    "rn": ("rankings", "rn"),
    "overview": ("overview", "ov"),
    "ov": ("overview", "ov"),
}
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "q",
    "kgmid",
    "sp",
    "type",
    "tab",
    "gl",
    "hl",
    "mpd",
    "moa",
    "mob",
    "season_kgmid",
    "no_cache",
}


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _text(value: Any, maximum: int = 500) -> str | None:
    compact = " ".join(str(value or "").split())
    if not compact:
        return None
    return compact if len(compact) <= maximum else compact[: maximum - 3].rstrip() + "..."


def _required_text(value: Any, label: str, maximum: int) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) > maximum:
        raise ValueError(f"'{label}' must be {maximum} characters or fewer.")
    return compact


def _dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _http_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    if any(character.isspace() for character in parsed.netloc):
        return None
    return url


def _compact_dict(value: Any, fields: Iterable[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    compact = {
        field: value[field]
        for field in fields
        if value.get(field) not in (None, "", [], {})
    }
    return compact or None


def normalize_locale(value: Any, label: str, default: str) -> str:
    locale = str(value or default).strip().lower()
    if not LOCALE_RE.fullmatch(locale):
        raise ValueError(f"'{label}' must be a two-letter code such as us or en.")
    return locale


def normalize_sport(value: Any) -> tuple[str, str]:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized not in SPORTS:
        raise ValueError(
            "'sport' must be football, soccer, basketball, baseball, cricket, "
            "american_football, ice_hockey, or rugby."
        )
    return SPORTS[normalized]


def normalize_entity_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"game", "league", "team"}:
        raise ValueError("'entity_type' must be game, league, or team.")
    return normalized


def normalize_tab(value: Any, entity_type: str, sport_code: str) -> tuple[str | None, str | None]:
    if value in (None, ""):
        return (None, None) if entity_type == "game" else ("games", "gm")
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in TABS:
        raise ValueError(
            "'tab' must be games, standings, players, brackets, stats, rankings, or overview."
        )
    friendly, code = TABS[normalized]
    if entity_type == "game":
        if friendly != "overview" or sport_code != "af":
            raise ValueError(
                "Game entities only support the overview tab for American football; omit tab otherwise."
            )
    elif friendly == "overview":
        raise ValueError("The overview tab is only valid for American football game entities.")
    elif friendly in {"stats", "rankings"} and entity_type != "league":
        raise ValueError(f"The {friendly} tab is only valid for league entities.")
    return friendly, code


def normalize_kgmid(value: Any, label: str = "kgmid") -> str | None:
    kgmid = str(value or "").strip()
    if not kgmid:
        return None
    if len(kgmid) > 100 or not KGMID_RE.fullmatch(kgmid):
        raise ValueError(f"'{label}' must be a Google Knowledge Graph ID such as /m/0jmk7.")
    return kgmid


def normalize_utc(value: Any, label: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if not UTC_RE.fullmatch(raw):
        raise ValueError(f"'{label}' must use UTC format YYYY-MM-DDTHH:mm:ssZ.")
    try:
        datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"'{label}' is not a valid UTC date and time.") from exc
    return raw


def _serpapi_request(params: dict[str, Any]) -> dict[str, Any]:
    # The wrapper remains proxy-capable; proxy_policy=off keeps direct access as default.
    return request_serpapi(
        params,
        timeout=GOOGLE_SPORTS_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def _link_parameters(value: Any) -> dict[str, str]:
    url = _http_url(value)
    if not url:
        return {}
    parsed = parse_qs(urlsplit(url).query)
    return {key: values[0] for key, values in parsed.items() if values}


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dicts(nested)


def resolve_kgmid(
    payload: dict[str, Any], *, query: str, entity_type: str, sport_code: str
) -> tuple[str | None, str | None, dict[str, str]]:
    """Resolve the required Sports API ID without exposing a second Jarvis tool call."""
    sports = payload.get("sports_results")
    sports = sports if isinstance(sports, dict) else {}

    if entity_type == "game":
        game_candidates = []
        spotlight = sports.get("game_spotlight")
        if isinstance(spotlight, dict):
            game_candidates.append(spotlight)
        game_candidates.extend(_dicts(sports.get("games")))
        for item in game_candidates:
            params = _link_parameters(item.get("google_sports_serpapi_link"))
            kgmid = normalize_kgmid(params.get("kgmid") or item.get("kgmid"))
            if kgmid and (not params.get("type") or params.get("type") == "game"):
                return kgmid, "google_sports_game", params

    query_tokens = {
        token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 1
    }
    named_matches: list[tuple[int, str, str, dict[str, str]]] = []
    expected_container = "teams" if entity_type == "team" else "league"
    for node in _walk_dicts(sports):
        link_params = _link_parameters(node.get("google_sports_serpapi_link"))
        if link_params.get("type") == entity_type:
            candidate = normalize_kgmid(link_params.get("kgmid"))
            if candidate:
                return candidate, "google_sports_link", link_params

        name = _text(node.get("name") or node.get("title"), 300)
        candidate = normalize_kgmid(node.get("kgmid"))
        if not name or not candidate:
            continue
        lowered_name = name.lower()
        score = sum(1 for token in query_tokens if token in lowered_name)
        if score:
            named_matches.append((score, name, candidate, link_params))

    if named_matches:
        named_matches.sort(key=lambda row: (-row[0], len(row[1])))
        return named_matches[0][2], f"google_sports_{expected_container}_match", named_matches[0][3]

    knowledge = payload.get("knowledge_graph")
    knowledge = knowledge if isinstance(knowledge, dict) else {}
    knowledge_kgmid = normalize_kgmid(knowledge.get("kgmid"))
    if knowledge_kgmid:
        return knowledge_kgmid, "google_knowledge_graph", {}
    return None, None, {}


def _compact_scalar_dict(value: Any, maximum: int = 16) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    compact = {
        str(key): item
        for key, item in list(value.items())[:maximum]
        if isinstance(item, (str, int, float, bool)) and item not in (None, "")
    }
    return compact or None


def _linescore(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in _dicts(value)[:24]:
        compact = _compact_dict(item, ("title", "short_title", "score", "value"))
        if compact:
            rows.append(compact)
    return rows


def _watch(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    groups = []
    for group in _dicts(value.get("groups"))[:8]:
        sources = []
        for item in _dicts(group.get("sources"))[:12]:
            compact = {
                "title": _text(item.get("title"), 200),
                "subtitle": _text(item.get("subtitle"), 200),
                "url": _http_url(item.get("link") or item.get("url")),
            }
            compact = {
                key: field for key, field in compact.items() if field not in (None, "")
            }
            if compact:
                sources.append(compact)
        if sources:
            groups.append(
                {
                    "title": _text(group.get("title") or group.get("name"), 200)
                    or "Viewing options",
                    "sources": sources,
                }
            )
    return {"groups": groups} if groups else None


def _more_info(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in _dicts(value)[:8]:
        compact = {
            "title": _text(item.get("title"), 250),
            "url": _http_url(item.get("link") or item.get("url")),
        }
        compact = {
            key: field for key, field in compact.items() if field not in (None, "")
        }
        if compact:
            rows.append(compact)
    return rows


def _team(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    score = value.get("score")
    if isinstance(score, dict):
        score = score.get("total") or score.get("current")
    compact = {
        "name": _text(value.get("name") or value.get("title"), 250),
        "short_name": _text(value.get("short_name"), 100),
        "short_code": _text(value.get("short_code"), 50),
        "kgmid": normalize_kgmid(value.get("kgmid")),
        "thumbnail": _http_url(value.get("thumbnail")),
        "score": score,
        "score_original": value.get("score_original"),
        "season_record": _compact_scalar_dict(value.get("season_record")),
        "linescore": _linescore(value.get("linescore")),
        "rank": value.get("rank"),
        "seeding": value.get("seeding"),
        "win": value.get("win") if isinstance(value.get("win"), bool) else None,
        "red_card": value.get("red_card") if isinstance(value.get("red_card"), bool) else None,
    }
    return {key: item for key, item in compact.items() if item not in (None, "", [], {})} or None


def _stats(value: Any, maximum: int = 12) -> list[dict[str, Any]]:
    rows = []
    for item in _dicts(value)[:maximum]:
        compact = _compact_dict(
            item,
            (
                "type",
                "title",
                "short_title",
                "value",
                "values",
                "highlighted",
                "rank",
            ),
        )
        if compact:
            rows.append(compact)
    return rows


def _box_score(value: Any, teams: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    normalized_teams = []
    for team_box in _dicts(value.get("teams"))[:4]:
        team_index = team_box.get("team_index")
        team_identity = None
        if isinstance(team_index, int) and 0 <= team_index < len(teams):
            team_identity = _compact_dict(
                teams[team_index], ("name", "short_name", "short_code", "kgmid")
            )
        groups = []
        for group in _dicts(team_box.get("groups"))[:12]:
            player_groups = []
            for player_group in _dicts(group.get("player_groups"))[:8]:
                players = []
                for player in _dicts(player_group.get("players"))[:40]:
                    compact = {
                        "name": _text(player.get("name") or player.get("title"), 250),
                        "short_name": _text(player.get("short_name"), 120),
                        "position": _text(player.get("position"), 100),
                        "jersey_number": _text(player.get("jersey_number"), 50),
                        "kgmid": normalize_kgmid(player.get("kgmid")),
                        "stats": _stats(player.get("stats"), maximum=24),
                    }
                    compact = {
                        key: field
                        for key, field in compact.items()
                        if field not in (None, "", [], {})
                    }
                    if compact:
                        players.append(compact)
                if players:
                    player_groups.append(
                        {
                            "type": _text(player_group.get("type"), 100) or "Player",
                            "players": players,
                        }
                    )
            if player_groups:
                groups.append(
                    {
                        "title": _text(group.get("title") or group.get("name"), 200)
                        or "Box score",
                        "player_groups": player_groups,
                    }
                )
        if groups:
            normalized = {"team_index": team_index, "groups": groups}
            if team_identity:
                normalized["team"] = team_identity
            normalized_teams.append(normalized)
    return {"teams": normalized_teams} if normalized_teams else None


_NOTABLE_STAT_WEIGHTS = {
    "home_runs": 10.0,
    "goals": 10.0,
    "touchdowns": 10.0,
    "points": 1.0,
    "rbi": 3.0,
    "batter_hits": 2.0,
    "runs": 2.0,
    "assists": 3.0,
    "rebounds": 1.5,
    "steals": 3.0,
    "blocks": 3.0,
    "strikeouts": 2.0,
    "saves": 3.0,
    "innings_pitched": 0.5,
    "passing_yards": 0.02,
    "rushing_yards": 0.03,
    "receiving_yards": 0.03,
}


def _numeric_stat(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _box_score_highlights(value: Any, maximum: int = 16) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    highlights = []
    for team_box in _dicts(value.get("teams")):
        team = team_box.get("team") if isinstance(team_box.get("team"), dict) else {}
        team_name = team.get("short_name") or team.get("name") or team.get("short_code")
        for group in _dicts(team_box.get("groups")):
            category = _text(group.get("title"), 150) or "Box score"
            ranked = []
            for player_group in _dicts(group.get("player_groups")):
                for player in _dicts(player_group.get("players")):
                    nonzero_stats = []
                    impact = 0.0
                    for stat in _dicts(player.get("stats")):
                        numeric = _numeric_stat(stat.get("value"))
                        if numeric == 0:
                            continue
                        stat_type = str(stat.get("type") or "").lower()
                        weight = _NOTABLE_STAT_WEIGHTS.get(stat_type, 0.1)
                        impact += abs(numeric) * weight
                        compact_stat = _compact_dict(
                            stat, ("type", "title", "short_title", "value")
                        )
                        if compact_stat:
                            nonzero_stats.append(compact_stat)
                    if nonzero_stats:
                        ranked.append((impact, player, nonzero_stats))
            ranked.sort(key=lambda item: item[0], reverse=True)
            for _impact, player, nonzero_stats in ranked[:3]:
                compact = {
                    "team": team_name,
                    "category": category,
                    "name": _text(player.get("name"), 250),
                    "position": _text(player.get("position"), 100),
                    "kgmid": normalize_kgmid(player.get("kgmid")),
                    "stats": nonzero_stats,
                }
                highlights.append(
                    {
                        key: field
                        for key, field in compact.items()
                        if field not in (None, "", [], {})
                    }
                )
    return highlights[:maximum]


def _highlights(value: Any) -> list[dict[str, Any]]:
    rows = _dicts(value)
    if isinstance(value, dict):
        rows = [value]
    highlights = []
    for item in rows[:4]:
        compact = {
            "title": _text(item.get("title") or item.get("source_title"), 300),
            "url": _http_url(item.get("link") or item.get("url")),
            "thumbnail": _http_url(item.get("thumbnail")),
            "duration": _text(item.get("duration"), 50),
            "posted_at": _text(item.get("posted_at"), 100),
        }
        compact = {key: field for key, field in compact.items() if field not in (None, "")}
        if compact:
            highlights.append(compact)
    return highlights


def _game(item: dict[str, Any], *, position: int, group: str | None = None) -> dict[str, Any] | None:
    teams = [team for raw in _dicts(item.get("teams")) if (team := _team(raw))]
    team_names = [str(team.get("name")) for team in teams if team.get("name")]
    title = _text(item.get("title"), 300) or (" vs ".join(team_names) if team_names else None)
    if not title and not item.get("kgmid"):
        return None
    league = _compact_dict(item.get("league"), ("name", "short_name", "kgmid"))
    venue = _compact_dict(item.get("venue"), ("name", "alt_name", "location", "kgmid"))
    highlights = _highlights(
        item.get("highlights")
        or item.get("video_highlights")
        or item.get("video_highlight_carousel")
    )
    watch = _watch(item.get("watch"))
    more_info = _more_info(item.get("more_info"))
    kgmid = normalize_kgmid(item.get("kgmid"))
    serpapi_link = _http_url(item.get("serpapi_link") or item.get("google_sports_serpapi_link"))
    public_url = _http_url(item.get("link"))
    if not public_url and kgmid:
        public_url = f"https://www.google.com/search?kgmid={quote(kgmid, safe='')}"
    result = {
        "kind": "game",
        "position": position,
        "group": group,
        "title": title,
        "teams": teams,
        "status": _text(item.get("status") or item.get("stage"), 100),
        "status_original": _text(item.get("status_original"), 100),
        "date": _text(item.get("date"), 100),
        "time": _text(item.get("time"), 100),
        "start_time": _text(item.get("start_time"), 100),
        "end_time": _text(item.get("end_time"), 100),
        "league": league,
        "tournament": _text(item.get("tournament"), 200),
        "venue": venue,
        "stadium": _text(item.get("stadium") or item.get("arena"), 200),
        "kgmid": kgmid,
        "url": public_url,
        "serpapi_link": serpapi_link,
        "highlights": highlights,
        "watch": watch,
        "more_info": more_info,
    }
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _game_rows(root: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in _dicts(root.get("game_groups")):
        group_name = _text(group.get("title") or group.get("name"), 250)
        for item in _dicts(group.get("games")):
            game = _game(item, position=len(rows) + 1, group=group_name)
            if game:
                rows.append(game)
    if not rows:
        for item in _dicts(root.get("games")):
            game = _game(item, position=len(rows) + 1)
            if game:
                rows.append(game)
    return rows


def _standing_rows(root: dict[str, Any]) -> list[dict[str, Any]]:
    standings = root.get("standings")
    standings = standings if isinstance(standings, dict) else {}
    rows: list[dict[str, Any]] = []
    groups = _dicts(standings.get("groups"))
    for group_index, group in enumerate(groups, 1):
        group_name = _text(group.get("title") or group.get("name"), 250) or f"Group {group_index}"
        divisions = _dicts(group.get("divisions"))
        sources = [(None, group.get("teams"))]
        sources.extend(
            (_text(division.get("title") or division.get("name"), 250), division.get("teams"))
            for division in divisions
        )
        for division_name, team_rows in sources:
            for item in _dicts(team_rows):
                team = _team(item) or {}
                result = {
                    "kind": "standing",
                    "position": len(rows) + 1,
                    "group": group_name,
                    "division": division_name,
                    "rank": item.get("rank"),
                    "title": team.get("name"),
                    "name": team.get("name"),
                    "kgmid": team.get("kgmid"),
                    "thumbnail": team.get("thumbnail"),
                    "url": _http_url(item.get("link") or item.get("serpapi_link")),
                    "league_movement": _text(item.get("league_movement"), 250),
                    "highlighted": item.get("highlighted") if isinstance(item.get("highlighted"), bool) else None,
                    "stats": _stats(item.get("stats")),
                }
                rows.append({key: value for key, value in result.items() if value not in (None, "", [], {})})
    return rows


def _prioritize_team_standings(
    rows: list[dict[str, Any]], team_kgmid: str | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    """Put the requested team's standings context ahead of bounded league rows."""
    selected = next(
        (
            row
            for row in rows
            if team_kgmid and row.get("kgmid") == team_kgmid
        ),
        None,
    )
    if selected is None:
        selected = next((row for row in rows if row.get("highlighted") is True), None)
    if selected is None:
        return rows, None, []

    selected_group = selected.get("group")
    selected_division = selected.get("division")
    if selected_division:
        peers = [
            row
            for row in rows
            if row is not selected
            and row.get("group") == selected_group
            and row.get("division") == selected_division
        ]
    elif selected_group:
        peers = [
            row
            for row in rows
            if row is not selected and row.get("group") == selected_group
        ]
    else:
        peers = []

    context = [selected, *peers]
    context_ids = {id(row) for row in context}
    prioritized = [*context, *(row for row in rows if id(row) not in context_ids)]
    return prioritized, selected, context


def _person_rows(value: Any, *, kind: str, group: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for item in _dicts(value):
        title = _text(item.get("name") or item.get("title"), 300)
        player = item.get("player")
        if isinstance(player, dict):
            title = _text(player.get("name") or player.get("title"), 300) or title
        source = player if isinstance(player, dict) else item
        raw_team = item.get("team") or source.get("team")
        team = (
            _compact_dict(raw_team, ("name", "short_name", "short_code", "kgmid", "thumbnail"))
            if isinstance(raw_team, dict)
            else _text(raw_team, 200)
        )
        result = {
            "kind": kind,
            "position": len(rows) + 1,
            "group": group,
            "rank": item.get("rank"),
            "title": title,
            "name": title,
            "player_position": _text(source.get("position"), 150),
            "jersey_number": _text(source.get("jersey_number"), 50),
            "team": team,
            "kgmid": normalize_kgmid(source.get("kgmid")),
            "thumbnail": _http_url(source.get("thumbnail")),
            "value": item.get("value"),
            "stats": _stats(item.get("stats") or source.get("stats")),
            "url": _http_url(item.get("link") or item.get("serpapi_link")),
        }
        compact = {key: field for key, field in result.items() if field not in (None, "", [], {})}
        if title or compact.get("value") not in (None, ""):
            rows.append(compact)
    return rows


def _grouped_rows(root: dict[str, Any], key: str, *, kind: str) -> list[dict[str, Any]]:
    section = root.get(key)
    if isinstance(section, list):
        return _person_rows(section, kind=kind)
    section = section if isinstance(section, dict) else {}
    direct = section.get("players") or section.get("teams") or section.get("results")
    rows = _person_rows(direct, kind=kind)
    if rows:
        return rows
    for group in _dicts(section.get("groups")):
        group_name = _text(group.get("title") or group.get("name"), 250)
        values = group.get("players") or group.get("teams") or group.get("results")
        rows.extend(_person_rows(values, kind=kind, group=group_name))
    for index, row in enumerate(rows, 1):
        row["position"] = index
    return rows


def _bracket_rows(root: dict[str, Any]) -> list[dict[str, Any]]:
    section = root.get("brackets")
    section = section if isinstance(section, dict) else {}
    rows: list[dict[str, Any]] = []
    stages = _dicts(section.get("stages")) or _dicts(section.get("rounds"))
    for stage in stages:
        group = _text(stage.get("title") or stage.get("name"), 250)
        for item in _dicts(stage.get("games") or stage.get("matches")):
            game = _game(item, position=len(rows) + 1, group=group)
            if game:
                rows.append(game)
    return rows or _game_rows(section)


def extract_results(payload: dict[str, Any], *, entity_type: str, tab: str | None) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    root_key = f"{entity_type}_results"
    root = payload.get(root_key)
    root = root if isinstance(root, dict) else {}
    extras: dict[str, Any] = {}

    if entity_type == "game":
        info = root.get("info") if isinstance(root.get("info"), dict) else root
        rows = []
        game = _game(info, position=1)
        if game:
            rows.append(game)
            if game.get("watch"):
                extras["watch"] = game["watch"]
            if game.get("more_info"):
                extras["more_info"] = game["more_info"]
        box_score = _box_score(
            root.get("box_scores"),
            game.get("teams", []) if game else [],
        )
        if box_score:
            extras["box_score"] = box_score
            extras["box_score_highlights"] = _box_score_highlights(box_score)
        team_stats = root.get("team_stats")
        if isinstance(team_stats, (dict, list)):
            extras["team_stats"] = team_stats
        kind = "game"
    elif tab == "standings":
        rows, kind = _standing_rows(root), "standing"
    elif tab == "players":
        rows, kind = _grouped_rows(root, "players", kind="player"), "player"
    elif tab == "stats":
        rows, kind = _grouped_rows(root, "stats", kind="stat"), "stat"
    elif tab == "rankings":
        rows, kind = _grouped_rows(root, "rankings", kind="ranking"), "ranking"
    elif tab == "brackets":
        rows, kind = _bracket_rows(root), "game"
    else:
        rows, kind = _game_rows(root), "game"

    standings = root.get("standings")
    if isinstance(standings, dict):
        seasons = []
        for item in _dicts(standings.get("seasons"))[:20]:
            league = _compact_dict(item.get("league"), ("name", "kgmid"))
            compact = {
                "name": _text(item.get("name"), 100),
                "kgmid": normalize_kgmid(item.get("kgmid")),
                "url": _http_url(item.get("serpapi_link")),
                "selected": item.get("selected") if isinstance(item.get("selected"), bool) else None,
                "league": league,
            }
            compact = {key: value for key, value in compact.items() if value not in (None, "", [], {})}
            if compact:
                seasons.append(compact)
        if seasons:
            extras["seasons"] = seasons
    extras["available_sections"] = sorted(
        key for key, value in root.items() if value not in (None, "", [], {})
    )
    return rows, kind, extras


def _parse_row_time(row: dict[str, Any]) -> datetime | None:
    raw = str(row.get("start_time") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _select_game_rows(
    rows: list[dict[str, Any]],
    *,
    max_results: int,
    middle_time: str | None,
    after_time: str | None,
    before_time: str | None,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], str, str | None]:
    """Select useful current games before applying the normalized result cap."""
    timed: list[tuple[datetime, dict[str, Any]]] = []
    untimed: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_row_time(row)
        if parsed is None:
            untimed.append(row)
        else:
            timed.append((parsed, row))
    timed.sort(key=lambda item: item[0])

    def parse_anchor(value: str) -> datetime:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )

    if after_time and before_time:
        lower = parse_anchor(after_time)
        upper = parse_anchor(before_time)
        selected = [row for stamp, row in timed if lower <= stamp <= upper]
        selected.extend(untimed)
        return selected[:max_results], "bounded", f"{after_time}/{before_time}"

    if after_time:
        lower = parse_anchor(after_time)
        selected = [row for stamp, row in timed if stamp >= lower]
        selected.extend(untimed)
        return selected[:max_results], "after_time", after_time

    if before_time:
        upper = parse_anchor(before_time)
        selected = [row for stamp, row in reversed(timed) if stamp <= upper]
        selected.extend(untimed)
        return selected[:max_results], "before_time", before_time

    if middle_time:
        anchor = parse_anchor(middle_time)
        selection_mode = "around_middle_time"
        selection_anchor = middle_time
    else:
        anchor = now or datetime.now(timezone.utc)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        anchor = anchor.astimezone(timezone.utc).replace(microsecond=0)
        selection_mode = "around_now"
        selection_anchor = anchor.strftime("%Y-%m-%dT%H:%M:%SZ")

    recent = [row for stamp, row in reversed(timed) if stamp <= anchor]
    upcoming = [row for stamp, row in timed if stamp > anchor]
    recent_quota = (max_results + 1) // 2
    recent_selected = recent[:recent_quota]
    upcoming_selected = upcoming[: max_results - len(recent_selected)]
    selected = [*recent_selected, *upcoming_selected]
    if len(selected) < max_results:
        remaining = max_results - len(selected)
        selected.extend(recent[len(recent_selected) : len(recent_selected) + remaining])
    if len(selected) < max_results:
        selected.extend(untimed[: max_results - len(selected)])
    return selected[:max_results], selection_mode, selection_anchor


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
            "google_sports_url",
        )
        if metadata.get(key) not in (None, "")
    }


def build_speech(
    query: str,
    tab: str | None,
    kind: str,
    results: list[dict[str, Any]],
    *,
    selection_mode: str | None = None,
) -> str:
    label = tab or "game details"
    if not results:
        return f"Google Sports returned no normalized {label} for '{query}'."
    top = results[0]
    if kind == "game":
        suffix = top.get("status_original") or top.get("status") or top.get("start_time") or top.get("date")
        label = (
            "Most recent returned matchup"
            if selection_mode in {"around_now", "around_middle_time", "before_time"}
            else "Top returned matchup"
        )
        speech = f"Found {len(results)} Google Sports game result(s) for '{query}'. {label}: {top.get('title') or 'game'}"
        return speech + (f" ({suffix})." if suffix else ".")
    if kind in {"standing", "ranking"}:
        rank = top.get("rank")
        return f"Found {len(results)} Google Sports {label} result(s) for '{query}'. Top returned entry: {top.get('title') or 'team'}" + (f" at rank {rank}." if rank not in (None, "") else ".")
    return f"Found {len(results)} Google Sports {label} result(s) for '{query}'. Top returned entry: {top.get('title') or kind}."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1
        if not isinstance(input_data, dict):
            raise ValueError("Input must be a JSON object.")

        query = _required_text(input_data.get("query"), "query", 500)
        kgmid = normalize_kgmid(input_data.get("kgmid"))
        if not query and not kgmid:
            raise ValueError("Provide either 'query' or 'kgmid'.")
        entity_type = normalize_entity_type(input_data.get("entity_type"))
        sport, sport_code = normalize_sport(input_data.get("sport"))
        tab, tab_code = normalize_tab(input_data.get("tab"), entity_type, sport_code)
        country = normalize_locale(input_data.get("country"), "country", "us")
        language = normalize_locale(input_data.get("language"), "language", "en")
        middle_time = normalize_utc(input_data.get("middle_time"), "middle_time")
        after_time = normalize_utc(input_data.get("after_time"), "after_time")
        before_time = normalize_utc(input_data.get("before_time"), "before_time")
        if middle_time and (after_time or before_time):
            raise ValueError("'middle_time' cannot be combined with 'after_time' or 'before_time'.")
        if after_time and before_time and after_time > before_time:
            raise ValueError("'after_time' cannot be later than 'before_time'.")
        if (middle_time or after_time or before_time) and (
            entity_type == "game" or tab != "games"
        ):
            raise ValueError(
                "Sports time filters are only valid for league or team games views."
            )
        season_kgmid = normalize_kgmid(input_data.get("season_kgmid"), "season_kgmid")
        max_results = clamp_results_count(
            input_data.get("max_results", DEFAULT_MAX_RESULTS),
            default=DEFAULT_MAX_RESULTS,
            maximum=30,
        )
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {})
        if extra_params is None:
            extra_params = {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        searches_used = 0
        kgmid_source = "explicit" if kgmid else None
        resolver_query = None
        resolved_link_params: dict[str, str] = {}
        resolver_payload: dict[str, Any] | None = None
        if not kgmid:
            resolver_query = query
            resolver_payload = _serpapi_request(
                {
                    "engine": "google",
                    "q": query,
                    "gl": country,
                    "hl": language,
                    "no_cache": "true" if no_cache else "false",
                }
            )
            searches_used += 1
            kgmid, kgmid_source, resolved_link_params = resolve_kgmid(
                resolver_payload,
                query=query,
                entity_type=entity_type,
                sport_code=sport_code,
            )
            if not kgmid:
                raise ValueError(
                    f"Could not resolve a Google Sports {entity_type} ID for '{query}'. "
                    "Try a more specific team, league, or matchup query, or provide kgmid directly."
                )

        params: dict[str, Any] = {
            "engine": "google_sports",
            "kgmid": kgmid,
            "sp": sport_code,
            "type": entity_type,
            "gl": country,
            "hl": language,
            "no_cache": "true" if no_cache else "false",
        }
        for key, value in (
            ("tab", tab_code),
            ("mpd", middle_time),
            ("moa", after_time),
            ("mob", before_time),
            ("season_kgmid", season_kgmid),
        ):
            if value not in (None, ""):
                params[key] = value
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _serpapi_request(params)
        searches_used += 1
        rows, results_kind, extras = extract_results(
            payload, entity_type=entity_type, tab=tab
        )
        provider_results_count = len(rows)
        if results_kind == "standing" and entity_type == "team":
            rows, selected_standing, standings_context = _prioritize_team_standings(
                rows, kgmid
            )
            if selected_standing:
                extras["selected_standing"] = selected_standing
                extras["standings_context"] = standings_context
        selection_mode = None
        selection_anchor = None
        if results_kind == "game" and entity_type != "game":
            results, selection_mode, selection_anchor = _select_game_rows(
                rows,
                max_results=max_results,
                middle_time=middle_time,
                after_time=after_time,
                before_time=before_time,
            )
        else:
            results = rows[:max_results]
        metadata = _search_metadata(payload)
        search_parameters = payload.get("search_parameters")
        search_parameters = search_parameters if isinstance(search_parameters, dict) else {}
        display_query = query or _text(search_parameters.get("kgmid"), 100) or kgmid

        data: dict[str, Any] = {
            "engine": "google_sports",
            "query": display_query,
            "resolver_query": resolver_query,
            "kgmid": kgmid,
            "kgmid_source": kgmid_source,
            "sport": sport,
            "sport_code": sport_code,
            "entity_type": entity_type,
            "tab": tab,
            "tab_code": tab_code,
            "country": country,
            "language": language,
            "middle_time": middle_time,
            "after_time": after_time,
            "before_time": before_time,
            "selection_mode": selection_mode,
            "selection_anchor": selection_anchor,
            "season_kgmid": season_kgmid,
            "max_results": max_results,
            "results_kind": results_kind,
            "results_count": len(results),
            "provider_results_count": provider_results_count,
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "search_id": metadata.get("id"),
            "google_sports_url": metadata.get("google_sports_url"),
            "serpapi_searches_used": searches_used,
            "source": "SerpApi Google Sports",
            **extras,
        }
        if resolved_link_params:
            data["resolver_sport_code"] = resolved_link_params.get("sp")
            data["resolver_entity_type"] = resolved_link_params.get("type")
        if include_raw:
            data["raw"] = payload
            if resolver_payload is not None:
                data["resolver_raw"] = resolver_payload
        data = {
            key: value
            for key, value in data.items()
            if value not in (None, "", [], {}) or key in {"results", "top_results"}
        }
        return_success(
            build_speech(
                display_query or kgmid,
                tab,
                results_kind,
                results,
                selection_mode=selection_mode,
            ),
            data,
        )
        return 0
    except Exception as exc:
        return_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
