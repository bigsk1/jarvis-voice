"""Publication, freshness, and profile boundaries using isolated feed fixtures."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import rss_feeds.service as service_module
import yaml
from config_loader import config_scope
from rss_feeds import RSSFeedError
from rss_feeds.config import load_profiles
from rss_feeds.service import RSSFeedService

NOW = datetime(2026, 10, 27, 16, tzinfo=timezone.utc)


def article(number=1, **extra):
    return {"id": f"provider-{number}", "title": f"Useful application {number}",
            "url": f"https://example.org/post/{number}", "summary": "A useful release.",
            "content": "", "published_at": NOW.isoformat(), "updated_at": "",
            "categories": ["engineering"], "needs_fetch": True, **extra}


@pytest.fixture
def setup(tmp_path):
    config_path = tmp_path / "rss.yaml"
    document = {"v": 1, "profiles": {"daily_tech": {
        "canvas_title": "Digests/Daily Tech", "interests": ["Developer tools"],
        "feeds": [{"name": "Primary", "url": "https://example.org/feed.xml"}],
    }}}
    config_path.write_text(yaml.safe_dump(document))
    canvas_dir = tmp_path / "canvas"
    canvas_dir.mkdir()
    rows = [article()]
    calls = []

    def reader(url, **kwargs):
        calls.append((url, kwargs))
        return {"url": url, "items": rows[:], "proxy": {"policy": "prefer", "used": False}}

    def service(**kwargs):
        return RSSFeedService(config_path=config_path, state_dir=tmp_path / "state",
                              canvas_dir=canvas_dir, now=kwargs.pop("now", NOW),
                              reader=kwargs.pop("reader", reader), **kwargs)

    return service, rows, calls, document, config_path, canvas_dir


def choose(service, batch, ids=None):
    ids = [batch["items"][0]["id"]] if ids is None else ids
    return service.execute("resolve_selection", profile="daily_tech", batch_id=batch["batch_id"],
                           text=json.dumps({"ids": ids}))


def publish(directory: Path, urls, *, title="Digests/Daily Tech", page_id="page_fixture"):
    body = "# Daily Tech\n" + "\n".join(f"[Story]({url})" for url in urls)
    (directory / f"{page_id}.json").write_text(json.dumps({"id": page_id, "title": title, "content": body}))
    return page_id


def test_direct_feed_read_needs_no_profile_and_never_tracks_history(tmp_path):
    def reader(url, **kwargs):
        return {"url": url, "items": [article()]}
    service = RSSFeedService(config_path=tmp_path / "missing.yaml", state_dir=tmp_path / "state",
                             now=NOW, reader=reader)
    result = service.execute(url="https://example.org/feed.xml")
    assert result["items"][0]["url"] == article()["url"]
    assert result["fresh_request"] and not (tmp_path / "state").exists()


def test_every_profile_read_fetches_again_and_unpublished_items_remain_eligible(setup):
    create, _, calls, _, _, _ = setup
    first = create().execute(profile="daily_tech")
    second = create().execute(profile="daily_tech")
    assert len(calls) == 2
    assert first["items"] == second["items"]
    assert first["batch_id"] != second["batch_id"]
    assert "content" not in first["items"][0]


def test_acknowledgment_needs_saved_canvas_then_prevents_next_day_repeats(setup):
    create, rows, _, _, _, canvas_dir = setup
    service = create()
    batch = service.execute(profile="daily_tech")
    selection = choose(service, batch)
    with pytest.raises(RSSFeedError, match="could not be verified"):
        service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id="page_missing")
    assert create().execute(profile="daily_tech")["has_items"]
    page_id = publish(canvas_dir, selection["urls"])
    result = service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    assert result["published_count"] == 1
    again = service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    assert again["already_acknowledged"]
    rows.append(article(2))
    tomorrow = create(now=NOW + timedelta(days=1)).execute(profile="daily_tech")
    assert [row["url"] for row in tomorrow["items"]] == [article(2)["url"]]


def test_profile_receipts_are_shared_across_modes_like_canvas(setup):
    create, _, _, _, _, canvas_dir = setup
    with config_scope("cloud"):
        service = create()
        batch = service.execute(profile="daily_tech")
        selection = choose(service, batch)
        page_id = publish(canvas_dir, selection["urls"])
        service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    with config_scope("local"):
        assert not create().execute(profile="daily_tech")["has_items"]


def test_tracking_parameters_and_cross_feed_duplicates_collapse(setup):
    create, rows, _, document, config_path, _ = setup
    rows[:] = [article(url="https://example.org/post/1?utm_source=one#section"), article()]
    document["profiles"]["daily_tech"]["feeds"].append({"name": "Other", "url": "https://other.example/feed"})
    config_path.write_text(yaml.safe_dump(document))
    result = create().execute(profile="daily_tech")
    assert len(result["items"]) == 1
    assert result["items"][0]["url"] == article()["url"]


@pytest.mark.parametrize("text", ['{"ids":["invented"]}', '{"ids":[],"url":"https://invented.example/"}',
                                  '```json\n{"ids":[]}\n```', '{"ids":[1]}', '[]'])
def test_editorial_selection_cannot_invent_a_story_or_url(setup, text):
    create, _, _, _, _, _ = setup
    service = create()
    batch = service.execute(profile="daily_tech")
    with pytest.raises(RSSFeedError):
        service.execute("resolve_selection", profile="daily_tech", batch_id=batch["batch_id"], text=text)


def test_selection_limits_and_duplicate_ids_are_enforced(setup):
    create, _, _, _, _, _ = setup
    service = create()
    batch = service.execute(profile="daily_tech")
    with pytest.raises(RSSFeedError, match="duplicate"):
        choose(service, batch, [batch["items"][0]["id"]] * 2)
    with pytest.raises(RSSFeedError, match="limit"):
        choose(service, batch, [batch["items"][0]["id"]] * 9)


def test_batch_expiry_and_changed_policy_require_new_fetch(setup):
    create, _, _, document, config_path, _ = setup
    batch = create().execute(profile="daily_tech")
    with pytest.raises(RSSFeedError, match="expired"):
        choose(create(now=NOW + timedelta(hours=3)), batch)
    document["profiles"]["daily_tech"]["exclude"] = ["Changed policy"]
    config_path.write_text(yaml.safe_dump(document))
    with pytest.raises(RSSFeedError, match="profile changed"):
        choose(create(), batch)


def test_ack_only_marks_selected_stories_actually_present_in_digest(setup):
    create, rows, _, _, _, canvas_dir = setup
    rows.append(article(2))
    service = create()
    batch = service.execute(profile="daily_tech")
    choose(service, batch, [row["id"] for row in batch["items"]])
    page_id = publish(canvas_dir, [article()["url"]])
    result = service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    assert result["published_count"] == 1 and result["omitted_selected"] == 1
    assert [row["url"] for row in create().execute(profile="daily_tech")["items"]] == [article(2)["url"]]


def test_unselected_candidates_stay_eligible_for_a_later_digest(setup):
    create, rows, _, _, _, canvas_dir = setup
    rows.append(article(2))
    service = create()
    batch = service.execute(profile="daily_tech")
    choose(service, batch)
    page_id = publish(canvas_dir, [article()["url"]])
    service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    assert [row["url"] for row in create().execute(profile="daily_tech")["items"]] == [article(2)["url"]]


def test_parallel_batches_cannot_claim_the_same_unpublished_stories(setup):
    create, _, _, _, _, _ = setup
    service = create()
    first = service.execute(profile="daily_tech")
    second = service.execute(profile="daily_tech")
    assert choose(service, first)["has_selection"]
    with pytest.raises(RSSFeedError, match="Another RSS digest"):
        choose(service, second)
    assert choose(create(now=NOW + timedelta(minutes=16)), second)["has_selection"]


@pytest.mark.parametrize("wrong", ["title", "links"])
def test_wrong_canvas_page_cannot_advance_history(setup, wrong):
    create, _, _, _, _, canvas_dir = setup
    service = create()
    batch = service.execute(profile="daily_tech")
    choose(service, batch)
    page_id = publish(canvas_dir, ["https://unrelated.example/"] if wrong == "links" else [article()["url"]],
                      title="Other page" if wrong == "title" else "Digests/Daily Tech")
    with pytest.raises(RSSFeedError):
        service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    assert create().execute(profile="daily_tech")["has_items"]


def test_failed_sources_do_not_replay_saved_candidate_content(setup):
    create, _, _, _, _, _ = setup
    create().execute(profile="daily_tech")

    def failed(*args, **kwargs):
        raise RSSFeedError("Feed unavailable.")

    with pytest.raises(RSSFeedError, match="No RSS feeds"):
        create(reader=failed).execute(profile="daily_tech")


def test_partial_coverage_is_explicit_and_keeps_successful_sources(setup):
    create, _, _, document, config_path, _ = setup
    document["profiles"]["daily_tech"]["feeds"].append({"name": "Unavailable", "url": "https://other.example/feed"})
    config_path.write_text(yaml.safe_dump(document))

    def partial(url, **kwargs):
        if "other.example" in url:
            raise RSSFeedError("Feed unavailable.")
        return {"url": url, "items": [article()]}

    result = create(reader=partial).execute(profile="daily_tech")
    assert result["has_items"] and "Unavailable" in result["coverage_note"]
    assert "request failed or timed out" in result["coverage_note"]
    assert result["failed_feeds"] == [{"name": "Unavailable", "reason": "request failed or timed out"}]
    selected = choose(create(), result)
    assert selected["failed_feeds"] == result["failed_feeds"]
    assert selected["coverage_note"] == result["coverage_note"]


def test_failure_reasons_are_useful_without_echoing_exception_secrets(setup):
    create, _, _, document, config_path, _ = setup
    document["profiles"]["daily_tech"]["feeds"].append({"name": "Protected", "url": "https://other.example/feed"})
    config_path.write_text(yaml.safe_dump(document))

    def partial(url, **kwargs):
        if "other.example" in url:
            raise RSSFeedError("Feed returned HTTP 403 https://secret-user:secret-value@proxy.test/")
        return {"url": url, "items": [article()]}

    batch = create(reader=partial).execute(profile="daily_tech")
    assert batch["failed_feeds"] == [{"name": "Protected", "reason": "HTTP 403"}]
    assert "Protected (HTTP 403)" in batch["coverage_note"]
    assert "secret" not in json.dumps({key: batch[key] for key in ("failed_feeds", "coverage_note")})


def test_profile_listing_includes_enabled_feed_configuration(setup):
    create, _, _, _, _, _ = setup
    result = create().execute("list_profiles")
    assert result["action"] == "list_profiles"
    profile = result["profiles"][0]
    assert profile["interests"] == ["Developer tools"]
    assert profile["feeds"] == [{"name": "Primary", "url": "https://example.org/feed.xml", "priority": "normal"}]


def test_profile_listing_can_focus_one_group_for_complete_feed_details(setup):
    create, _, _, document, config_path, _ = setup
    document["profiles"]["release_watch"] = {
        "canvas_title": "Digests/Releases", "feeds": [
            {"name": "Releases", "url": "https://example.org/releases.atom"},
        ],
    }
    config_path.write_text(yaml.safe_dump(document))
    result = create().execute("list_profiles", profile="release_watch")
    assert len(result["profiles"]) == 1
    assert result["profiles"][0]["profile"] == "release_watch"
    assert result["profiles"][0]["feeds"][0]["url"] == "https://example.org/releases.atom"
    with pytest.raises(RSSFeedError, match="not configured"):
        create().execute("list_profiles", profile="missing")


def test_large_profile_budgets_all_worker_waves_and_starts_high_priority_first(setup, monkeypatch):
    create, _, calls, document, config_path, _ = setup
    profile = document["profiles"]["daily_tech"]
    profile["feeds"] = [{"name": f"Feed {i}", "url": f"https://feed{i}.example/rss", "priority": "normal"} for i in range(16)]
    profile["feeds"][-1]["priority"] = "high"
    config_path.write_text(yaml.safe_dump(document))

    class InlinePool:
        def __init__(self, max_workers):
            assert max_workers == 4
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def map(self, function, values):
            return map(function, values)

    monkeypatch.setattr(service_module, "ThreadPoolExecutor", InlinePool)
    monkeypatch.setattr(service_module, "time", SimpleNamespace(monotonic=lambda: 100.0))
    create().execute(profile="daily_tech")
    assert calls[0][0] == "https://feed15.example/rss"
    assert len(calls) == 16
    assert all(call[1]["deadline"] == 110.0 for call in calls)


def test_manual_profile_reads_cannot_evict_a_digest_before_publication(setup):
    create, _, _, _, _, canvas_dir = setup
    batch = create().execute(profile="daily_tech")
    # The first model call also needs the batch before a selection is claimed.
    for _ in range(6):
        create().execute(profile="daily_tech")
    selected = choose(create(), batch)
    for _ in range(6):
        create().execute(profile="daily_tech")
    page_id = publish(canvas_dir, selected["urls"])
    ack = create().execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    assert ack["published_count"] == 1


@pytest.mark.parametrize("length", [3501, 6000])
def test_collection_content_limits_mark_incomplete_text_and_request_article(setup, length):
    create, rows, _, _, _, _ = setup
    rows[:] = [article(content="x" * length, content_chars=length, content_truncated=False,
                      content_kind="inline", needs_fetch=False)]
    batch = create().execute(profile="daily_tech")
    selection = choose(create(), batch)
    item = selection["selected_items"][0]
    assert len(item["content"]) == 3500
    assert item["content_chars"] == length
    assert item["content_truncated"] is True
    assert selection["urls"] == [rows[0]["url"]]


def test_selection_budget_reclassifies_previously_complete_feed_bodies_for_crawling(setup):
    create, rows, _, _, _, _ = setup
    rows[:] = [article(i, content="界" * 3500, content_chars=3500, content_truncated=False,
                      content_kind="inline", needs_fetch=False) for i in range(8)]
    batch = create().execute(profile="daily_tech")
    selection = choose(create(), batch, [row["id"] for row in batch["items"]])
    assert len(json.dumps(selection["selected_items"], ensure_ascii=True, indent=2)) <= 40000
    assert len(selection["urls"]) == 8
    assert all(item["content_truncated"] and item["content_chars"] == 3500
               and len(item["content"]) < 3500 for item in selection["selected_items"])


def test_candidate_and_selection_prompts_have_bounded_complete_json(setup):
    create, rows, _, document, config_path, _ = setup
    document["profiles"]["daily_tech"]["feeds"] *= 3
    config_path.write_text(yaml.safe_dump(document))
    rows[:] = [article(number, summary="x" * 1200, content="y" * 6000,
                       url=f"https://example.org/{number}?long=" + "z" * 2000) for number in range(30)]
    service = create()
    batch = service.execute(profile="daily_tech")
    assert len(json.dumps(batch["items"], ensure_ascii=True, indent=2)) < 50_000
    selected = choose(service, batch, [row["id"] for row in batch["items"][:8]])
    assert len(json.dumps(selected["selected_items"], ensure_ascii=True, indent=2)) < 50_000
    assert all(row["url"].endswith("z" * 2000) for row in selected["selected_items"])


def test_corrupt_state_fails_closed_without_resetting_publication_history(setup):
    create, _, _, _, _, _ = setup
    service = create()
    service.execute(profile="daily_tech")
    path = service.state_dir / "daily_tech.json"
    path.write_text('{"broken": true}')
    with pytest.raises(RSSFeedError, match="was not reset"):
        create().execute(profile="daily_tech")
    assert path.read_text() == '{"broken": true}'


def test_concurrent_acknowledgments_are_idempotent(setup):
    create, _, _, _, _, canvas_dir = setup
    service = create()
    batch = service.execute(profile="daily_tech")
    selection = choose(service, batch)
    page_id = publish(canvas_dir, selection["urls"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create().execute("acknowledge", profile="daily_tech",
                                batch_id=batch["batch_id"], page_id=page_id), range(2)))
    assert sum(bool(result.get("already_acknowledged")) for result in results) == 1


@pytest.mark.parametrize("link", ["{url}", "[Source]({url})", "[Source](<{url}>)"])
def test_publication_verification_keeps_parentheses_inside_article_urls(setup, link):
    create, rows, _, _, _, canvas_dir = setup
    url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
    rows[:] = [article(url=url)]
    service = create()
    batch = service.execute(profile="daily_tech")
    choose(service, batch)
    page_id = "page_parentheses"
    (canvas_dir / f"{page_id}.json").write_text(json.dumps({
        "id": page_id, "title": "Digests/Daily Tech", "content": link.format(url=url),
    }))
    result = service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"],
                             page_id=page_id)
    assert result["published_count"] == 1
    assert not create().execute(profile="daily_tech")["has_items"]


@pytest.mark.parametrize("profile", ["../outside", "/tmp/escape", "", "a.b"])
def test_profile_names_cannot_select_arbitrary_files(setup, profile):
    create, _, _, _, _, _ = setup
    with pytest.raises(RSSFeedError):
        create().execute(profile=profile)


def test_config_examples_are_valid_and_feed_limits_are_checked(setup):
    root = Path(__file__).resolve().parents[1]
    assert "daily_tech" in load_profiles(root / "config/rss_feeds.yaml.example")
    _, _, _, document, config_path, _ = setup
    document["profiles"]["daily_tech"]["max_stories"] = True
    config_path.write_text(yaml.safe_dump(document))
    with pytest.raises(RSSFeedError, match="max_stories"):
        load_profiles(config_path)


@pytest.mark.parametrize("field,value", [("priority", []), ("enabled", "false")])
def test_malformed_feed_policy_has_a_useful_configuration_error(setup, field, value):
    _, _, _, document, config_path, _ = setup
    document["profiles"]["daily_tech"]["feeds"][0][field] = value
    config_path.write_text(yaml.safe_dump(document))
    with pytest.raises(RSSFeedError, match=field):
        load_profiles(config_path)


@pytest.mark.parametrize("field,value", [("seen", {"story": "yesterday"}),
                                        ("batches", {"batch": {"created_at": "yesterday"}})])
def test_malformed_publication_receipts_are_not_silently_discarded(setup, field, value):
    create, _, _, _, _, _ = setup
    service = create()
    service.execute(profile="daily_tech")
    path = service.state_dir / "daily_tech.json"
    state = json.loads(path.read_text())
    state[field] = value
    original = json.dumps(state)
    path.write_text(original)
    with pytest.raises(RSSFeedError, match="was not reset"):
        create().execute(profile="daily_tech")
    assert path.read_text() == original
