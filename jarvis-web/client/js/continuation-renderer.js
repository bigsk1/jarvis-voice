/** Late output stays DOM data; completed local artifacts may use media controls. */
window.continuationRenderer = (() => {
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  };

  function markdownText(value) {
    // Marked's lexer retains entities. Decode one validated entity at a time;
    // this detached textarea never receives tags or any surrounding content.
    // Use only for Markdown, not literal tool filenames/refs or code blocks.
    return String(value || '').replace(/&(?:[a-z][a-z0-9]*|#(?:[0-9]+|x[0-9a-f]+));/gi, entity => {
      const decoder = node('textarea');
      decoder.innerHTML = entity;
      return decoder.value;
    });
  }

  function stashUrl(value, mode) {
    const base = window.mediaResultRenderer.stashUrl(value)?.replace('/api/stash/', '/stash/view/');
    return base ? base + (mode ? `?mode=${mode}` : '') : null;
  }

  function linkUrl(value, mode) {
    const stash = stashUrl(value, mode);
    if (stash) return stash;
    if (typeof value !== 'string' || !/^https?:\/\//i.test(value)) return null;
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
    } catch (_) { return null; }
  }

  function link(parent, label, href, mode) {
    const url = linkUrl(href, mode);
    const el = node(url ? 'a' : 'span');
    if (url) { el.href = url; el.target = '_blank'; el.rel = 'noopener noreferrer'; }
    if (typeof label === 'string') el.textContent = label;
    else tokens(el, label, 0, mode);
    parent.appendChild(el);
  }

  function tokens(parent, items, depth = 0, mode) {
    for (const token of items || []) {
      if (depth > 32) { parent.appendChild(node('span', token.raw || token.text || '')); continue; }
      const children = (el, content = token.tokens) => {
        if (content) tokens(el, content, depth + 1, mode);
        else el.textContent = markdownText(token.text);
        parent.appendChild(el);
      };
      switch (token.type) {
        case 'space': break;
        case 'paragraph': children(node('p')); break;
        case 'heading': children(node(`h${Math.max(1, Math.min(6, token.depth || 1))}`)); break;
        case 'strong': children(node('strong')); break;
        case 'em': children(node('em')); break;
        case 'del': children(node('del')); break;
        case 'blockquote': children(node('blockquote')); break;
        case 'br': parent.appendChild(node('br')); break;
        case 'hr': parent.appendChild(node('hr')); break;
        case 'codespan': parent.appendChild(node('code', token.text)); break;
        case 'escape': parent.appendChild(node('span', token.text)); break;
        case 'code': {
          const pre = node('pre'); pre.appendChild(node('code', token.text)); parent.appendChild(pre); break;
        }
        case 'list': {
          const list = node(token.ordered ? 'ol' : 'ul');
          if (token.ordered && Number.isInteger(token.start)) list.start = token.start;
          for (const item of token.items || []) {
            const li = node('li');
            if (item.task) li.appendChild(node('span', item.checked ? '☑ ' : '☐ '));
            tokens(li, item.tokens, depth + 1, mode); list.appendChild(li);
          }
          parent.appendChild(list); break;
        }
        case 'table': {
          const table = node('table'), head = node('thead'), body = node('tbody');
          const row = (cells, tag) => {
            const tr = node('tr');
            for (const cell of cells) { const td = node(tag); tokens(td, cell.tokens, depth + 1, mode); tr.appendChild(td); }
            return tr;
          };
          head.appendChild(row(token.header, 'th'));
          for (const cells of token.rows) body.appendChild(row(cells, 'td'));
          table.appendChild(head); table.appendChild(body); parent.appendChild(table); break;
        }
        case 'link': link(parent, token.tokens || markdownText(token.text), markdownText(token.href), mode); break;
        // Images remain explicit artifact links; no remote resource is loaded on arrival.
        case 'image': link(parent, markdownText(token.text) || 'Image', markdownText(token.href), mode); break;
        case 'text': children(node('span')); break;
        default: parent.appendChild(node('span', token.raw || token.text || ''));
      }
    }
  }

  function appendArtifacts(parent, data, media, mode) {
    const seen = new Set([...media].map(url => url.replace('/api/stash/', '/stash/view/') + (mode ? `?mode=${mode}` : '')));
    const visited = new WeakSet(), list = node('ul');
    list.className = 'continuation-artifacts';
    function visit(value, label) {
      if (typeof value === 'string') {
        const url = stashUrl(value, mode);
        if (url && !seen.has(url)) {
          seen.add(url);
          const li = node('li'); link(li, label || value, value, mode); list.appendChild(li);
        }
      } else if (value && typeof value === 'object' && !visited.has(value)) {
        visited.add(value);
        const filename = typeof value.filename === 'string' ? value.filename : label;
        for (const child of Object.values(value)) visit(child, filename);
      }
    }
    visit(data);
    if (list.children.length) parent.appendChild(list);
  }

  function browserResearch(data) {
    const entries = Array.isArray(data?.browser_use) ? data.browser_use : [data?.browser_use];
    return entries.find(result => typeof result?.ok === 'boolean'
      && typeof result.speech === 'string'
      && (result.data?.browser_research?.kind === 'browser_research'
        || /^Saved research:\s*stash:\/\/[^\r\n]+/i.test(result.speech))) || null;
  }

  function appendBrowserResearch(message, result, mode) {
    const metadata = result.data?.browser_research || {};
    const partial = result.ok !== true;
    const card = node('section'); card.className = `browser-research-card${partial ? ' is-partial' : ''}`;
    const heading = node('header'); heading.className = 'browser-research-heading';
    const title = node('div');
    title.appendChild(node('span', partial ? 'Partial browser research' : 'Browser research', 'browser-research-title'));
    const provenance = [metadata.provider, metadata.model].filter(value => typeof value === 'string');
    const subtitle = [partial ? 'The requested result could not be fully verified' : '', ...provenance].filter(Boolean);
    if (subtitle.length) title.appendChild(node('small', subtitle.join(' · ')));
    heading.appendChild(title);
    const saved = result.speech.match(/^Saved research:\s*(stash:\/\/[^\r\n]+)/i);
    const archive = stashUrl(metadata.stash_ref || saved?.[1], mode);
    if (archive) {
      const open = node('a', 'Open full research');
      open.className = 'btn-secondary browser-research-open';
      open.href = archive; open.target = '_blank'; open.rel = 'noopener noreferrer';
      heading.appendChild(open);
    }
    card.appendChild(heading);

    let report = String(result.speech || '');
    if (/^Saved research:\s*stash:\/\/[^\r\n]+\r?\n/i.test(report)) {
      report = report.replace(/^Saved research:\s*stash:\/\/[^\r\n]+\r?\n+/i, '');
    }
    const body = node('div'); body.className = 'browser-research-report';
    try {
      if (!window.marked?.lexer) throw new Error('Markdown unavailable');
      tokens(body, window.marked.lexer(report, {gfm: true, breaks: true}), 0, mode);
    } catch (_) { body.textContent = report; body.style.whiteSpace = 'pre-wrap'; }
    card.appendChild(body);

    const sources = (metadata.sources || []).filter(value => linkUrl(value, mode)).slice(0, 60);
    if (sources.length) {
      const details = node('details'); details.className = 'browser-research-sources';
      details.appendChild(node('summary', `Sources visited (${sources.length})`));
      const list = node('ol');
      for (const source of sources) {
        const item = node('li'); link(item, source, source, mode); list.appendChild(item);
      }
      details.appendChild(list); card.appendChild(details);
    }
    const actions = node('div'); actions.className = 'browser-research-actions';
    const copy = node('button', 'Copy report'); copy.type = 'button'; copy.className = 'btn-secondary';
    copy.addEventListener('click', async () => {
      try {
        try {
          if (!window.isSecureContext || !navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
          await navigator.clipboard.writeText(report);
        } catch (_) { Utils.copyTextFallback(report); }
        Utils.toast('Copied browser research as Markdown', 'success', 1800);
      } catch (_) { Utils.toast('Could not copy browser research', 'error', 3000); }
    });
    actions.appendChild(copy); card.appendChild(actions); message.appendChild(card);
  }

  function callbackReport(data) {
    const tool = data?._callback_tool;
    if (typeof tool !== 'string' || !/^[a-z][a-z0-9_]{0,63}$/.test(tool)
        || !Object.prototype.hasOwnProperty.call(data, tool)) return null;
    const result = data[tool];
    return typeof result?.ok === 'boolean' && typeof result.speech === 'string'
      ? {tool, result} : null;
  }

  function appendCallbackReport(message, {tool, result}, mode) {
    const report = result.speech;
    const label = tool.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
    const card = node('section');
    card.className = `browser-research-card callback-report-card${result.ok ? '' : ' is-partial'}`;
    const heading = node('header'); heading.className = 'browser-research-heading';
    heading.appendChild(node('span', `${label} ${result.ok ? 'report' : 'failed'}`, 'browser-research-title'));
    card.appendChild(heading);
    const body = node('div'); body.className = 'browser-research-report';
    try {
      if (!window.marked?.lexer) throw new Error('Markdown unavailable');
      tokens(body, window.marked.lexer(report, {gfm: true, breaks: true}), 0, mode);
    } catch (_) { body.textContent = report; body.style.whiteSpace = 'pre-wrap'; }
    card.appendChild(body);
    const actions = node('div'); actions.className = 'browser-research-actions';
    const copy = node('button', 'Copy report'); copy.type = 'button'; copy.className = 'btn-secondary';
    copy.addEventListener('click', async () => {
      try {
        try {
          if (!window.isSecureContext || !navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
          await navigator.clipboard.writeText(report);
        } catch (_) { Utils.copyTextFallback(report); }
        Utils.toast('Copied background report as Markdown', 'success', 1800);
      } catch (_) { Utils.toast('Could not copy background report', 'error', 3000); }
    });
    actions.appendChild(copy); card.appendChild(actions); message.appendChild(card);
  }

  function append(message, text, data) {
    const mode = ['cloud', 'local'].includes(data?._background_mode) ? data._background_mode : null;
    const research = browserResearch(data);
    if (research) {
      appendBrowserResearch(message, research, mode);
      return;
    }
    const callback = callbackReport(data);
    if (callback) {
      appendCallbackReport(message, callback, mode);
      return;
    }
    const media = window.mediaResultRenderer.append(message, data);
    const bubble = node('div'); bubble.className = 'message-bubble';
    try {
      if (!window.marked?.lexer) throw new Error('Markdown unavailable');
      tokens(bubble, window.marked.lexer(text, {gfm: true, breaks: true}), 0, mode);
    } catch (_) {
      // A missing/failed parser must never fall through to an HTML interpretation.
      bubble.textContent = text; bubble.style.whiteSpace = 'pre-wrap';
    }
    appendArtifacts(bubble, data, media, mode);
    message.appendChild(bubble);
    if (text) {
      const actions = node('div'); actions.className = 'message-response-actions continuation-actions';
      const copy = node('button', 'Copy'); copy.type = 'button';
      copy.className = 'message-response-action-btn message-copy-btn';
      copy.title = 'Copy this background response as Markdown';
      copy.addEventListener('click', async () => {
        try {
          try {
            if (!window.isSecureContext || !navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
            await navigator.clipboard.writeText(text);
          } catch (_) { Utils.copyTextFallback(text); }
          Utils.toast('Copied background response as Markdown', 'success', 1800);
        } catch (_) { Utils.toast('Could not copy the background response', 'error', 3000); }
      });
      actions.appendChild(copy); message.appendChild(actions);
    }
  }
  return { append };
})();
