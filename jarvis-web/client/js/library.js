/* Source library: plain DOM rendering, explicit writes and durable indexing. */
(() => {
  const byId = id => document.getElementById(id);
  const params = new URLSearchParams(window.location.search);
  let mode = params.get('mode') === 'local' ? 'local' : 'cloud';
  let generation = 0;
  let detailGeneration = 0;
  let activeQuery = '';
  let activeSource = null;
  let activeSourceTitle = '';
  let nextOffset = null;
  let passagePane = null;
  let renderedPane = null;
  let originalPane = null;
  let pageObjectUrl = null;
  let pdfRequestGeneration = 0;
  let selectedFiles = [];
  let uploading = false;
  let workerHealthGeneration = 0;
  byId('mode').value = mode;

  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text != null) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  }
  function status(text) { byId('status').textContent = text; }
  function button(label, action) {
    const result = node('button', label);
    result.type = 'button';
    result.addEventListener('click', () => action().catch(error => status(error.message)));
    return result;
  }
  async function api(path = '', options = {}, query = {}) {
    const search = new URLSearchParams({mode, ...query});
    const response = await Utils.auth.fetch(`/api/library${path}?${search}`, options);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Library request failed.');
    return data;
  }
  function sourceUrl(source, passage) {
    const query = new URLSearchParams({mode: source.mode, source: source.source_id});
    if (passage) query.set('passage', passage);
    return `/library?${query}`;
  }
  function closeSource(restoreFocus = false) {
    ++detailGeneration;
    ++pdfRequestGeneration;
    if (pageObjectUrl) URL.revokeObjectURL(pageObjectUrl);
    pageObjectUrl = null;
    passagePane = null; renderedPane = null; originalPane = null;
    byId('detail').hidden = true;
    byId('detail').replaceChildren();
    window.history.replaceState(null, '', `/library?mode=${mode}`);
    if (restoreFocus) byId(activeQuery ? 'query' : 'browse').focus();
  }
  function sourceMeta(source) {
    const size = source.size_bytes == null ? '' : ` · ${source.size_bytes < 1024 * 1024
      ? `${Math.ceil(source.size_bytes / 1024)} KB` : `${(source.size_bytes / (1024 * 1024)).toFixed(1)} MB`}`;
    const captureDate = /^Firefox page capture at (\d{4}-\d{2}-\d{2})T/.exec(source.origin || '');
    const captured = captureDate ? ` · Captured ${captureDate[1]}` : '';
    const date = source.created_at ? ` · Saved ${source.created_at.slice(0, 10)}` : '';
    return `${source.filename || 'Source'}${size}${captured}${date} · ${indexLabel(source)}`;
  }
  function sourceMetaNode(source) {
    const meta = node('p', sourceMeta(source), 'meta');
    meta.dataset.libraryIndex = `${source.mode}/${source.source_id}`;
    meta.dataset.indexPending = source.index_job_status === 'pending' ? 'true' : 'false';
    return meta;
  }
  function renderSearchContext() {
    const context = byId('search-context');
    context.replaceChildren();
    const hasContext = Boolean(activeQuery || activeSource);
    context.hidden = !hasContext;
    byId('clear-search').hidden = !hasContext && !byId('query').value.trim();
    if (!hasContext) return;
    context.append(node('strong', activeQuery ? `Results for “${activeQuery}”` : 'Choose a query'));
    if (activeSource) {
      context.append(node('span', `within ${activeSourceTitle || 'this source'}`));
      context.append(button('Search all sources', async () => {
        activeSource = null; activeSourceTitle = '';
        if (byId('query').value.trim()) await search(); else await browse();
      }));
    }
  }
  function managementButtons(source) {
    const rename = button('Rename', async () => {
      const title = window.prompt(`Rename “${source.title}”`, source.title);
      if (title == null || title.trim() === source.title) return;
      const updated = await api(`/${source.source_id}`, {
        method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: title.trim()})
      }, {mode: source.mode});
      if (activeSource === source.source_id) activeSourceTitle = updated.source.title;
      closeSource();
      if (activeQuery) await search(); else await browse();
      status('Source renamed. Meaning indexing is queued; citations still point to the same original.');
    });
    const downloadButton = button('Download original', () => download(source));
    const removeButton = button('Delete source', async () => {
      if (!window.confirm(`Permanently delete “${source.title}” and its passages from the ${source.mode} library?`)) return;
      await api(`/${source.source_id}`, {method: 'DELETE'}, {mode: source.mode});
      closeSource();
      await browse();
      status('Source deleted.');
    });
    removeButton.className = 'danger';
    return [rename, downloadButton, removeButton];
  }
  function sourceActions(source, {reader = false} = {}) {
    const actions = node('div', null, 'actions');
    if (!reader) actions.append(button('Open source', () => showSource(source.source_id)));
    actions.append(button('Search within', async () => {
      activeSource = source.source_id; activeSourceTitle = source.title;
      renderSearchContext();
      if (byId('query').value.trim()) await search(); else byId('query').focus();
    }));
    if (source.index_status !== 'ready') {
      const indexAction = button(source.index_job_status === 'error' ? 'Retry meaning index'
        : source.index_job_status === 'pending' ? 'Meaning index queued' : 'Queue meaning index',
      () => indexSource(source.source_id, source.mode));
      indexAction.dataset.libraryIndexAction = `${source.mode}/${source.source_id}`;
      indexAction.disabled = source.index_job_status === 'pending';
      actions.append(indexAction);
    }
    if (reader) {
      actions.append(...managementButtons(source));
    } else {
      const manage = node('details', null, 'manage-menu');
      manage.append(node('summary', 'Manage source'));
      const options = node('div', null, 'manage-options');
      options.append(...managementButtons(source));
      manage.append(options);
      actions.append(manage);
    }
    return actions;
  }
  function sourceCard(source, {searchResult = false} = {}) {
    const card = node('article', null, searchResult ? 'source-group' : 'source-card');
    const link = node('a', source.title);
    link.href = sourceUrl(source);
    link.addEventListener('click', event => { event.preventDefault(); showSource(source.source_id).catch(error => status(error.message)); });
    const heading = node('h2'); heading.append(link);
    card.append(heading, sourceMetaNode(source));
    card.append(sourceActions(source));
    return card;
  }
  function readerHeader(source) {
    const header = node('div', null, 'reader-header');
    const titleRow = node('div', null, 'reader-title-row');
    titleRow.append(node('h2', source.title), button('Close source', async () => closeSource(true)));
    header.append(titleRow, sourceMetaNode(source), sourceActions(source, {reader: true}));
    return header;
  }
  function indexLabel(source) {
    const state = source.index_job_status === 'pending' ? ' · meaning index queued/running'
      : source.index_job_status === 'error' ? ' · meaning index needs retry' : '';
    return `${source.passage_count} passages · ${source.indexed_passages} indexed by meaning${state} · ${source.mode}`;
  }
  function updateIndexLabels(source) {
    document.querySelectorAll('[data-library-index]').forEach(element => {
      if (element.dataset.libraryIndex === `${source.mode}/${source.source_id}`) {
        element.textContent = sourceMeta(source);
        element.dataset.indexPending = source.index_job_status === 'pending' ? 'true' : 'false';
      }
    });
    document.querySelectorAll('[data-library-index-action]').forEach(element => {
      if (element.dataset.libraryIndexAction !== `${source.mode}/${source.source_id}`) return;
      if (source.index_status === 'ready') { element.remove(); return; }
      element.disabled = source.index_job_status === 'pending';
      element.textContent = source.index_job_status === 'error' ? 'Retry meaning index'
        : source.index_job_status === 'pending' ? 'Meaning index queued' : 'Queue meaning index';
    });
  }
  async function refreshPendingStatuses() {
    const ids = [...new Set([...document.querySelectorAll('[data-library-index]')]
      .filter(element => element.dataset.indexPending === 'true'
        && element.dataset.libraryIndex.startsWith(`${mode}/`))
      .map(element => element.dataset.libraryIndex.slice(mode.length + 1)))].slice(0, 100);
    if (!ids.length) return;
    const data = await api('/status', {}, {ids: ids.join(',')});
    data.sources.forEach(updateIndexLabels);
  }
  async function refreshWorkerHealth() {
    const selectedMode = mode;
    const token = ++workerHealthGeneration;
    const warning = byId('worker-health');
    let message = '';
    try {
      const data = await api('/worker', {}, {mode: selectedMode});
      if (!data.running) {
        message = data.worker_mode === 'external'
          ? `The ${selectedMode} library worker is not running. Queued inbox imports and meaning indexing are paused. Check docker compose ps and logs for jarvis-library-worker.`
          : `The ${selectedMode} library worker is not running. Queued inbox imports and meaning indexing are paused. Restart Jarvis Web and check its logs.`;
      }
    } catch (_error) {
      message = `The ${selectedMode} library worker could not be checked. Queued work may be paused; check the library and Web logs.`;
    }
    if (token !== workerHealthGeneration || selectedMode !== mode) return;
    if (warning.textContent !== message) warning.textContent = message;
    warning.hidden = !message;
  }
  async function browse(append = false, resetDetail = true) {
    if (!append) {
      activeQuery = ''; activeSource = null; activeSourceTitle = '';
      byId('query').value = '';
      renderSearchContext();
      if (resetDetail) closeSource();
    }
    const token = ++generation;
    const data = await api('', {}, {offset: append ? nextOffset || 0 : 0});
    if (token !== generation) return false;
    if (!append) byId('results').replaceChildren();
    data.sources.forEach(source => byId('results').append(sourceCard(source)));
    nextOffset = data.next_offset;
    byId('more').hidden = nextOffset == null;
    if (!data.total) byId('results').append(node('p', `No saved sources in ${mode}. Import a document to start.`, 'hint'));
    status(data.total ? `${data.total} saved sources in ${mode}.` : `No saved sources in ${mode}.`);
    return true;
  }
  function matchingRanges(text, query) {
    const literal = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const find = pattern => [...text.matchAll(new RegExp(pattern, 'giu'))]
      .map(match => ({start: match.index, end: match.index + match[0].length}));
    const phrase = query.trim();
    if (!phrase) return [];
    const exact = find(literal(phrase));
    if (exact.length) return exact;
    const words = [...new Set(phrase.match(/[\p{L}\p{N}_]+/gu) || [])];
    const common = new Set('a an and are as at be by can did do does for from how i in is it me my of on or that the this to was what when where which who with you'.split(' '));
    const terms = words.filter(word => !common.has(word.toLowerCase()));
    return words.length ? find((terms.length ? terms : words).slice(0, 40)
      .sort((a, b) => b.length - a.length).map(literal).join('|')) : [];
  }
  function passageText(text, ranges, excerpt) {
    const first = ranges[0];
    let start = excerpt && first ? Math.max(0, first.start - 80) : 0;
    let end = excerpt ? Math.min(text.length, Math.max(start + 440, first?.end || 0)) : text.length;
    // A preview boundary must not cut a Unicode surrogate pair in half.
    if (start && /[\uDC00-\uDFFF]/.test(text[start])) --start;
    if (end < text.length && /[\uDC00-\uDFFF]/.test(text[end])) ++end;
    const pre = node('pre', null, 'passage');
    if (start) pre.append(node('span', '… '));
    let cursor = start;
    for (const range of ranges) {
      if (range.start < start || range.end > end) continue;
      pre.append(node('span', text.slice(cursor, range.start)),
        node('mark', text.slice(range.start, range.end), 'library-match'));
      cursor = range.end;
    }
    pre.append(node('span', text.slice(cursor, end)));
    if (end < text.length) pre.append(node('span', ' …'));
    return pre;
  }
  function passageCard(passage, {query = '', excerpt = false} = {}) {
    const card = node('article', null, 'passage-card');
    const link = node('a', passage.citation);
    link.href = sourceUrl(passage, passage.number);
    link.addEventListener('click', event => { event.preventDefault(); showSource(passage.source_id, passage.number, false, query).catch(error => status(error.message)); });
    const reasons = passage.match_reasons || (passage.matched_by || []).map(value => value === 'keyword' ? 'text' : value);
    // The server, not a client regex, decides whether a search hit is literal.
    const ranges = excerpt && reasons.length && !reasons.includes('text') ? [] : matchingRanges(passage.text, query);
    card.append(link, passageText(passage.text, ranges, excerpt));
    if (excerpt) {
      if (query && !ranges.length) {
        const explanation = reasons.includes('title')
          ? 'The title matches; this passage is shown for source context.'
          : reasons.includes('semantic')
            ? 'Related by meaning. No literal query words occur in this passage.'
            : 'Keyword retrieval found this passage; inspect the source for context.';
        card.append(node('p', explanation, 'hint'));
      }
      card.append(button('View full passage', () => showSource(passage.source_id, passage.number, false, query)));
    }
    const reasonLabels = {text: 'Text match', title: 'Title match', semantic: 'Related by meaning'};
    if (reasons.length) {
      const badges = node('div', null, 'match-reasons');
      reasons.forEach(reason => {
        const badge = node('span', reasonLabels[reason] || reason, `match-reason ${reason}`);
        badges.append(badge);
      });
      card.append(badges);
    }
    return card;
  }
  function renderSearchResults(data, query) {
    const results = byId('results');
    results.replaceChildren();
    if (!data.passages.length) {
      results.append(node('p', `No passages found for “${query}”. Try fewer terms, search all sources, or inspect an original.`, 'hint'));
      return;
    }
    const metadata = new Map((data.sources || []).map(source => [source.source_id, source]));
    const groups = new Map();
    data.passages.forEach(passage => {
      if (!groups.has(passage.source_id)) groups.set(passage.source_id, []);
      groups.get(passage.source_id).push(passage);
    });
    groups.forEach((passages, sourceId) => {
      const source = metadata.get(sourceId) || passages[0];
      const card = sourceCard(source, {searchResult: true});
      card.append(node('h3', `${passages.length} relevant passage${passages.length === 1 ? '' : 's'}`));
      const visible = [];
      passages.forEach(passage => {
        const parent = visible.find(item => item.passage.page === passage.page
          && item.passage.char_start < passage.char_end
          && passage.char_start < item.passage.char_end);
        if (parent) parent.nearby.push(passage);
        else visible.push({passage, nearby: []});
      });
      visible.forEach(item => {
        card.append(passageCard(item.passage, {query, excerpt: true}));
        if (item.nearby.length) {
          const nearby = node('details', null, 'nearby-passages');
          nearby.append(node('summary', `${item.nearby.length} overlapping passage${item.nearby.length === 1 ? '' : 's'}`));
          item.nearby.forEach(passage => nearby.append(passageCard(passage, {query, excerpt: true})));
          card.append(nearby);
        }
      });
      results.append(card);
    });
  }
  async function showSource(sourceId, passage = 1, append = false, query = activeQuery) {
    const token = ++detailGeneration;
    const data = await api(`/${sourceId}`, {}, {passage});
    if (token !== detailGeneration) return;
    const detail = byId('detail');
    detail.hidden = false;
    if (!append) {
      ++pdfRequestGeneration;
      if (pageObjectUrl) URL.revokeObjectURL(pageObjectUrl);
      pageObjectUrl = null;
      detail.replaceChildren(readerHeader(data.source));
      if (data.source.empty_pages.length) detail.append(node('p', `No extracted text on pages ${data.source.empty_pages.join(', ')}. These pages are not searchable.`, 'hint'));
      detail.append(node('p', 'Citations refer to extracted text. Rendered pages show layout; download the original for full fidelity.', 'hint'));
      const tabs = node('div', null, 'reader-tabs');
      passagePane = node('div', null, 'reader-pane');
      renderedPane = node('div', null, 'reader-pane'); renderedPane.hidden = true;
      originalPane = node('div', null, 'reader-pane'); originalPane.hidden = true;
      tabs.append(button('Extracted passages', async () => selectView('passages')));
      tabs.append(button('Rendered view', () => selectView('rendered', data.source, data.passages[0]?.page || 1)));
      tabs.append(button('Original / raw', () => selectView('original', data.source)));
      detail.append(tabs, passagePane, renderedPane, originalPane);
      window.history.replaceState(null, '', sourceUrl(data.source, passage));
    }
    passagePane.querySelector('[data-next]')?.remove();
    data.passages.forEach(item => passagePane.append(passageCard(item, {query})));
    if (data.next_passage) {
      const next = button('Read next passages', () => showSource(sourceId, data.next_passage, true, query));
      next.dataset.next = 'true'; passagePane.append(next);
    }
    if (!append) detail.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
  async function selectView(kind, source = null, passage = 1) {
    passagePane.hidden = kind !== 'passages';
    renderedPane.hidden = kind !== 'rendered';
    originalPane.hidden = kind !== 'original';
    if (!source || kind === 'passages') return;
    const token = detailGeneration;
    if (kind === 'original') {
      if (originalPane.children.length) return;
      originalPane.append(node('p', 'The original is retained byte-for-byte. Text files can be inspected here; PDFs can be downloaded.', 'hint'));
      originalPane.append(button('Download original', () => download(source)));
      if (source.mime !== 'application/pdf') {
        const data = await api(`/${source.source_id}/text`, {}, {mode: source.mode});
        if (token !== detailGeneration) return;
        const editor = node('textarea', null, 'original-editor');
        editor.value = data.text;
        editor.setAttribute('aria-label', `Editable copy of ${source.title}`);
        originalPane.append(editor, node('p', 'Saving creates a new source. This original and its citation links stay unchanged.', 'hint'));
        originalPane.append(button('Save edited copy', async () => {
          if (editor.value === data.text) { status('No changes to save.'); return; }
          const result = await api(`/${source.source_id}/copy`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: editor.value})
          }, {mode: source.mode});
          await browse();
          await showSource(result.source.source_id);
          status(result.source.duplicate ? 'These bytes already exist as a saved source.' : 'Edited copy saved as a new source. The earlier version remains.');
        }));
      }
      return;
    }
    if (source.mime === 'application/pdf') {
      await showPdfPage(source, Math.max(1, source.page_count ? Math.min(source.page_count, Number(passage) || 1) : 1), token);
    } else if (/\.(md|markdown)$/i.test(source.filename)) {
      if (renderedPane.children.length) return;
      const data = await api(`/${source.source_id}/rendered`, {}, {mode: source.mode});
      if (token !== detailGeneration) return;
      const frame = node('iframe', null, 'markdown-frame');
      frame.setAttribute('sandbox', '');
      frame.setAttribute('title', `Rendered ${source.title}`);
      frame.srcdoc = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">`
        + `<style>body{font:16px/1.6 system-ui,sans-serif;color:#eef0ff;background:#171925;padding:20px;overflow-wrap:anywhere}pre{white-space:pre-wrap}a{color:#85dcff}</style>`
        + data.html;
      renderedPane.append(frame);
    } else {
      if (renderedPane.children.length) return;
      const data = await api(`/${source.source_id}/text`, {}, {mode: source.mode});
      if (token !== detailGeneration) return;
      renderedPane.append(node('pre', data.text, 'original-text'));
    }
  }
  async function showPdfPage(source, page, token) {
    if (page < 1 || page > source.page_count) return;
    const pageRequest = ++pdfRequestGeneration;
    const response = await Utils.auth.fetch(`/api/library/${source.source_id}/page/${page}?mode=${source.mode}`);
    if (!response.ok) throw new Error('This PDF page could not be rendered. Download the original instead.');
    const blob = await response.blob();
    if (token !== detailGeneration || pageRequest !== pdfRequestGeneration) return;
    if (pageObjectUrl) URL.revokeObjectURL(pageObjectUrl);
    pageObjectUrl = URL.createObjectURL(blob);
    const toolbar = node('div', null, 'page-controls');
    const previous = button('Previous page', () => showPdfPage(source, page - 1, token));
    const next = button('Next page', () => showPdfPage(source, page + 1, token));
    previous.disabled = page <= 1;
    next.disabled = page >= source.page_count;
    toolbar.append(previous, node('span', `Page ${page} of ${source.page_count}`), next);
    const image = node('img');
    image.alt = `Page ${page} of ${source.title}`;
    image.src = pageObjectUrl;
    renderedPane.replaceChildren(toolbar, image);
  }
  async function download(source) {
    const response = await Utils.auth.fetch(`/api/library/${source.source_id}/download?mode=${source.mode}`);
    if (!response.ok) throw new Error('The original could not be downloaded.');
    const url = URL.createObjectURL(await response.blob());
    const link = node('a'); link.href = url; link.download = source.filename;
    document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function indexSource(sourceId, sourceMode = mode) {
    const data = await api(`/${sourceId}/queue`, {method: 'POST'}, {mode: sourceMode});
    updateIndexLabels(data.source);
    status(data.queued ? 'Meaning indexing queued. It continues after you leave this page.' : 'Meaning index is already ready.');
  }
  function renderSelectedFiles() {
    const selection = byId('selected-files');
    selection.replaceChildren();
    selection.hidden = selectedFiles.length === 0;
    byId('selection-count').hidden = selectedFiles.length === 0;
    byId('selection-count').textContent = selectedFiles.length
      ? `${selectedFiles.length} chosen · ${mode}` : '';
    byId('save').disabled = uploading || selectedFiles.length === 0;
    byId('clear-files').hidden = selectedFiles.length === 0;
    byId('clear-files').disabled = uploading || selectedFiles.length === 0;
    byId('title').disabled = uploading || selectedFiles.length !== 1;
    if (selectedFiles.length !== 1) byId('title').value = '';
    if (!selectedFiles.length) return;
    const summary = node('p', `${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'} ready to add to the ${mode} library. Nothing is uploaded until you click Add to library.`, 'selection-summary');
    const list = node('ul', null, 'selected-file-list');
    selectedFiles.forEach((file, index) => {
      const item = node('li', null, 'selected-file');
      const description = node('span', `${file.name} · ${Math.max(1, Math.ceil(file.size / 1024))} KB`);
      const remove = button('Remove from list', async () => {
        selectedFiles.splice(index, 1);
        renderSelectedFiles();
      });
      remove.setAttribute('aria-label', `Remove ${file.name} from list`);
      remove.disabled = uploading;
      item.append(description, remove);
      list.append(item);
    });
    selection.append(summary, list);
  }
  byId('file').addEventListener('change', () => {
    selectedFiles.push(...Array.from(byId('file').files || []));
    byId('file').value = '';
    renderSelectedFiles();
  });
  byId('clear-files').addEventListener('click', () => {
    selectedFiles = [];
    byId('file').value = '';
    renderSelectedFiles();
  });
  renderSelectedFiles();
  byId('upload-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (uploading || !selectedFiles.length) return;
    const files = [...selectedFiles];
    const uploadMode = mode;
    const title = files.length === 1 ? byId('title').value : '';
    const progress = byId('import-progress');
    progress.hidden = false;
    progress.replaceChildren(node('h2', `Importing ${files.length} source${files.length === 1 ? '' : 's'} to ${uploadMode}`));
    const rows = files.map(file => {
      const row = node('div', null, 'import-row');
      row.append(node('span', file.name), node('span', 'Waiting'));
      progress.append(row);
      return {row, state: row.children[1], retry: null};
    });
    async function saveFile(file, position) {
      const item = rows[position];
      if (file.size > 25 * 1024 * 1024) {
        item.state.textContent = 'Too large (25 MB limit)';
        return false;
      }
      item.state.textContent = 'Adding…';
      const data = new FormData();
      data.append('file', file);
      if (title) data.append('title', title);
      try {
        const saved = await api('', {method: 'POST', body: data}, {mode: uploadMode});
        item.state.textContent = saved.source.duplicate ? 'Already in library' : 'Added · text search ready · meaning search preparing';
        item.retry?.remove(); item.retry = null;
        return true;
      } catch (error) {
        item.state.textContent = `Failed: ${error.message}`;
        if (!item.retry) {
          item.retry = button('Retry this file', async () => {
            item.retry.disabled = true;
            const succeeded = await saveFile(file, position);
            if (succeeded) {
              if (mode === uploadMode) await browse();
              status(`Retried ${file.name} successfully in ${uploadMode}.`);
            } else if (item.retry) item.retry.disabled = false;
          });
          item.row.append(item.retry);
        }
        return false;
      }
    }
    uploading = true;
    byId('file').disabled = true;
    renderSelectedFiles();
    let savedCount = 0;
    try {
      for (const [position, file] of files.entries()) {
        if (await saveFile(file, position)) savedCount += 1;
      }
      selectedFiles = [];
      byId('upload-form').reset();
      if (mode === uploadMode) await browse();
      status(`${savedCount} of ${files.length} files added to the ${uploadMode} library. Text search is ready; search by meaning continues in the background.`);
    } catch (error) { status(error.message); }
    finally {
      uploading = false;
      byId('file').disabled = false;
      renderSelectedFiles();
    }
  });
  async function search() {
    const query = byId('query').value.trim();
    if (!query) { await browse(); return; }
    const token = ++generation;
    closeSource();
    status('Searching saved passages…');
    try {
      const args = {q: query, semantic: byId('semantic').checked};
      if (activeSource) args.source = activeSource;
      const data = await api('', {}, args);
      if (token !== generation) return;
      activeQuery = query;
      renderSearchContext();
      renderSearchResults(data, query);
      byId('more').hidden = true;
      const summary = [
        `${data.passages.length} passages in ${new Set(data.passages.map(p => p.source_id)).size} sources`,
        data.retrieval_mode === 'hybrid' ? 'Keyword + meaning' : 'Keyword',
        data.semantic_coverage_incomplete
          ? `Meaning coverage ${data.semantic_indexed_passages}/${data.total_passages}` : null,
        data.semantic_unavailable_reason
      ];
      status(summary.filter(Boolean).join(' · '));
    } catch (error) { if (token === generation) status(error.message); }
  }
  byId('search-form').addEventListener('submit', async event => {
    event.preventDefault();
    await search();
  });
  byId('mode').addEventListener('change', () => {
    mode = byId('mode').value; ++generation;
    activeQuery = ''; activeSource = null; activeSourceTitle = '';
    selectedFiles = [];
    byId('file').value = '';
    renderSelectedFiles();
    byId('results').replaceChildren();
    byId('more').hidden = true;
    closeSource();
    browse().catch(error => status(error.message));
    refreshWorkerHealth();
  });
  byId('browse').addEventListener('click', () => { byId('query').value = ''; browse().catch(error => status(error.message)); });
  byId('clear-search').addEventListener('click', () => { byId('query').value = ''; browse().catch(error => status(error.message)); });
  byId('query').addEventListener('input', () => {
    if (!byId('query').value.trim() && (activeQuery || activeSource)) browse().catch(error => status(error.message));
    else renderSearchContext();
  });
  byId('more').addEventListener('click', () => browse(true).catch(error => status(error.message)));
  byId('refresh').addEventListener('click', () => {
    if (byId('query').value.trim()) search().catch(error => status(error.message));
    else browse().catch(error => status(error.message));
    refreshWorkerHealth();
  });
  if (typeof window.setInterval === 'function') window.setInterval(() => {
    if (document.visibilityState !== 'hidden') {
      refreshPendingStatuses().catch(() => {});
      refreshWorkerHealth();
    }
  }, 5000);
  async function checkInbox() {
    const data = await api('/inbox');
    const jobs = data.jobs || [];
    const pending = data.job_counts?.pending || 0;
    const failedCount = data.job_counts?.error || 0;
    const failed = jobs.filter(job => job.state === 'error');
    byId('inbox-status').textContent = `${data.eligible_count} eligible files in ${data.inbox_path}; ${data.queueable_count} to queue; `
      + `${data.skipped_count} skipped; estimated space ${Math.ceil(data.estimated_disk_bytes / 1048576)} MB, `
      + `free ${Math.ceil(data.free_disk_bytes / 1048576)} MB. ${pending} queued; ${failedCount} need attention.`
      + (failed.length ? ` Latest error: ${failed[0].relative_path}: ${failed[0].error}` : '');
    return data;
  }
  byId('check-inbox').addEventListener('click', () => checkInbox().catch(error => status(error.message)));
  byId('queue-inbox').addEventListener('click', async () => {
    try {
      const preview = await checkInbox();
      if (!preview.queueable_count) { status('No new or failed files to queue in this mode’s inbox.'); return; }
      if (!preview.enough_disk) { status('Not enough free disk for the estimated import.'); return; }
      if (!window.confirm(`Queue up to ${preview.queueable_count} files from ${preview.inbox_path}? Originals remain in the inbox.`)) return;
      const data = await api('/inbox/queue', {method: 'POST'});
      status(`${data.queued} inbox files queued. Import continues after this tab closes.`);
      await checkInbox();
    } catch (error) { status(error.message); }
  });
  const initialDetailGeneration = detailGeneration;
  refreshWorkerHealth();
  browse(false, false).then(completed => {
    if (completed && detailGeneration === initialDetailGeneration && params.get('source')) {
      return showSource(params.get('source'), Number(params.get('passage') || 1));
    }
  }).catch(error => status(error.message));
})();
