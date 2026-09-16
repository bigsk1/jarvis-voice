import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizePageLink, isYouTubeVideo, pageLinkToolHints, defaultPageLinkPrompt } from '../core/page-link.js';

test('YouTube video links prefer transcripts across watch, short, live, and share URLs', () => {
  for (const url of [
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=123',
    'https://m.youtube.com/watch?v=dQw4w9WgXcQ',
    'https://music.youtube.com/watch?v=dQw4w9WgXcQ',
    'https://youtu.be/dQw4w9WgXcQ?si=shared',
    'https://www.youtube.com/shorts/dQw4w9WgXcQ',
    'https://www.youtube.com/live/dQw4w9WgXcQ',
    'https://www.youtube.com/embed/dQw4w9WgXcQ',
  ]) {
    const link = normalizePageLink({url, title: 'A video'});
    assert.equal(isYouTubeVideo(link), true, url);
    assert.deepEqual(pageLinkToolHints(link, "What's this video about?"), ['youtube_transcript']);
    assert.match(defaultPageLinkPrompt(link), /transcript/);
    assert.deepEqual(pageLinkToolHints(link, ' /research this'), []);
  }
});

test('channel, search, malformed and lookalike URLs do not select the transcript tool', () => {
  for (const url of [
    'https://youtube.com/', 'https://youtube.com/@creator', 'https://youtube.com/results?search_query=video',
    'https://youtube.com/watch?v=bad', 'https://youtu.be/', 'https://youtube.com.example/watch?v=dQw4w9WgXcQ',
    'https://example.com/youtube.com/watch?v=dQw4w9WgXcQ', 'https://youtube.com@evil.example/watch?v=dQw4w9WgXcQ',
    'file:///youtube.com/watch?v=dQw4w9WgXcQ',
  ]) assert.deepEqual(pageLinkToolHints({url}, 'Summarize this'), [], url);
});

test('page references preserve query and fragment and reject credentials or unshareable URLs', () => {
  const url = 'https://example.test/article?topic=one&version=two#section';
  assert.deepEqual(normalizePageLink({url, title: 'Title\nwith\ttabs'}), {url, title: 'Title with tabs'});
  for (const url of ['about:blank', 'javascript:alert(1)', 'https://user:secret@example.test/', '', 'https://example.test/' + 'a'.repeat(8000)]) {
    assert.throws(() => normalizePageLink({url}));
  }
  assert.equal(normalizePageLink({url, title: 'x'.repeat(800)}).title.length, 500);
});
