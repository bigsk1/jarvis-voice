/* Source library: plain DOM rendering, explicit writes and resumable indexing. */
(() => {
  const byId = id => document.getElementById(id);
  const params = new URLSearchParams(window.location.search);
  let mode = params.get('mode') === 'local' ? 'local' : 'cloud';
  let generation = 0;
  let detailGeneration = 0;
  let activeQuery = '';
  let nextOffset = null;
  let indexing = false;
  let pauseIndex = false;
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
    byId('detail').hidden = true;
    byId('detail').replaceChildren();
    window.history.replaceState(null, '', `/library?mode=${mode}`);
    if (restoreFocus) byId(activeQuery ? 'query' : 'browse').focus();
  }
  function sourceCard(source) {
    const card = node('article');
    const link = node('a', source.title);
    link.href = sourceUrl(source);
    link.addEventListener('click', event => { event.preventDefault(); showSource(source.source_id).catch(error => status(error.message)); });
    const heading = node('h2'); heading.append(link); card.append(heading);
    const meta = node('p', indexLabel(source), 'meta');
    meta.dataset.libraryIndex = `${source.mode}/${source.source_id}`;
    card.append(meta);
    const actions = node('div', null, 'actions');
    actions.append(button('Open source', () => showSource(source.source_id)));
    actions.append(button('Index remaining', () => indexSource(source.source_id)));
    actions.append(button('Download original', () => download(source)));
    actions.append(button('Remove', async () => {
      if (!window.confirm(`Remove “${source.title}” and its passages from the ${mode} library?`)) return;
      await api(`/${source.source_id}`, {method: 'DELETE'});
      closeSource();
      await browse();
      status('Source removed.');
    }));
    card.append(actions);
    return card;
  }
  function indexLabel(source) {
    return `${source.passage_count} passages · ${source.indexed_passages} indexed by meaning · ${source.mode}`;
  }
  function updateIndexLabels(source) {
    document.querySelectorAll('[data-library-index]').forEach(element => {
      if (element.dataset.libraryIndex === `${source.mode}/${source.source_id}`) element.textContent = indexLabel(source);
    });
  }
  async function browse(append = false, resetDetail = true) {
    if (!append) { activeQuery = ''; if (resetDetail) closeSource(); }
    const token = ++generation;
    const data = await api('', {}, {offset: append ? nextOffset || 0 : 0});
    if (token !== generation) return false;
    if (!append) byId('results').replaceChildren();
    data.sources.forEach(source => byId('results').append(sourceCard(source)));
    nextOffset = data.next_offset;
    byId('more').hidden = nextOffset == null;
    status(data.total ? `${data.total} saved sources in ${mode}.` : `No saved sources in ${mode}. Save a document to start.`);
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
    const card = node('article');
    const link = node('a', passage.citation);
    link.href = sourceUrl(passage, passage.number);
    link.addEventListener('click', event => { event.preventDefault(); showSource(passage.source_id, passage.number, false, query).catch(error => status(error.message)); });
    const ranges = matchingRanges(passage.text, query);
    card.append(link, passageText(passage.text, ranges, excerpt));
    if (excerpt) {
      if (query && !ranges.length) card.append(node('p', 'No literal match in this passage. Open the source for context.', 'hint'));
      card.append(button('View full passage', () => showSource(passage.source_id, passage.number, false, query)));
    }
    if (passage.matched_by) card.append(node('p', `Matched by ${passage.matched_by.join(' + ')}`, 'meta'));
    return card;
  }
  async function showSource(sourceId, passage = 1, append = false, query = activeQuery) {
    const token = ++detailGeneration;
    const data = await api(`/${sourceId}`, {}, {passage});
    if (token !== detailGeneration) return;
    const detail = byId('detail');
    detail.hidden = false;
    if (!append) {
      const toolbar = node('div', null, 'detail-toolbar');
      toolbar.append(button('Close source', async () => closeSource(true)));
      detail.replaceChildren(toolbar, sourceCard(data.source));
      if (data.source.empty_pages.length) detail.append(node('p', `No extracted text on pages ${data.source.empty_pages.join(', ')}. These pages are not searchable.`, 'hint'));
      detail.append(node('p', 'Passages are extracted text. Download the original to inspect layout, images, or tables.', 'hint'));
      window.history.replaceState(null, '', sourceUrl(data.source, passage));
    }
    detail.querySelector('[data-next]')?.remove();
    data.passages.forEach(item => detail.append(passageCard(item, {query})));
    if (data.next_passage) {
      const next = button('Read next passages', () => showSource(sourceId, data.next_passage, true, query));
      next.dataset.next = 'true'; detail.append(next);
    }
    if (!append) detail.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
  async function download(source) {
    const response = await Utils.auth.fetch(`/api/library/${source.source_id}/download?mode=${source.mode}`);
    if (!response.ok) throw new Error('The original could not be downloaded.');
    const url = URL.createObjectURL(await response.blob());
    const link = node('a'); link.href = url; link.download = source.filename;
    document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function indexSource(sourceId) {
    if (indexing) { status('One source is already indexing. Pause it before starting another.'); return; }
    indexing = true; pauseIndex = false;
    byId('stop-index').hidden = false;
    byId('mode').disabled = true;
    byId('save').disabled = true;
    try {
      do {
        status('Indexing saved passages by meaning… Your original is already saved.');
        const data = await api(`/${sourceId}/index`, {method: 'POST'});
        updateIndexLabels(data.source);
        if (data.index_error) { status(data.index_error); break; }
        status(`${data.source.indexed_passages} of ${data.source.passage_count} passages indexed.`);
        if (!data.remaining) break;
      } while (!pauseIndex);
      if (pauseIndex) status('Indexing paused. Completed batches are saved; Index remaining resumes them.');
    } finally {
      indexing = false;
      byId('stop-index').hidden = true;
      byId('mode').disabled = false;
      byId('save').disabled = false;
    }
  }
  byId('upload-form').addEventListener('submit', async event => {
    event.preventDefault();
    const file = byId('file').files[0];
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) { status('Sources must be at most 25 MB.'); return; }
    const data = new FormData(); data.append('file', file); data.append('title', byId('title').value);
    byId('save').disabled = true; byId('mode').disabled = true;
    status('Saving the original and extracting passages…');
    try {
      const saved = await api('', {method: 'POST', body: data});
      byId('upload-form').reset();
      await browse();
      status(saved.source.duplicate ? 'This original is already saved.' : 'Source saved. Keyword search is ready.');
      await indexSource(saved.source.source_id);
    } catch (error) { status(error.message); }
    finally { byId('save').disabled = false; byId('mode').disabled = indexing; }
  });
  byId('search-form').addEventListener('submit', async event => {
    event.preventDefault();
    const query = byId('query').value.trim();
    if (!query) { await browse().catch(error => status(error.message)); return; }
    const token = ++generation;
    closeSource();
    status('Searching saved passages…');
    try {
      const data = await api('', {}, {q: query, semantic: byId('semantic').checked});
      if (token !== generation) return;
      activeQuery = query;
      byId('results').replaceChildren(...data.passages.map(passage => passageCard(passage, {query, excerpt: true})));
      byId('more').hidden = true;
      const coverage = data.semantic_coverage_incomplete
        ? ` Search by meaning covers ${data.semantic_indexed_passages} of ${data.total_passages} passages.` : '';
      status(`${data.passages.length} passages · ${data.retrieval_mode}. ${data.semantic_unavailable_reason || ''}${coverage}`);
    } catch (error) { if (token === generation) status(error.message); }
  });
  byId('mode').addEventListener('change', () => {
    mode = byId('mode').value; ++generation;
    activeQuery = '';
    byId('results').replaceChildren();
    byId('more').hidden = true;
    closeSource();
    browse().catch(error => status(error.message));
  });
  byId('browse').addEventListener('click', () => { byId('query').value = ''; browse().catch(error => status(error.message)); });
  byId('more').addEventListener('click', () => browse(true).catch(error => status(error.message)));
  byId('stop-index').addEventListener('click', () => { pauseIndex = true; status('Pausing when this batch finishes…'); });
  window.addEventListener('pagehide', () => { pauseIndex = true; });
  const initialDetailGeneration = detailGeneration;
  browse(false, false).then(completed => {
    if (completed && detailGeneration === initialDetailGeneration && params.get('source')) {
      return showSource(params.get('source'), Number(params.get('passage') || 1));
    }
  }).catch(error => status(error.message));
})();
