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


def test_update_tracking_republishes_changed_incident_only_after_canvas_acknowledgment(setup):
    create, rows, calls, document, config_path, canvas_dir = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    rows[:] = [article(title="API errors", summary="Investigating increased failures.")]
    first_service = create()
    first = first_service.execute(profile="daily_tech")
    assert calls[0][1]["track_updates"] is True
    first_id = first["items"][0]["id"]
    choose(first_service, first)
    with pytest.raises(RSSFeedError, match="could not be verified"):
        first_service.execute("acknowledge", profile="daily_tech", batch_id=first["batch_id"],
                              page_id="page_not_saved")
    assert create().execute(profile="daily_tech")["items"][0]["id"] == first_id
    page_id = publish(canvas_dir, [rows[0]["url"]])
    first_service.execute("acknowledge", profile="daily_tech", batch_id=first["batch_id"], page_id=page_id)
    assert not create().execute(profile="daily_tech")["has_items"]

    rows[0].update(summary="Resolved; normal availability restored.",
                   updated_at=(NOW + timedelta(hours=1)).isoformat())
    updated_service = create(now=NOW + timedelta(hours=1))
    updated = updated_service.execute(profile="daily_tech")
    assert updated["items"][0]["id"] != first_id
    assert updated["items"][0]["url"] == first["items"][0]["url"]
    choose(updated_service, updated)
    assert create(now=NOW + timedelta(hours=1)).execute(profile="daily_tech")["has_items"]
    updated_page = publish(canvas_dir, [rows[0]["url"]], page_id="page_resolved")
    updated_service.execute("acknowledge", profile="daily_tech", batch_id=updated["batch_id"],
                            page_id=updated_page)
    assert not create(now=NOW + timedelta(hours=2)).execute(profile="daily_tech")["has_items"]


def test_update_tracking_does_not_repeat_timestamp_or_metadata_only_changes(setup):
    create, rows, _, document, config_path, canvas_dir = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    service = create()
    batch = service.execute(profile="daily_tech")
    choose(service, batch)
    page_id = publish(canvas_dir, [rows[0]["url"]])
    service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    rows[0].update(published_at=(NOW + timedelta(minutes=1)).isoformat(),
                   updated_at=(NOW + timedelta(hours=1)).isoformat(),
                   categories=["status"], id="a-new-provider-entry-id")
    assert not create(now=NOW + timedelta(hours=1)).execute(profile="daily_tech")["has_items"]


def test_update_tracking_uses_reader_fingerprint_before_service_caps_without_exposing_it(setup):
    create, rows, _, document, config_path, canvas_dir = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    rows[:] = [article(content="x" * 4000 + " Investigating", content_fingerprint="a" * 64)]
    service = create()
    first = service.execute(profile="daily_tech")
    selected = choose(service, first)
    assert "content_fingerprint" not in json.dumps(first)
    assert "content_fingerprint" not in json.dumps(selected)
    assert len(selected["selected_items"][0]["content"]) == 3500
    page_id = publish(canvas_dir, [rows[0]["url"]])
    service.execute("acknowledge", profile="daily_tech", batch_id=first["batch_id"], page_id=page_id)
    rows[0].update(content="x" * 4000 + " Resolved", content_fingerprint="b" * 64)
    updated = create().execute(profile="daily_tech")
    assert updated["has_items"] and updated["items"][0]["id"] != first["items"][0]["id"]
    assert "content_fingerprint" not in json.dumps(choose(create(), updated))


def test_real_feed_tail_update_survives_reader_and_service_display_caps(setup, monkeypatch):
    from rss_feeds import reader as feed_reader

    create, _, _, document, config_path, canvas_dir = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    latest_status = ["Investigating"]

    class FeedResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def iter_content(self, chunk_size):
            content = "x" * 6500 + " " + latest_status[0]
            yield ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Status</title>'
                   f'<entry><id>urn:incident:1</id><title>API outage</title><updated>{NOW.isoformat()}</updated>'
                   '<link href="https://example.org/post/1"/><summary>Incident update.</summary>'
                   f'<content type="html"><![CDATA[<p>{content}</p>]]></content></entry></feed>').encode()

    monkeypatch.setattr(feed_reader, "validate_url", lambda url: url)
    monkeypatch.setattr(feed_reader, "http_request", lambda *_args, **_kwargs: FeedResponse())
    service = create(reader=feed_reader.read_feed)
    first = service.execute(profile="daily_tech")
    first_selection = choose(service, first)
    assert len(first_selection["selected_items"][0]["content"]) == 3500
    page_id = publish(canvas_dir, ["https://example.org/post/1"])
    service.execute("acknowledge", profile="daily_tech", batch_id=first["batch_id"], page_id=page_id)
    assert not service.execute(profile="daily_tech")["has_items"]
    latest_status[0] = "Resolved"
    updated = service.execute(profile="daily_tech")
    assert updated["has_items"] and updated["items"][0]["id"] != first["items"][0]["id"]
    updated_selection = choose(service, updated)
    assert updated_selection["selected_items"][0]["content"] == first_selection["selected_items"][0]["content"]
    assert "content_fingerprint" not in json.dumps(updated_selection)


def test_ordinary_profiles_keep_url_deduplication_when_content_changes(setup):
    create, rows, calls, _, _, canvas_dir = setup
    service = create()
    batch = service.execute(profile="daily_tech")
    choose(service, batch)
    page_id = publish(canvas_dir, [rows[0]["url"]])
    service.execute("acknowledge", profile="daily_tech", batch_id=batch["batch_id"], page_id=page_id)
    rows[0].update(title="An updated release", summary="Now with different content.",
                   content_fingerprint="b" * 64, updated_at=(NOW + timedelta(hours=1)).isoformat())
    assert not create().execute(profile="daily_tech")["has_items"]
    assert all(not kwargs.get("track_updates", False) for _, kwargs in calls)


