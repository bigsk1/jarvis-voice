#!/usr/bin/env python3
"""Regression coverage for the SerpApi Google Sports tool."""

import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import serpapi_client
from serpapi_google_sports import (
    GOOGLE_SPORTS_TIMEOUT,
    _prioritize_team_standings,
    _select_game_rows,
    _serpapi_request,
    extract_results,
    main,
    normalize_sport,
    resolve_kgmid,
)


def games_payload():
    return {
        "search_metadata": {
            "id": "sports-123",
            "status": "Success",
            "cached": True,
            "google_sports_url": "https://www.google.com/search?kgmid=/m/0jmk7",
        },
        "search_parameters": {
            "engine": "google_sports",
            "kgmid": "/m/0jmk7",
            "sp": "bs",
            "type": "team",
            "tab": "gm",
        },
        "team_results": {
            "game_groups": [
                {
                    "title": "Regular season",
                    "games": [
                        {
                            "teams": [
                                {
                                    "name": "Los Angeles Lakers",
                                    "short_code": "LAL",
                                    "kgmid": "/m/0jmk7",
                                    "thumbnail": "https://images.example/lakers.png",
                                    "score": 112,
                                    "win": True,
                                },
                                {
                                    "name": "Boston Celtics",
                                    "short_code": "BOS",
                                    "kgmid": "/m/0jm3v",
                                    "score": 108,
                                },
                            ],
                            "league": {"name": "NBA", "kgmid": "/m/05jvx"},
                            "venue": {"name": "Example Arena", "location": "Los Angeles"},
                            "status": "finished",
                            "status_original": "Final",
                            "kgmid": "/g/11sports_game",
                            "serpapi_link": "https://serpapi.com/search.json?engine=google_sports&kgmid=%2Fg%2F11sports_game&sp=bs&type=game",
                            "start_time": "2026-08-04T02:00:00Z",
                            "highlights": [
                                {
                                    "title": "Game recap",
                                    "link": "https://video.example/recap",
                                    "duration": "4:30",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


def standings_payload():
    return {
        "team_results": {
            "standings": {
                "groups": [
                    {
                        "title": "Western Conference",
                        "teams": [
                            {
                                "rank": 1,
                                "name": "Los Angeles Lakers",
                                "kgmid": "/m/0jmk7",
                                "thumbnail": "https://images.example/lakers.png",
                                "highlighted": True,
                                "stats": [
                                    {"title": "Wins", "short_title": "W", "value": "54"},
                                    {"title": "Losses", "short_title": "L", "value": "28"},
                                ],
                            }
                        ],
                    }
                ],
                "seasons": [
                    {
                        "name": "2025-26",
                        "kgmid": "/g/11season",
                        "selected": True,
                        "league": {"name": "NBA", "kgmid": "/m/05jvx"},
                    }
                ],
            }
        }
    }


def game_detail_payload():
    return {
        "game_results": {
            "info": {
                "teams": [
                    {
                        "name": "Los Angeles Dodgers",
                        "short_code": "LAD",
                        "score": 6,
                        "season_record": {"wins": 69, "losses": 46},
                        "linescore": [
                            {"title": "Runs", "short_title": "R", "score": "6"},
                            {"title": "Hits", "short_title": "H", "score": "14"},
                        ],
                    },
                    {
                        "name": "Chicago Cubs",
                        "short_code": "CHC",
                        "score": 7,
                        "win": True,
                    },
                ],
                "status": "upcoming",
                "start_time": "2026-08-05T18:20:00Z",
                "kgmid": "/g/11sports_game",
                "watch": {
                    "groups": [
                        {
                            "title": "TV options",
                            "sources": [
                                {"title": "FOX"},
                                {
                                    "title": "Fubo",
                                    "subtitle": "Subscription",
                                    "link": "https://watch.example/fubo",
                                },
                            ],
                        }
                    ]
                },
                "more_info": [
                    {
                        "title": "More game info at mlb.com",
                        "link": "https://www.mlb.com/gameday/824646/live",
                    }
                ],
            },
            "box_scores": {
                "teams": [
                    {
                        "team_index": 0,
                        "groups": [
                            {
                                "title": "Batting",
                                "player_groups": [
                                    {
                                        "type": "Player",
                                        "players": [
                                            {
                                                "name": "Shohei Ohtani",
                                                "position": "DH",
                                                "kgmid": "/m/0nb273g",
                                                "stats": [
                                                    {
                                                        "type": "batter_hits",
                                                        "title": "Hits",
                                                        "short_title": "H",
                                                        "value": "3",
                                                    },
                                                    {
                                                        "type": "rbi",
                                                        "title": "Runs batted in",
                                                        "short_title": "RBI",
                                                        "value": "3",
                                                    },
                                                    {
                                                        "type": "home_runs",
                                                        "title": "Home runs",
                                                        "short_title": "HR",
                                                        "value": "2",
                                                    },
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "title": "Pitching",
                                "player_groups": [
                                    {
                                        "type": "Player",
                                        "players": [
                                            {
                                                "name": "Example Pitcher",
                                                "stats": [
                                                    {
                                                        "type": "innings_pitched",
                                                        "short_title": "IP",
                                                        "value": "6.0",
                                                    },
                                                    {
                                                        "type": "strikeouts",
                                                        "short_title": "SO",
                                                        "value": "8",
                                                    },
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ]
            },
        }
    }


def run_main(arguments, responses):
    stdout = StringIO()
    argv = ["serpapi_google_sports.py", json.dumps(arguments)]
    if not isinstance(responses, list):
        responses = [responses]
    with patch("serpapi_google_sports.load_config"), patch(
        "serpapi_google_sports._serpapi_request", side_effect=responses
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_query_mode_resolves_team_kgmid_then_returns_games():
    resolver = {
        "knowledge_graph": {
            "title": "Los Angeles Lakers",
            "kgmid": "/m/0jmk7",
        }
    }
    exit_code, result, request = run_main(
        {
            "query": "Los Angeles Lakers",
            "sport": "basketball",
            "entity_type": "team",
            "tab": "games",
            "max_results": 5,
        },
        [resolver, games_payload()],
    )

    assert exit_code == 0
    assert request.call_count == 2
    assert request.call_args_list[0].args[0]["engine"] == "google"
    sports_params = request.call_args_list[1].args[0]
    assert sports_params == {
        "engine": "google_sports",
        "kgmid": "/m/0jmk7",
        "sp": "bs",
        "type": "team",
        "gl": "us",
        "hl": "en",
        "no_cache": "false",
        "tab": "gm",
    }
    data = result["data"]
    assert data["kgmid_source"] == "google_knowledge_graph"
    assert data["serpapi_searches_used"] == 2
    assert data["results_count"] == 1
    assert data["results"][0]["title"] == "Los Angeles Lakers vs Boston Celtics"
    assert data["results"][0]["teams"][0]["score"] == 112
    assert data["results"][0]["url"] == "https://www.google.com/search?kgmid=%2Fg%2F11sports_game"
    assert data["results"][0]["serpapi_link"].startswith("https://serpapi.com/")
    assert data["results"][0]["highlights"][0]["url"] == "https://video.example/recap"
    assert "Most recent returned matchup" in result["speech"]


def test_default_game_window_keeps_recent_and_upcoming_games_near_now():
    dates = [
        "2026-07-29T02:10:00Z",
        "2026-07-30T02:10:00Z",
        "2026-07-31T02:10:00Z",
        "2026-08-01T02:10:00Z",
        "2026-08-02T01:10:00Z",
        "2026-08-02T23:20:00Z",
        "2026-08-04T00:05:00Z",
        "2026-08-05T00:05:00Z",
        "2026-08-05T18:20:00Z",
        "2026-08-08T01:40:00Z",
        "2026-08-09T00:10:00Z",
        "2026-08-09T20:10:00Z",
        "2026-08-11T02:10:00Z",
        "2026-08-12T02:10:00Z",
    ]
    rows = [
        {"title": f"Game {index}", "start_time": start_time}
        for index, start_time in enumerate(dates, 1)
    ]

    selected, mode, anchor = _select_game_rows(
        rows,
        max_results=12,
        middle_time=None,
        after_time=None,
        before_time=None,
        now=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
    )

    selected_dates = [row["start_time"] for row in selected]
    assert mode == "around_now"
    assert anchor == "2026-08-05T12:00:00Z"
    assert selected_dates[:6] == [
        "2026-08-05T00:05:00Z",
        "2026-08-04T00:05:00Z",
        "2026-08-02T23:20:00Z",
        "2026-08-02T01:10:00Z",
        "2026-08-01T02:10:00Z",
        "2026-07-31T02:10:00Z",
    ]
    assert selected_dates[6:] == [
        "2026-08-05T18:20:00Z",
        "2026-08-08T01:40:00Z",
        "2026-08-09T00:10:00Z",
        "2026-08-09T20:10:00Z",
        "2026-08-11T02:10:00Z",
        "2026-08-12T02:10:00Z",
    ]


def test_before_and_after_game_windows_keep_expected_direction():
    rows = [
        {"title": "Old", "start_time": "2026-08-01T00:00:00Z"},
        {"title": "Recent", "start_time": "2026-08-04T00:00:00Z"},
        {"title": "Next", "start_time": "2026-08-06T00:00:00Z"},
        {"title": "Later", "start_time": "2026-08-08T00:00:00Z"},
    ]

    before, before_mode, _ = _select_game_rows(
        rows,
        max_results=2,
        middle_time=None,
        after_time=None,
        before_time="2026-08-05T00:00:00Z",
    )
    after, after_mode, _ = _select_game_rows(
        rows,
        max_results=2,
        middle_time=None,
        after_time="2026-08-05T00:00:00Z",
        before_time=None,
    )

    assert before_mode == "before_time"
    assert [row["title"] for row in before] == ["Recent", "Old"]
    assert after_mode == "after_time"
    assert [row["title"] for row in after] == ["Next", "Later"]


def test_game_query_prefers_spotlight_google_sports_link():
    payload = {
        "sports_results": {
            "game_spotlight": {
                "kgmid": "/g/11spotlight",
                "google_sports_serpapi_link": (
                    "https://serpapi.com/search.json?engine=google_sports"
                    "&kgmid=%2Fg%2F11spotlight&sp=bs&type=game"
                ),
            }
        }
    }
    kgmid, source, params = resolve_kgmid(
        payload,
        query="Lakers vs Celtics",
        entity_type="game",
        sport_code="bs",
    )
    assert kgmid == "/g/11spotlight"
    assert source == "google_sports_game"
    assert params["sp"] == "bs"


def test_direct_kgmid_uses_one_request_and_time_filters():
    exit_code, result, request = run_main(
        {
            "kgmid": "/m/0jmk7",
            "sport": "basketball",
            "entity_type": "team",
            "after_time": "2026-08-01T00:00:00Z",
            "before_time": "2026-08-31T23:59:59Z",
        },
        games_payload(),
    )
    assert exit_code == 0
    assert request.call_count == 1
    params = request.call_args.args[0]
    assert params["tab"] == "gm"
    assert params["moa"] == "2026-08-01T00:00:00Z"
    assert params["mob"] == "2026-08-31T23:59:59Z"
    assert result["data"]["kgmid_source"] == "explicit"
    assert result["data"]["serpapi_searches_used"] == 1


def test_standings_normalization_preserves_stats_and_season_followup_ids():
    rows, kind, extras = extract_results(
        standings_payload(), entity_type="team", tab="standings"
    )
    assert kind == "standing"
    assert rows[0]["rank"] == 1
    assert rows[0]["group"] == "Western Conference"
    assert rows[0]["stats"][0] == {
        "title": "Wins",
        "short_title": "W",
        "value": "54",
    }
    assert extras["seasons"][0]["kgmid"] == "/g/11season"
    assert extras["seasons"][0]["league"]["kgmid"] == "/m/05jvx"


def test_team_standings_prioritize_selected_division_before_bounding():
    rows = [
        {
            "kind": "standing",
            "position": 1,
            "group": "American League",
            "division": "AL East",
            "name": "Rays",
            "kgmid": "/m/rays",
        },
        {
            "kind": "standing",
            "position": 26,
            "group": "National League",
            "division": "NL West",
            "name": "Dodgers",
            "kgmid": "/m/dodgers",
            "highlighted": True,
        },
        {
            "kind": "standing",
            "position": 27,
            "group": "National League",
            "division": "NL West",
            "name": "Padres",
            "kgmid": "/m/padres",
        },
    ]

    prioritized, selected, context = _prioritize_team_standings(
        rows, "/m/dodgers"
    )

    assert selected == rows[1]
    assert context == [rows[1], rows[2]]
    assert prioritized == [rows[1], rows[2], rows[0]]


def test_team_standings_main_exposes_selected_context_outside_original_bound():
    payload = standings_payload()
    western = payload["team_results"]["standings"]["groups"][0]
    western["teams"].insert(
        0,
        {
            "rank": 1,
            "name": "Oklahoma City Thunder",
            "kgmid": "/m/thunder",
            "stats": [{"title": "Wins", "short_title": "W", "value": "60"}],
        },
    )
    exit_code, result, _request = run_main(
        {
            "kgmid": "/m/0jmk7",
            "sport": "basketball",
            "entity_type": "team",
            "tab": "standings",
            "max_results": 1,
        },
        payload,
    )

    assert exit_code == 0
    data = result["data"]
    assert data["provider_results_count"] == 2
    assert data["results_count"] == 1
    assert data["results"][0]["name"] == "Los Angeles Lakers"
    assert data["selected_standing"]["kgmid"] == "/m/0jmk7"
    assert [row["name"] for row in data["standings_context"]] == [
        "Los Angeles Lakers",
        "Oklahoma City Thunder",
    ]


def test_jarvis_sport_names_translate_to_serpapi_codes():
    assert normalize_sport("football") == ("american_football", "af")
    assert normalize_sport("american_football") == ("american_football", "af")
    assert normalize_sport("soccer") == ("football", "ft")
    assert normalize_sport("association football") == ("football", "ft")

    for jarvis_sport, expected_code in (("football", "af"), ("soccer", "ft")):
        exit_code, _result, request = run_main(
            {
                "kgmid": "/m/0jmk7",
                "sport": jarvis_sport,
                "entity_type": "team",
                "tab": "games",
                "max_results": 1,
            },
            games_payload(),
        )
        assert exit_code == 0
        assert request.call_args.args[0]["sp"] == expected_code


def test_game_detail_normalizes_watch_linescore_and_box_score_highlights():
    rows, kind, extras = extract_results(
        game_detail_payload(), entity_type="game", tab=None
    )

    assert kind == "game"
    assert rows[0]["teams"][0]["season_record"] == {"wins": 69, "losses": 46}
    assert rows[0]["teams"][0]["linescore"][1] == {
        "title": "Hits",
        "short_title": "H",
        "score": "14",
    }
    assert rows[0]["watch"]["groups"][0]["sources"][0]["title"] == "FOX"
    assert rows[0]["more_info"][0]["url"].startswith("https://www.mlb.com/")
    assert extras["watch"] == rows[0]["watch"]
    assert extras["box_score"]["teams"][0]["team"]["short_code"] == "LAD"
    batting = extras["box_score"]["teams"][0]["groups"][0]
    assert batting["player_groups"][0]["players"][0]["stats"][2] == {
        "type": "home_runs",
        "title": "Home runs",
        "short_title": "HR",
        "value": "2",
    }
    assert extras["box_score_highlights"][0]["name"] == "Shohei Ohtani"
    assert extras["box_score_highlights"][0]["stats"][2]["short_title"] == "HR"


def test_league_stats_preserve_team_as_structured_identity():
    payload = {
        "league_results": {
            "stats": {
                "groups": [
                    {
                        "title": "Points per game",
                        "players": [
                            {
                                "rank": 1,
                                "name": "Luka Doncic",
                                "kgmid": "/m/0135s_cz",
                                "team": {
                                    "name": "Lakers",
                                    "kgmid": "/m/0jmk7",
                                    "thumbnail": "https://images.example/lakers.png",
                                },
                                "stats": [{"title": "PPG", "value": "33.5"}],
                            }
                        ],
                    }
                ]
            }
        }
    }
    rows, kind, _extras = extract_results(payload, entity_type="league", tab="stats")
    assert kind == "stat"
    assert rows[0]["group"] == "Points per game"
    assert rows[0]["team"] == {
        "name": "Lakers",
        "kgmid": "/m/0jmk7",
        "thumbnail": "https://images.example/lakers.png",
    }
    assert rows[0]["stats"] == [{"title": "PPG", "value": "33.5"}]


def test_validation_rejects_incompatible_game_tab_and_time_window():
    exit_code, result, request = run_main(
        {
            "kgmid": "/g/11game",
            "sport": "basketball",
            "entity_type": "game",
            "tab": "standings",
        },
        {},
    )
    assert exit_code == 1
    assert "Game entities only support" in result["error"]
    request.assert_not_called()

    exit_code, result, request = run_main(
        {
            "kgmid": "/m/0jmk7",
            "sport": "basketball",
            "entity_type": "team",
            "middle_time": "2026-08-05T12:00:00Z",
            "after_time": "2026-08-01T00:00:00Z",
        },
        {},
    )
    assert exit_code == 1
    assert "cannot be combined" in result["error"]
    request.assert_not_called()

    exit_code, result, request = run_main(
        {
            "kgmid": "/m/0jmk7",
            "sport": "basketball",
            "entity_type": "team",
            "tab": "standings",
            "after_time": "2026-08-01T00:00:00Z",
        },
        {},
    )
    assert exit_code == 1
    assert "only valid for league or team games" in result["error"]
    request.assert_not_called()


def test_unresolved_query_explains_how_to_retry():
    exit_code, result, request = run_main(
        {
            "query": "ambiguous club",
            "sport": "football",
            "entity_type": "team",
        },
        {},
    )
    assert exit_code == 1
    assert request.call_count == 1
    assert "more specific" in result["error"]
    assert "kgmid" in result["error"]


def test_shared_request_is_proxy_capable_but_manifest_defaults_off():
    with patch("serpapi_google_sports.request_serpapi", return_value={}) as request:
        _serpapi_request({"engine": "google_sports", "kgmid": "/m/0jmk7"})
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_SPORTS_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_sports.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]


def test_status_diagnostics_include_resolver_only_when_needed():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_sports", {"query": "Los Angeles Lakers"}
    ) == ("google", "google_sports")
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_sports", {"kgmid": "/m/0jmk7"}
    ) == ("google_sports",)
