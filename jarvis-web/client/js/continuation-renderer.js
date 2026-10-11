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
    const visited = new WeakSet(), artifacts = new Map(), list = node('ul');
    list.className = 'continuation-artifacts';
    const roles = {source_stash_ref:'Source file', input_stash_ref:'Input file',
      receipt_stash_ref:'Task receipt', markdown_stash_ref:'Markdown file', md_stash_ref:'Markdown file',
      json_stash_ref:'JSON file', text_stash_ref:'Text file', output_stash_ref:'Output file',
      archive_stash_ref:'Archive file', editable_project_ref:'Editable project'};
    function add(ref, label, priority) {
      const url = stashUrl(ref, mode);
      if (!url || seen.has(url)) return;
      const previous = artifacts.get(url);
      if (!previous || priority > previous.priority) artifacts.set(url, {ref, label:label || ref, priority});
    }
    function filenameFor(value, ref) {
      const filename = [value.filename, value.name].find(name => typeof name === 'string' && name.trim());
      if (!filename) return null;
      // Some OCR clients describe the input image in filename. A named primary
      // reference must not contradict an explicit output-format alias.
      const formats = {markdown_stash_ref:['md','markdown'], md_stash_ref:['md','markdown'],
        json_stash_ref:['json'], text_stash_ref:['txt','text']};
      const extension = filename.split('.').pop().toLowerCase();
      const url = stashUrl(ref, mode);
      return Object.entries(formats).some(([key, extensions]) => value[key]
        && stashUrl(value[key], mode) === url && !extensions.includes(extension)) ? null : filename;
    }
    function visit(value, key) {
      if (typeof value === 'string') {
        add(value, roles[key], roles[key] ? 1 : 0);
      } else if (value && typeof value === 'object' && !visited.has(value)) {
        visited.add(value);
        // Names belong to this object's own reference, never every descendant.
        // Output descriptors can improve an earlier alias's generic label.
        for (const ref of [value.stash_ref, value.ref]) {
          const filename = filenameFor(value, ref);
          if (filename) add(ref, filename, typeof value.name === 'string' ? 3 : 2);
        }
        if (Array.isArray(value.outputs)) visit(value.outputs);
        for (const [childKey, child] of Object.entries(value)) {
          const prefix = childKey.replace(/_stash_ref$/, '');
          const filename = value[prefix + '_filename'];
          if (typeof child === 'string' && typeof filename === 'string' && filename.trim()) add(child, filename, 3);
          visit(child, childKey);
        }
      }
    }
    visit(data);
    for (const {ref, label} of artifacts.values()) {
      const li = node('li'); link(li, label, ref, mode); list.appendChild(li);
    }
    if (list.children.length) parent.appendChild(list);
  }

  function browserResearch(data) {
    const entries = [data?.browser_use, data?.browser_use_cloud]
      .flatMap(value => Array.isArray(value) ? value : [value]);
    return entries.find(result => typeof result?.ok === 'boolean'
      && typeof result.speech === 'string'
      && (result.data?.browser_research?.kind === 'browser_research'
        || /^Saved research:\s*stash:\/\/[^\r\n]+/i.test(result.speech))) || null;
  }

  function appendBrowserResearch(message, result, mode) {
    const metadata = result.data?.browser_research || {};
    const legacyCloudOutput = metadata.provider === 'Browser Use Cloud'
      && metadata.full_report_imported == null
      && /^Full report:\s*`outputs\/[^`\r\n]+`\s*$/im.test(result.speech);
    const savedSummary = metadata.full_report_imported === false || legacyCloudOutput;
    const partial = result.ok !== true;
    const card = node('section'); card.className = `browser-research-card${partial ? ' is-partial' : ''}`;
    const heading = node('header'); heading.className = 'browser-research-heading';
    const title = node('div');
    title.appendChild(node('span', partial ? 'Partial browser research' : 'Browser research', 'browser-research-title'));
    const provenance = [metadata.provider, metadata.model].filter(value => typeof value === 'string');
    if (metadata.profile_used === true) provenance.push('Saved profile');
    if (metadata.workspace_used === true) provenance.push('Shared workspace');
    const totalCost = metadata.cost_usd?.total;
    if (typeof totalCost === 'string' && /^\d+(?:\.\d+)?$/.test(totalCost)) {
      const amount = Number(totalCost);
      if (Number.isFinite(amount) && amount >= 0 && amount < 1000000) {
        provenance.push(`$${amount.toFixed(2)} total`);
      }
    }
    const subtitle = [partial ? 'The requested result could not be fully verified' : '', ...provenance].filter(Boolean);
    if (subtitle.length) title.appendChild(node('small', subtitle.join(' · ')));
    heading.appendChild(title);
    const saved = result.speech.match(/^Saved research:\s*(stash:\/\/[^\r\n]+)/i);
    const archive = stashUrl(metadata.stash_ref || saved?.[1], mode);
    if (archive) {
      const open = node('a', savedSummary ? 'Open saved summary' : 'Open full research');
      open.className = 'btn-secondary browser-research-open';
      open.href = archive; open.target = '_blank'; open.rel = 'noopener noreferrer';
      heading.appendChild(open);
    }
    card.appendChild(heading);

    let report = String(result.speech || '');
    if (/^Saved research:\s*stash:\/\/[^\r\n]+\r?\n/i.test(report)) {
      report = report.replace(/^Saved research:\s*stash:\/\/[^\r\n]+\r?\n+/i, '');
    }
    if (legacyCloudOutput) {
      report = report.replace(/^Full report:\s*`outputs\/[^`\r\n]+`\s*$/im,
        'The provider workspace file was not imported with this saved answer.');
    }
    const displayReport = Utils.unwrapBrowserResearchMarkdown(report);
    const body = node('div'); body.className = 'browser-research-report';
    try {
      if (!window.marked?.lexer) throw new Error('Markdown unavailable');
      tokens(body, window.marked.lexer(displayReport, {gfm: true, breaks: true}), 0, mode);
    } catch (_) { body.textContent = displayReport; body.style.whiteSpace = 'pre-wrap'; }
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
          await navigator.clipboard.writeText(displayReport);
        } catch (_) { Utils.copyTextFallback(displayReport); }
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
