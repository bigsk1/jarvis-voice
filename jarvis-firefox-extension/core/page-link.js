/** An explicitly attached page link is a snapshot, never a live tab binding. */
export function normalizePageLink(source) {
  let url;
  try { url = new URL(source?.url); } catch {}
  if (!url || !['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('Choose a page with a shareable HTTP or HTTPS address.');
  }
  if (url.href.length > 8000) throw new Error('This page address is too long to include.');
  return {
    url: url.href,
    title: String(source?.title || url.hostname).replace(/[\r\n\t]+/g, ' ').trim().slice(0, 500),
  };
}

export function isYouTubeVideo(pageLink) {
  let url;
  try { url = new URL(pageLink?.url); } catch { return false; }
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return false;
  const host = url.hostname.toLowerCase();
  let id;
  if (host === 'youtu.be') id = url.pathname.split('/')[1];
  else if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'].includes(host)) {
    if (url.pathname === '/watch') id = url.searchParams.get('v');
    else id = /^\/(?:shorts|live|embed)\/([^/]+)\/?$/.exec(url.pathname)?.[1];
  }
  return typeof id === 'string' && /^[A-Za-z0-9_-]{11}$/.test(id);
}

export function pageLinkToolHints(pageLink, message) {
  return !String(message || '').trimStart().startsWith('/') && isYouTubeVideo(pageLink)
    ? ['youtube_transcript'] : [];
}

export function defaultPageLinkPrompt(pageLink) {
  return isYouTubeVideo(pageLink) ? 'Summarize this video using its transcript.' : 'Tell me about this page.';
}