def test_update_history_is_independent_for_profiles_reading_the_same_feed(setup):
    create, rows, _, document, config_path, canvas_dir = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    document["profiles"]["status_watch"] = {**document["profiles"]["daily_tech"],
                                             "canvas_title": "Digests/Status Watch"}
    config_path.write_text(yaml.safe_dump(document))
    service = create()
    first = service.execute(profile="daily_tech")
    choose(service, first)
    page_id = publish(canvas_dir, [rows[0]["url"]])
    service.execute("acknowledge", profile="daily_tech", batch_id=first["batch_id"], page_id=page_id)
    assert not create().execute(profile="daily_tech")["has_items"]
    other = create().execute(profile="status_watch")
    assert other["has_items"] and other["items"][0]["url"] == rows[0]["url"]
    rows[0]["summary"] = "A material new update."
    assert create().execute(profile="daily_tech")["has_items"]
    assert create().execute(profile="status_watch")["has_items"]


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


def test_parallel_digest_cannot_claim_another_revision_of_an_incident_being_prepared(setup):
    create, rows, _, document, config_path, _ = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    first = create().execute(profile="daily_tech")
    choose(create(), first)
    rows[0]["summary"] = "Resolved while the earlier digest was being prepared."
    second = create().execute(profile="daily_tech")
    assert second["items"][0]["id"] != first["items"][0]["id"]
    with pytest.raises(RSSFeedError, match="Another RSS digest"):
        choose(create(), second)
    assert choose(create(now=NOW + timedelta(minutes=16)), second)["has_selection"]


@pytest.mark.parametrize("stale_action", ["resolve_selection", "acknowledge"])
def test_published_revision_supersedes_earlier_staged_incident_batches(setup, stale_action):
    create, rows, _, document, config_path, canvas_dir = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    rows[0]["summary"] = "Investigating errors."
    earlier = create().execute(profile="daily_tech")
    if stale_action == "acknowledge":
        choose(create(), earlier)

    # The earlier publication claim has expired, but its batch is still valid.
    later_time = NOW + timedelta(minutes=16)
    rows[0]["summary"] = "Resolved; all services recovered."
    newer_service = create(now=later_time)
    newer = newer_service.execute(profile="daily_tech")
    choose(newer_service, newer)
    page_id = publish(canvas_dir, [rows[0]["url"]], page_id="page_resolved")
    newer_service.execute("acknowledge", profile="daily_tech", batch_id=newer["batch_id"], page_id=page_id)

    stale_service = create(now=later_time + timedelta(minutes=1))
    with pytest.raises(RSSFeedError, match="superseded"):
        if stale_action == "resolve_selection":
            choose(stale_service, earlier)
        else:
            # Even a freshly saved page with the right URL cannot revive stale evidence.
            stale_page = publish(canvas_dir, [rows[0]["url"]], page_id="page_stale")
            stale_service.execute("acknowledge", profile="daily_tech", batch_id=earlier["batch_id"],
                                  page_id=stale_page)
    assert not stale_service.execute(profile="daily_tech")["has_items"]


def test_publishing_an_incident_revision_keeps_unrelated_pending_batch_usable(setup):
    create, rows, _, document, config_path, canvas_dir = setup
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    create().execute(profile="daily_tech")
    rows[:] = [article(2)]
    unrelated = create().execute(profile="daily_tech")
    rows[:] = [article(summary="Resolved; all services recovered.")]
    service = create()
    revised = service.execute(profile="daily_tech")
    choose(service, revised)
    page_id = publish(canvas_dir, [rows[0]["url"]])
    service.execute("acknowledge", profile="daily_tech", batch_id=revised["batch_id"], page_id=page_id)
    selected = choose(create(), unrelated)
    assert selected["has_selection"] and selected["urls"] == [article(2)["url"]]


def test_ordinary_profile_pending_batches_keep_url_based_selection_after_publication(setup):
    create, rows, _, _, _, canvas_dir = setup
    earlier = create().execute(profile="daily_tech")
    rows[0]["summary"] = "Changed reporting at the same article URL."
    service = create()
    newer = service.execute(profile="daily_tech")
    choose(service, newer)
    page_id = publish(canvas_dir, [rows[0]["url"]])
    service.execute("acknowledge", profile="daily_tech", batch_id=newer["batch_id"], page_id=page_id)
    assert choose(create(), earlier)["has_selection"] is False


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


@pytest.mark.parametrize("value", [None, "true", "false", 0, 1, [], {}])
def test_update_tracking_policy_requires_a_boolean(setup, value):
    _, _, _, document, config_path, _ = setup
    document["profiles"]["daily_tech"]["track_updates"] = value
    config_path.write_text(yaml.safe_dump(document))
    with pytest.raises(RSSFeedError, match="track_updates"):
        load_profiles(config_path)


def test_explicitly_disabled_update_tracking_preserves_existing_batch_policy(setup):
    create, _, _, document, config_path, _ = setup
    original_config = load_profiles(config_path)["daily_tech"]
    batch = create().execute(profile="daily_tech")
    document["profiles"]["daily_tech"]["track_updates"] = False
    config_path.write_text(yaml.safe_dump(document))
    assert load_profiles(config_path)["daily_tech"] == original_config
    assert choose(create(), batch)["has_selection"]


def test_enabling_update_tracking_requires_a_new_batch(setup):
    create, _, _, document, config_path, _ = setup
    batch = create().execute(profile="daily_tech")
    document["profiles"]["daily_tech"]["track_updates"] = True
    config_path.write_text(yaml.safe_dump(document))
    with pytest.raises(RSSFeedError, match="profile changed"):
        choose(create(), batch)


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
