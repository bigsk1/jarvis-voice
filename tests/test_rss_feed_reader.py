"""Fresh RSS/Atom parsing and public-feed transport without network calls."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest
import requests

from lib.rss_feeds import RSSFeedError, reader

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
FEED_URL = "https://news.example.test/feed.xml"


class Response:
    def __init__(self, body=b"", *, status=200, headers=None):
        self.body = body.encode() if isinstance(body, str) else body
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]


def rss(*entries):
    return ('<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            '<channel><title>Public &amp; Useful</title><link>https://news.example.test/</link>'
            '<description>Current news</description>' + "".join(entries) + '</channel></rss>')


def item(url="https://news.example.test/story", *, date=NOW, extra="", summary="A short summary"):
    published = f"<pubDate>{format_datetime(date)}</pubDate>" if date else ""
    return (f'<item><title>A &amp; B</title><link>{url}</link>{published}'
            f'<description><![CDATA[{summary}]]></description>{extra}</item>')


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    monkeypatch.setattr(reader, "validate_url", lambda url: url)

    def reject(*_args, **_kwargs):
        raise AssertionError("Unexpected feed HTTP request")

    monkeypatch.setattr(reader, "http_request", reject)


def transport(monkeypatch, *responses, route=None):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if route:
            kwargs["route_metadata"].update(route)
        response = responses[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(reader, "http_request", request)
    return calls


def test_rss_full_text_is_plain_bounded_and_no_enclosure_is_downloaded(monkeypatch):
    full = '<p>Complete reporting &amp; facts.</p>' * 350 + '<script>secret_script()</script>'
    extra = (f'<content:encoded><![CDATA[{full}]]></content:encoded>'
             '<category>Technology</category><category>Technology</category>'
             '<enclosure url="https://news.example.test/audio.mp3" type="audio/mpeg" length="123"/>')
    response = Response(rss(item(extra=extra, summary='<b>Summary</b> &amp; details ' * 100)))
    calls = transport(monkeypatch, response)
    result = reader.read_feed(FEED_URL, now=NOW)
    article = result["items"][0]
    assert result["title"] == "Public & Useful" and result["checked_at"] == "2026-10-28T12:00:00Z"
    assert article["title"] == "A & B" and article["categories"] == ["Technology"]
    assert article["published_at"] == "2026-10-28T12:00:00Z"
    assert article["updated_at"] == ""
    assert len(article["content"]) <= 6000 and len(article["summary"]) <= 1200
    assert "<" not in article["content"] and "secret_script" not in article["content"]
    assert article["content_kind"] == "inline" and article["content_truncated"] is True
    assert article["content_chars"] == len(" ".join(["Complete reporting & facts."] * 350))
    assert article["needs_fetch"] is True and len(article["id"]) == 64
    assert len(calls) == 1 and response.closed


def test_atom_updated_only_and_out_of_line_content_need_fetch(monkeypatch):
    body = '''<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://news.example.test/">
      <title>Atom news</title><id>urn:feed:1</id><updated>2026-10-28T12:00:00Z</updated>
      <entry><title>External content</title><id>urn:article:1</id>
      <updated>2026-10-28T10:00:00-02:00</updated><link rel="alternate" href="article?utm_source=feed&amp;id=5#part"/>
      <link rel="enclosure" href="https://news.example.test/media.mp4" type="video/mp4"/>
      <summary>Read more</summary><content type="text/html" src="https://news.example.test/full"/></entry></feed>'''
    calls = transport(monkeypatch, Response(body))
    article = reader.read_feed(FEED_URL, now=NOW)["items"][0]
    assert article["url"] == "https://news.example.test/article?id=5"
    assert article["published_at"] == "" and article["updated_at"] == "2026-10-28T12:00:00Z"
    assert article["needs_fetch"] is True and len(calls) == 1
    assert article["content_kind"] == "out_of_line"
    assert article["content_chars"] == len("Read more") and article["content_truncated"] is False
    assert "https://news.example.test/full" not in article["content"]


@pytest.mark.parametrize("kind", ["rss", "atom"])
def test_long_summary_without_explicit_content_still_requires_article_fetch(monkeypatch, kind):
    teaser = "A long teaser does not establish that this is the complete article. " * 20
    if kind == "rss":
        body = rss(item(summary=teaser))
    else:
        body = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>News</title>'
                '<entry><title>Teaser only</title><id>urn:article:summary</id>'
                '<updated>2026-10-28T12:00:00Z</updated>'
                '<link href="https://news.example.test/teaser"/>'
                f'<summary>{teaser}</summary></entry></feed>')
    transport(monkeypatch, Response(body))
    article = reader.read_feed(FEED_URL, now=NOW)["items"][0]
    assert len(article["content"]) >= 500
    assert article["needs_fetch"] is True
    assert article["content_kind"] == "summary" and article["content_truncated"] is False
    assert article["content_chars"] == len(teaser.strip())


@pytest.mark.parametrize("kind", ["rss", "atom"])
def test_complete_inline_feed_body_preserves_length_and_needs_no_fetch(monkeypatch, kind):
    text = "A complete readable article with café facts. " * 30
    markup = f"<p>{text}</p><style>hidden rule</style>"
    if kind == "rss":
        body = rss(item(extra=f"<content:encoded><![CDATA[{markup}]]></content:encoded>"))
    else:
        body = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>News</title>'
                '<entry><title>Complete article</title><id>urn:article:inline</id>'
                '<updated>2026-10-28T12:00:00Z</updated>'
                '<link href="https://news.example.test/complete"/>'
                f'<content type="html"><![CDATA[{markup}]]></content></entry></feed>')
    transport(monkeypatch, Response(body))
    article = reader.read_feed(FEED_URL, now=NOW)["items"][0]
    assert article["content"] == text.strip()
    assert article["content_chars"] == len(text.strip())
    assert article["content_kind"] == "inline" and article["content_truncated"] is False
    assert article["needs_fetch"] is False


def test_long_summary_reports_original_available_text_length(monkeypatch):
    text = "A teaser with facts but no inline article. " * 200
    transport(monkeypatch, Response(rss(item(summary=f"<p>{text}</p>"))))
    article = reader.read_feed(FEED_URL, now=NOW)["items"][0]
    assert article["content_chars"] == len(text.strip()) > len(article["content"])
    assert article["content_truncated"] is True and article["content_kind"] == "summary"
    assert article["needs_fetch"] is True


def test_plain_text_counter_collapses_whitespace_across_markup_without_full_copy():
    markup = " <p>one\t two</p>\n<div>three &amp; four</div><script>hidden text</script> "
    text, length = reader._text_with_length(markup, 7)
    assert text == "one two" and length == len("one two three & four")
    collector = reader._PlainText(7)
    collector.feed("word " * 10000)
    collector.close()
    assert sum(map(len, collector.parts)) <= 7
    assert collector.characters == 49999


@pytest.mark.parametrize("length,cut", [(6000, False), (6001, True)])
def test_reader_content_limit_marks_only_an_actual_cut(monkeypatch, length, cut):
    body = rss(item(extra=f'<content:encoded><![CDATA[{"x" * length}]]></content:encoded>'))
    transport(monkeypatch, Response(body))
    article = reader.read_feed(FEED_URL, now=NOW)["items"][0]
    assert article["content_chars"] == length
    assert article["content_truncated"] is cut and article["needs_fetch"] is cut
    assert article["content_kind"] == "inline" and len(article["content"]) == 6000


def test_dates_filter_undated_old_and_future_without_invented_dates(monkeypatch):
    body = rss(item(date=NOW - timedelta(hours=49)), item(date=None),
               item(date=NOW + timedelta(minutes=16)),
               item("https://news.example.test/earlier", date=NOW - timedelta(hours=1)),
               item("https://news.example.test/newest", date=NOW))
    transport(monkeypatch, Response(body))
    result = reader.read_feed(FEED_URL, now=NOW, max_age_hours=48, limit=1)
    assert result["total_items"] == 5 and result["undated_skipped"] == 1
    assert [entry["url"] for entry in result["items"]] == ["https://news.example.test/newest"]


def test_article_tracking_variants_have_one_stable_identity(monkeypatch):
    body = rss(item("https://NEWS.example.test:443/story?utm_source=feed&amp;id=5#top"),
               item("https://news.example.test/story?id=5&amp;fbclid=tracking"))
    transport(monkeypatch, Response(body))
    result = reader.read_feed(FEED_URL, now=NOW)
    assert len(result["items"]) == 1
    assert result["items"][0]["url"] == "https://news.example.test/story?id=5"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "http://localhost/story",
                                 "http://127.0.0.1/story", "http://[::1]/story", "http://2130706433/story",
                                 "http://0x7f000001/story", "http://192.168.1.1/story", "http://host.local/story",
                                 "https://user:password@news.example.test/story", "https://news.example.test\\@localhost/story"])
def test_unsafe_article_links_are_skipped(monkeypatch, url):
    transport(monkeypatch, Response(rss(item(url))))
    assert reader.read_feed(FEED_URL, now=NOW)["items"] == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:secret@host.test/feed", "http://localhost/feed",
                                 "http://127.0.0.1/feed", "http://[::ffff:127.0.0.1]/feed", "http://news.example.test:bad/feed"])
def test_unsafe_feed_urls_rejected_before_http(monkeypatch, url):
    with pytest.raises(RSSFeedError):
        reader.read_feed(url, now=NOW)


def test_redirects_are_individually_validated_and_responses_closed(monkeypatch):
    checked = []
    monkeypatch.setattr(reader, "validate_url", lambda url: checked.append(url) or url)
    redirected = Response(status=302, headers={"Location": "/current.xml"})
    final = Response(rss(item()))
    calls = transport(monkeypatch, redirected, final)
    result = reader.read_feed(FEED_URL, now=NOW)
    assert checked == [FEED_URL, "https://news.example.test/current.xml"]
    assert result["url"] == checked[-1] and len(calls) == 2
    assert redirected.closed and final.closed


def test_private_redirect_is_refused_before_another_request(monkeypatch):
    response = Response(status=302, headers={"Location": "http://169.254.169.254/metadata"})
    calls = transport(monkeypatch, response)
    with pytest.raises(RSSFeedError):
        reader.read_feed(FEED_URL, now=NOW)
    assert len(calls) == 1 and response.closed


def test_redirect_chain_is_bounded(monkeypatch):
    responses = [Response(status=302, headers={"Location": "/another.xml"}) for _ in range(4)]
    calls = transport(monkeypatch, *responses)
    with pytest.raises(RSSFeedError, match="redirect limit"):
        reader.read_feed(FEED_URL, now=NOW)
    assert len(calls) == 4 and all(response.closed for response in responses)


def test_every_call_is_fresh_with_no_conditional_cache_headers(monkeypatch):
    calls = transport(monkeypatch, Response(rss(item())), Response(rss(item())))
    reader.read_feed(FEED_URL, now=NOW)
    reader.read_feed(FEED_URL, now=NOW)
    assert len(calls) == 2
    for method, _, options in calls:
        assert method == "GET" and options["allow_redirects"] is False and options["stream"] is True
        assert options["headers"]["Cache-Control"] == "no-cache, max-age=0"
        assert options["headers"]["Pragma"] == "no-cache"
        assert not any(key.lower().startswith("if-") for key in options["headers"])
        assert "verify" not in options and options["deadline"] is not None


@pytest.mark.parametrize("body", ["<html><body>Not a feed</body></html>", "<rss><channel>",
                                  "<rss/>", "<not-feed/>",
                                  '<!DOCTYPE rss [<!ENTITY secret "expanded">]><rss><channel/></rss>'])
def test_html_malformed_xml_and_entity_declarations_rejected(monkeypatch, body):
    response = Response(body)
    transport(monkeypatch, response)
    with pytest.raises(RSSFeedError):
        reader.read_feed(FEED_URL, now=NOW)
    assert response.closed


def test_utf16_entity_declaration_is_rejected(monkeypatch):
    body = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss [<!ENTITY x "boom">]><rss><channel/></rss>'
    transport(monkeypatch, Response(body.encode("utf-16")))
    with pytest.raises(RSSFeedError, match="entities"):
        reader.read_feed(FEED_URL, now=NOW)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_actual_entity_declaration_outside_cdata_and_comments_is_rejected(monkeypatch, encoding):
    body = ('<?xml version="1.0" encoding="' + encoding + '"?>'
            '<!-- a harmless comment containing <!DOCTYPE html> -->'
            '<!DOCTYPE rss [<!ENTITY x "expanded">]>'
            '<rss version="2.0"><channel><title>&x;</title></channel></rss>')
    transport(monkeypatch, Response(body.encode(encoding)))
    with pytest.raises(RSSFeedError, match="entities"):
        reader.read_feed(FEED_URL, now=NOW)


def test_embedded_html_doctype_in_cdata_and_comment_is_not_an_xml_declaration(monkeypatch):
    article = ('<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN">'
               '<html><body><p>Complete article content.</p></body></html>')
    body = rss(item(extra='<content:encoded><![CDATA[' + article + ']]></content:encoded>'))
    body = body.replace('<channel>', '<channel><!-- Documentation: <!DOCTYPE html> and <!ENTITY sample> -->')
    transport(monkeypatch, Response(body))
    result = reader.read_feed(FEED_URL, now=NOW)
    assert result["items"][0]["content"] == "Complete article content."


def test_feed_sized_stream_and_html_content_type_fail_closed(monkeypatch):
    oversized = Response(b"x" * (reader.MAX_FEED_BYTES + 1))
    transport(monkeypatch, oversized)
    with pytest.raises(RSSFeedError, match="2 MiB"):
        reader.read_feed(FEED_URL, now=NOW)
    assert oversized.closed
    html = Response(rss(item()), headers={"Content-Type": "text/html; charset=utf-8"})
    transport(monkeypatch, html)
    with pytest.raises(RSSFeedError, match="HTML page"):
        reader.read_feed(FEED_URL, now=NOW)
    assert html.closed


def test_cache_304_and_error_status_are_not_stale_successes(monkeypatch):
    for status in (304, 404, 500):
        response = Response(status=status)
        transport(monkeypatch, response)
        with pytest.raises(RSSFeedError, match=f"HTTP {status}"):
            reader.read_feed(FEED_URL, now=NOW)
        assert response.closed


def test_network_and_dns_errors_never_echo_secrets(monkeypatch):
    transport(monkeypatch, requests.Timeout("https://user:private-key@proxy.test/?token=secret"))
    with pytest.raises(RSSFeedError) as failed:
        reader.read_feed(FEED_URL, now=NOW)
    assert "private-key" not in str(failed.value) and "secret" not in str(failed.value)

    def refuse(_url):
        raise reader.SecurityError("private hostname with secret")

    monkeypatch.setattr(reader, "validate_url", refuse)
    with pytest.raises(RSSFeedError, match="public-address security check") as failed:
        reader.read_feed(FEED_URL, now=NOW)
    assert "secret" not in str(failed.value)


def test_proxy_metadata_is_credential_free(monkeypatch):
    calls = transport(monkeypatch, Response(rss(item())), route={
        "used": True, "slot": "LOCAL_PROXY2", "policy": "prefer",
        "url": "http://name:secret@proxy.test", "password": "secret", "basis": "http_request"})
    result = reader.read_feed(FEED_URL, now=NOW)
    assert result["proxy"] == {"used": True, "slot": "LOCAL_PROXY2", "policy": "prefer"}
    assert len(calls) == 1


def test_shared_deadline_prevents_fetch_after_expiry_and_closes_late_response(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(reader, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    with pytest.raises(RSSFeedError, match="time limit"):
        reader.read_feed(FEED_URL, now=NOW, deadline=9)

    response = Response(rss(item()))

    def late(_method, _url, **_options):
        clock[0] = 20
        return response

    monkeypatch.setattr(reader, "http_request", late)
    with pytest.raises(RSSFeedError, match="time limit"):
        reader.read_feed(FEED_URL, now=NOW, deadline=12)
    assert response.closed
