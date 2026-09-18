/** Media from completed tool results. DOM-only, same-origin stash, no turn state. */
window.mediaResultRenderer = (() => {
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const string = value => typeof value === 'string' ? value : '';
  const formats = {
    jpg: 'image', jpeg: 'image', png: 'image', gif: 'image', webp: 'image', avif: 'image', bmp: 'image', ico: 'image',
    mp4: 'video', webm: 'video', mov: 'video', m4v: 'video', mkv: 'video', avi: 'video',
    mp3: 'audio', wav: 'audio', flac: 'audio', ogg: 'audio', opus: 'audio', aac: 'audio', m4a: 'audio',
  };
  const mimeKinds = {
    'image/jpeg': 'image', 'image/png': 'image', 'image/gif': 'image', 'image/webp': 'image',
    'image/avif': 'image', 'image/bmp': 'image', 'image/x-icon': 'image',
    'video/mp4': 'video', 'video/webm': 'video', 'video/quicktime': 'video',
    'video/x-matroska': 'video', 'video/x-msvideo': 'video',
    'audio/mpeg': 'audio', 'audio/wav': 'audio', 'audio/x-wav': 'audio', 'audio/flac': 'audio',
    'audio/ogg': 'audio', 'audio/opus': 'audio', 'audio/aac': 'audio', 'audio/mp4': 'audio',
  };

  function stashUrl(value) {
    if (typeof value !== 'string') return null;
    const match = /^stash:\/\/([^/\r\n]+)\/([^/\r\n]+)$/.exec(value);
    if (!match || match[0] !== value || match.slice(1).some(part =>
      part === '.' || part === '..' || /[\\\x00-\x1f\x7f]/.test(part))) return null;
    const encode = part => encodeURIComponent(part).replace(/'/g, '%27');
    try { return `/api/stash/${encode(match[1])}/${encode(match[2])}`; }
    catch (_) { return null; }
  }

  function append(parent, data) {
    const seen = new Set();
    const mode = ['cloud', 'local'].includes(data?._background_mode) ? data._background_mode : null;
    // Inspect only successful tool envelopes, never prose, input arguments,
    // arbitrary nested references, remote URLs or filesystem paths.
    for (const [tool, entries] of Object.entries(data || {})) {
      if (tool.startsWith('_')) continue;
      for (const result of (Array.isArray(entries) ? entries : [entries])) {
        if (!result || result.ok !== true || result.cancelled || result.status === 'accepted'
            || result.result_kind === 'background_admission') continue;
        const body = result.data || result;
        const saved = body.saved || {};
        const base = stashUrl(saved.stash_ref || body.stash_ref);
        const filename = string(saved.filename || body.filename);
        const mime = string(body.mime_type || saved.mime_type).toLowerCase().split(';')[0].trim();
        const extension = (filename.split('.').pop() || string(body.target_format)).toLowerCase();
        const kind = mime ? (Object.hasOwn(mimeKinds, mime) ? mimeKinds[mime] : null)
          : (Object.hasOwn(formats, extension) ? formats[extension] : null);
        if (!base || !kind || seen.has(base) || seen.size >= 16) continue;
        seen.add(base);
        const url = base + (mode ? `?mode=${mode}` : '');
        const label = string(body.title || body.prompt || body.subject || filename) || `${kind} result`;
        const title = label.length > 180 ? label.slice(0, 180) + '…' : label;
        const card = node('section', undefined, 'continuation-media converted-media-container');
        const frame = node(kind === 'image' ? 'button' : 'div', undefined, `message-${kind}`);
        const media = node(kind === 'image' ? 'img' : kind);
        if (kind === 'image') {
          frame.type = 'button';
          frame.setAttribute('aria-label', `Expand ${title}`);
          media.alt = title; media.loading = 'lazy';
          const overlay = node('div', undefined, 'image-overlay');
          overlay.appendChild(node('span', '🔍 Click to expand'));
          frame.appendChild(media); frame.appendChild(overlay);
          frame.addEventListener('click', () => window.showImageLightbox(url));
        } else {
          const heading = node('div', undefined, `${kind}-header`);
          heading.appendChild(node('span', kind === 'video' ? '🎬' : '🎵', `${kind}-icon`));
          heading.appendChild(node('span', title, `${kind}-title`));
          media.className = `${kind}-player`;
          media.controls = true; media.autoplay = false; media.preload = 'metadata';
          if (kind === 'video') media.playsInline = true;
          media.setAttribute('aria-label', title);
          frame.appendChild(heading); frame.appendChild(media);
        }
        media.src = url;
        const unavailable = node('p', 'Preview unavailable. Open or download the saved file below.', 'continuation-media-note');
        unavailable.hidden = true;
        media.addEventListener('error', () => { media.hidden = true; unavailable.hidden = false; });
        card.appendChild(frame); card.appendChild(unavailable);
        const actions = node('div', undefined, 'convert-actions continuation-media-actions');
        actions.appendChild(node('span', filename || title, 'convert-info'));
        for (const [text, download] of [['Open', false], ['Download', true]]) {
          const link = node('a', text, 'convert-download-btn');
          link.href = url;
          if (download) link.download = filename || 'download';
          else { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
          actions.appendChild(link);
        }
        card.appendChild(actions);
        const provenance = [string(body.provider), string(body.model)].filter(Boolean).map(value => value.slice(0, 120));
        if (provenance.length) card.appendChild(node('p', provenance.join(' · '), 'continuation-media-note'));
        parent.appendChild(card);
      }
    }
    return seen;
  }
  return { append, stashUrl };
})();
