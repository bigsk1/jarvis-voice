/** Apify lifecycle and property previews, shared by live and restored results.
 *
 * All returned content is an inert node model. Saved-page browsing reads only
 * an authenticated, mode-qualified Stash archive, never Apify or a model.
 */
window.createApifyResultAdapter = function createApifyResultAdapter({
  node, stashLinks, compactText, toDom,
}) {
  const views = new WeakMap();
  const pageSize = 12;
  const maxArchiveBytes = 8 * 1024 * 1024;
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const text = (value, limit = 240) => typeof value === 'string' ? compactText(value, limit) : '';
  const element = (tag, value = null, className = '', children = []) => node(
    tag, className ? {class: className} : {}, value, children,
  );
  const count = value => {
    if (Number.isSafeInteger(value) && value >= 0) return BigInt(value);
    return typeof value === 'string' && /^(0|[1-9][0-9]{0,127})$/.test(value) ? BigInt(value) : null;
  };
  const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const printable = value => number(value) === null ? '' : value.toLocaleString('en-US');
  const label = value => {
    const words = text(value, 100).replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2');
    const normalized = words === words.toUpperCase() ? words.toLowerCase() : words;
    return normalized ? normalized[0].toUpperCase() + normalized.slice(1) : '';
  };
  const httpUrl = (value, source = '', image = false) => {
    if (typeof value !== 'string' || value.length > 8000) return '';
    try {
      const url = new URL(value);
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return '';
      if (image && (url.protocol !== 'https:' || /\.svg(?:$|\/)/i.test(url.pathname))) return '';
      const host = url.hostname.toLowerCase();
      const root = image
        ? source === 'zillow' ? 'zillowstatic.com' : 'cdn-redfin.com'
        : source === 'zillow' ? 'zillow.com' : 'redfin.com';
      return host === root || host.endsWith('.' + root) ? url.href : '';
    } catch (_error) { return ''; }
  };

  function property(row, sourceHint = '') {
    if (!record(row)) return null;
    if (row.kind === 'property_listing' && ['zillow', 'redfin'].includes(row.source)
        && (!sourceHint || sourceHint === row.source)) {
      return {...row, address: text(row.address) || 'Address not provided',
        url: httpUrl(row.url, row.source), image_url: httpUrl(row.image_url, row.source, true)};
    }
    // Existing saved Zillow runs predate canonical presentation rows. These
    // fields are verified against their native retained dataset, not aliases
    // guessed from arbitrary Actor output.
    if (sourceHint && sourceHint !== 'zillow') return null;
    if (row.isValid === false || (row.error != null && row.error !== '')) return null;
    const url = httpUrl(row.propertyUrl, 'zillow');
    if (!url || !record(row.listingAddress)) return null;
    const address = row.listingAddress;
    const listingPrice = record(row.listingPrice) ? row.listingPrice : {};
    return {
      kind: 'property_listing', source: 'zillow', listing_id: row.zpid,
      address: text(address.full) || [text(address.street),
        [text(address.city), text(address.state), text(address.zipCode)].filter(Boolean).join(' ')].filter(Boolean).join(', ')
        || 'Address not provided',
      city: text(address.city), state: text(address.state, 80), postal_code: text(address.zipCode, 30),
      price: number(listingPrice.amount), price_text: text(listingPrice.formatted, 100),
      currency: text(listingPrice.currency, 12), listing_status: text(row.listingStatus, 80),
      property_type: text(row.homeType, 80), bedrooms: number(row.bedrooms), bathrooms: number(row.bathrooms),
      area: number(row.livingArea), area_unit: text(row.livingAreaUnit, 30),
      days_on_zillow: number(row.daysOnZillow), url,
      image_url: httpUrl(row.mainImage, 'zillow', true), scraped_at: text(row.scrapedAt, 100),
    };
  }

  function price(row) {
    if (text(row.price_text, 100)) return text(row.price_text, 100);
    if (number(row.price) === null) return 'Price not provided';
    const currency = typeof row.currency === 'string' && /^[A-Z]{3}$/.test(row.currency) ? row.currency : '';
    if (!currency) return printable(row.price);
    try {
      return new Intl.NumberFormat('en-US', {style: 'currency', currency,
        maximumFractionDigits: row.price % 1 === 0 ? 0 : 2}).format(row.price);
    } catch (_error) { return `${printable(row.price)} ${currency}`; }
  }

  function propertyCard(row, index) {
    const statusLabels = {for_sale: 'For sale', forSale: 'For sale', for_rent: 'For rent', forRent: 'For rent', sold: 'Sold'};
    const status = statusLabels[row.listing_status] || label(row.listing_status) || 'Status not provided';
    const details = [
      number(row.bedrooms) !== null ? `${printable(row.bedrooms)} beds` : '',
      number(row.bathrooms) !== null ? `${printable(row.bathrooms)} baths` : '',
      number(row.area) !== null ? `${printable(row.area)}${text(row.area_unit, 30) ? ' ' + text(row.area_unit, 30) : ' area (unit not provided)'}` : '',
    ].filter(Boolean);
    const sourceName = row.source === 'redfin' ? 'Redfin' : 'Zillow';
    const location = [text(row.city, 100), [text(row.state, 80), text(row.postal_code, 30)].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    const children = [];
    children.push(element('div', null, 'apify-property-media', [
      ...(row.image_url ? [node('img', {class: 'apify-property-image', src: row.image_url,
        alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer'})] : []),
      node('div', {class: 'apify-property-image-fallback', ...(row.image_url ? {hidden: true} : {})},
        row.image_url ? 'Photo unavailable' : 'No photo provided'),
    ]));
    children.push(element('div', null, 'apify-property-body', [
      element('div', null, 'apify-property-topline', [
        element('span', status, 'apify-property-status'), element('span', `#${index + 1n}`, 'apify-property-number'),
      ]),
      element('div', price(row), 'apify-property-price'),
      element('h4', row.address, 'apify-property-address'),
      ...(location && !row.address.includes(location) ? [element('p', location, 'apify-property-location')] : []),
      ...(details.length ? [element('p', details.join(' · '), 'apify-property-facts')] : []),
      element('p', [label(row.property_type), number(row.days_on_zillow) !== null
        ? `${printable(row.days_on_zillow)} days on Zillow` : ''].filter(Boolean).join(' · '), 'apify-property-secondary'),
      ...(row.url ? [node('a', {class: 'structured-results-action', href: row.url,
        target: '_blank', rel: 'noopener noreferrer'}, `View on ${sourceName}`)] : []),
    ]));
    return element('article', null, 'apify-property-card', children);
  }

  function listingRows(rows, sourceHint = '') {
    return rows.map((row, index) => ({row: property(row, sourceHint), index})).filter(item => item.row);
  }

  function grid(rows, sourceHint, offset = 0n) {
    return element('div', null, 'apify-property-grid', listingRows(rows, sourceHint).map(
      item => propertyCard(item.row, offset + BigInt(item.index)),
    ));
  }

  function coverage(result, shown) {
    const offset = count(result.offset) ?? 0n;
    const returned = count(result.returned_count);
    const total = count(result.total_items);
    const unrecognized = count(result.presentation?.unrecognized_count) ?? 0n;
    const recognized = count(result.presentation?.input_count);
    return [
      shown ? `Showing ${shown} listing${shown === 1 ? '' : 's'} from this fetched page` : 'No listing preview in this page',
      returned !== null ? `${returned} fetched${offset ? ` at offset ${offset}` : ''}` : '',
      unrecognized && recognized !== null && recognized >= unrecognized ? `${recognized - unrecognized} recognized listings` : '',
      total !== null ? `${total} items in dataset` : 'Dataset total unknown',
      result.complete === true ? 'Fetched page covers the complete dataset'
        : result.complete === false ? 'Dataset coverage is partial' : 'Dataset coverage unknown',
    ].filter(Boolean).join(' · ');
  }

  function rawReference(payload, fallbackMode) {
    const ref = payload.raw_ref;
    const mode = payload.source?.mode || fallbackMode;
    const match = typeof ref === 'string' && ref.match(/^stash:\/\/(space_[A-Za-z0-9_-]+)\/([A-Za-z0-9_-]+)$/);
    return match && ['cloud', 'local'].includes(mode)
      ? {ref, mode, href: `/api/stash/${match[1]}/${match[2]}?mode=${mode}`} : null;
  }

  function model(payload, options = {}) {
    if (payload.source?.provider !== 'apify') return null;
    const result = payload.result || {}, execution = payload.execution || {};
    const nativeRows = Array.isArray(result.sample_items) ? result.sample_items
      : Array.isArray(result.items) ? result.items : null;
    const sourceHint = result.presentation?.kind === 'property_listings' ? result.presentation.source : '';
    const rows = nativeRows?.slice(0, 20) || [];
    const properties = listingRows(rows, sourceHint);
    const isListings = properties.length > 0 || (nativeRows && ['zillow', 'redfin'].includes(sourceHint));
    const lifecycle = !nativeRows && execution.run_id && execution.status
      && (result.kind === 'object' || !result.kind);
    if (!isListings && !lifecycle) return null;
    const raw = rawReference(payload, options.mode);
    const attributes = {class: 'structured-results-preview structured-results-external structured-results-apify',
      'aria-label': isListings ? 'Apify property listings' : 'Apify run'};
    if (options.embedded) {
      const surface = options.surface === 'orchestration' ? 'orchestration' : 'workflow';
      attributes.class += ` structured-results-workflow-section${surface === 'orchestration' ? ' structured-results-orchestration-section' : ''}`;
      if (options.toolName) attributes[`data-${surface}-tool`] = options.toolName;
      if ((options.call ?? options.step) != null) attributes[`data-${surface}-${surface === 'orchestration' ? 'call' : 'step'}`] = options.call ?? options.step;
      if (surface === 'orchestration' && options.occurrence != null) attributes['data-orchestration-occurrence'] = options.occurrence;
    }
    const source = sourceHint || properties[0]?.row.source;
    const sourceName = source === 'redfin' ? 'Redfin' : source === 'zillow' ? 'Zillow' : 'Apify';
    const status = text(execution.status, 80) || 'Status unknown';
    const running = ['SUBMITTED', 'READY', 'RUNNING', 'TIMING-OUT', 'ABORTING'].includes(status);
    const children = [element('div', null, 'structured-results-header', [
      element('div', null, '', [
        element('div', 'Apify', 'structured-results-eyebrow'),
        element('div', isListings ? `${sourceName} property listings` : 'Actor run', 'structured-results-heading'),
        element('div', status, 'apify-run-status'),
        element('div', isListings ? coverage(result, properties.length)
          : running ? 'Run accepted; output is not complete. Keep this run ID for the next check.'
            : status === 'SUCCEEDED' ? 'Actor finished. Read its existing dataset to inspect output.'
              : 'Actor stopped; inspect this existing run before deciding what to do next.', 'structured-results-subtitle'),
      ]),
    ])];
    const statusValue = record(result.value) ? result.value : {};
    if (text(statusValue.status_message, 800)) children.push(element('p', text(statusValue.status_message, 800), 'external-result-note'));
    if (isListings) {
      children.push(element('p', 'Listing data is external evidence. Search filters and availability are not independently verified.', 'apify-listing-notice'));
      const unrecognized = count(result.presentation?.unrecognized_count) ?? 0n;
      if (unrecognized > 0n) children.push(element('p', `${unrecognized} fetched record${unrecognized === 1n ? '' : 's'} could not be recognized as property listings. Original records remain in the raw response and are excluded from listing cards. Dataset coverage describes fetched records.`, 'apify-listing-notice'));
      if (properties.length) children.push(element('div', null, 'apify-initial-preview', [grid(rows, sourceHint, unrecognized ? 0n : count(result.offset) ?? 0n)]));
      else children.push(element('p', 'No recognized property records in the displayed preview.', 'external-result-note'));
      if (properties.length < rows.length) children.push(element('p', `${rows.length - properties.length} unrecognized records remain in the raw response.`, 'external-result-note'));
      if (payload.limits?.sample_truncated || payload.limits?.truncated
          || (count(result.returned_count) ?? 0n) > BigInt(rows.length)) {
        children.push(element('p', 'This preview is shortened. Browse the saved page to inspect the rows already fetched.', 'external-result-note'));
      }
      if (raw) {
        attributes['data-apify-raw-ref'] = raw.ref;
        attributes['data-apify-mode'] = raw.mode;
        attributes['data-apify-source'] = source || '';
        attributes['data-apify-run-id'] = text(execution.run_id, 128);
        attributes['data-apify-dataset-id'] = text(result.dataset_id, 128);
        children.push(node('button', {type: 'button', class: 'apify-browse-saved structured-results-action'}, 'Browse saved page'));
        children.push(node('div', {class: 'apify-saved-page', 'aria-live': 'polite'}));
      }
      const next = count(result.pagination?.next_offset);
      if (result.pagination?.has_more === true) children.push(element('p', next !== null
        ? `More remote records are available. Ask for the next dataset page at offset ${next}; this does not start another Actor run.`
        : 'More remote records may be available. Continue reading this same run.', 'external-result-note'));
    }
    const provenance = [
      execution.actor_name || execution.actor_id ? `Actor: ${text(execution.actor_name || execution.actor_id, 220)}` : '',
      execution.run_id ? `Run: ${text(execution.run_id, 128)}` : '',
      result.dataset_id ? `Dataset: ${text(result.dataset_id, 128)}` : '',
      statusValue.started_at ? `Started: ${text(statusValue.started_at, 100)}` : '',
      statusValue.finished_at ? `Finished: ${text(statusValue.finished_at, 100)}` : '',
    ].filter(Boolean).map(value => element('p', value, 'external-result-note'));
    if (provenance.length) children.push(element('details', null, 'external-result-details', [element('summary', 'Run details'), ...provenance]));
    children.push(element('div', null, 'external-result-downloads', stashLinks(payload, options.mode)));
    return node('section', attributes, null, children);
  }

  async function readArchive(response) {
    if (Number(response.headers?.get('Content-Length')) > maxArchiveBytes) throw new Error('Saved page exceeds the 8 MiB browser limit. Use its raw download.');
    if (!response.body?.getReader) {
      const value = await response.text();
      if (value.length > maxArchiveBytes) throw new Error('Saved page exceeds the browser limit. Use its raw download.');
      return JSON.parse(value);
    }
    const reader = response.body.getReader(), chunks = [];
    let size = 0;
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > maxArchiveBytes) throw new Error('Saved page exceeds the 8 MiB browser limit. Use its raw download.');
        chunks.push(value);
      }
    } finally { await reader.cancel(); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  function renderSavedPage(section, state) {
    const container = section.querySelector('.apify-saved-page');
    if (!container) return;
    const initial = section.querySelector('.apify-initial-preview');
    if (initial) initial.hidden = true;
    const start = state.page * pageSize, rows = state.rows.slice(start, start + pageSize);
    const shown = listingRows(rows, state.source).length;
    const summary = state.unrecognized
      ? `Saved page: ${rows.length ? `listings ${start + 1}–${start + rows.length} of ${state.rows.length} recognized listings` : '0 recognized listings'} from ${state.fetched} fetched record${state.fetched === 1 ? '' : 's'}. No new Apify request.`
      : `Saved page: ${rows.length ? `rows ${start + 1}–${start + rows.length}` : '0 rows'} of ${state.rows.length} fetched rows. No new Apify request.`;
    const content = [element('p', summary, 'apify-saved-page-summary'),
      grid(rows, state.source, (state.unrecognized ? 0n : state.offset) + BigInt(start))];
    if (state.unrecognized) content.push(element('p', `${state.unrecognized} unsupported or error record${state.unrecognized === 1 ? ' is' : 's are'} excluded from these cards. Original records remain in the raw download.`, 'external-result-note'));
    if (shown < rows.length) content.push(element('p', `${rows.length - shown} records on this page are not recognized property listings. See the raw download.`, 'external-result-note'));
    const pages = Math.max(1, Math.ceil(state.rows.length / pageSize));
    content.push(element('div', null, 'apify-saved-pagination', [
      node('button', {type: 'button', class: 'apify-saved-previous', ...(state.page === 0 ? {disabled: true} : {})}, 'Previous saved rows'),
      element('span', `Page ${state.page + 1} of ${pages}`),
      node('button', {type: 'button', class: 'apify-saved-next', ...(start + pageSize >= state.rows.length ? {disabled: true} : {})}, 'Next saved rows'),
    ]));
    container.replaceChildren(...content.map(toDom));
  }

  async function browse(section, button) {
    const prior = views.get(section);
    if (prior) { renderSavedPage(section, prior); return; }
    const raw = rawReference({raw_ref: section.dataset.apifyRawRef, source: {mode: section.dataset.apifyMode}});
    const container = section.querySelector('.apify-saved-page');
    if (!raw || !container) return;
    button.disabled = true;
    container.textContent = 'Loading the saved page…';
    try {
      const response = await Utils.auth.fetch(raw.href, {credentials: 'same-origin', redirect: 'error'});
      if (!response.ok) throw new Error('The saved page is unavailable or expired. The original run ID is preserved.');
      const archive = await readArchive(response);
      if (!record(archive) || !Array.isArray(archive.items) || archive.items.length > 100
          || !record(archive.run) || archive.run.id !== section.dataset.apifyRunId
          || !record(archive.dataset) || archive.dataset.id !== section.dataset.apifyDatasetId) {
        throw new Error('This archive does not match the saved run and dataset page. Use its raw download.');
      }
      const presentation = archive.presentation;
      const canonical = presentation?.kind === 'property_listings'
        && archive.presentation.source === section.dataset.apifySource
        && Array.isArray(presentation.items);
      const unrecognized = canonical && Number.isSafeInteger(presentation.unrecognized_count)
        && presentation.unrecognized_count >= 0 ? presentation.unrecognized_count : 0;
      if (canonical && (presentation.items.length !== archive.items.length
          || 'input_count' in presentation || 'unrecognized_count' in presentation)
          && (presentation.input_count !== archive.items.length
              || !Number.isSafeInteger(presentation.unrecognized_count)
              || presentation.unrecognized_count < 0
              || presentation.items.length + presentation.unrecognized_count !== archive.items.length)) {
        throw new Error('The saved property presentation does not match its fetched record counts. Use its raw download.');
      }
      const rows = canonical ? presentation.items : archive.items;
      const state = {rows, source: section.dataset.apifySource, offset: count(archive.offset) ?? 0n,
        fetched: archive.items.length, unrecognized, page: 0};
      views.set(section, state);
      renderSavedPage(section, state);
      button.textContent = 'Saved page loaded';
    } catch (_error) {
      container.textContent = _error instanceof Error ? _error.message : 'Unable to read this saved page. Use its raw download.';
    } finally { button.disabled = false; }
  }

  function handleClick(event) {
    const button = event.target?.closest?.('.apify-browse-saved, .apify-saved-previous, .apify-saved-next');
    if (!button || button.disabled) return false;
    const section = button.closest('.structured-results-apify');
    if (!section) return false;
    if (button.classList.contains('apify-browse-saved')) void browse(section, button);
    else {
      const state = views.get(section);
      if (state) {
        state.page = Math.min(Math.max(state.page + (button.classList.contains('apify-saved-next') ? 1 : -1), 0), Math.max(0, Math.ceil(state.rows.length / pageSize) - 1));
        renderSavedPage(section, state);
      }
    }
    return true;
  }

  function handleImageError(event) {
    const image = event.target;
    if (!image?.matches?.('.apify-property-image')) return;
    image.hidden = true;
    const fallback = image.parentElement?.querySelector('.apify-property-image-fallback');
    if (fallback) fallback.hidden = false;
  }

  return {model, handleClick, handleImageError};
};
