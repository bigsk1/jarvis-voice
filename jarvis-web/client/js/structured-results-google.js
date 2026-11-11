/** Google SERP panels share one retained response, without flattening their identities. */
window.createGoogleSearchResultAdapter = function createGoogleSearchResultAdapter({
  node, stashLinks, compactText, jsonTree,
}) {
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const text = (value, maximum = 240) => typeof value === 'string' ? compactText(value, maximum) : '';
  const scalar = value => typeof value === 'string' ? text(value, 500)
    : typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value)) ? String(value) : '';
  const title = value => text(value, 100).replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
  const element = (tag, value = null, className = '', children = []) => node(
    tag, className ? {class: className} : {}, value, children,
  );
  const integer = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
  const rows = value => Array.isArray(value) ? value.filter(record).slice(0, 20) : [];
  const url = value => {
    if (typeof value !== 'string' || value.length > 8000) return '';
    try {
      const parsed = new URL(value);
      return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password
        ? parsed.href : '';
    } catch (_error) { return ''; }
  };
  const link = (href, label, className = 'structured-results-action') => {
    const safe = url(href);
    return safe ? node('a', {href: safe, class: className, target: '_blank', rel: 'noopener noreferrer'}, label) : null;
  };
  const paragraph = (value, className = 'google-serp-secondary') => element('p', value, className);
  const facts = values => values.filter(Boolean).map(value => element('span', value, 'google-serp-fact'));
  const imageUrl = url;

  function media(row, icon = false) {
    const candidates = icon ? [row.favicon, row.source_icon] : [row.thumbnail, row.image_url, row.image,
      ...(Array.isArray(row.header_images) ? row.header_images.slice(0, 3).filter(record).map(image => image.image || image.thumbnail) : [])];
    const src = candidates.map(imageUrl).find(Boolean);
    if (!src) return null;
    return element('span', null, icon ? 'google-serp-site-icon' : 'google-serp-thumbnail', [
      node('img', {class: 'google-serp-image', src, alt: '', loading: 'lazy', decoding: 'async',
        referrerpolicy: 'no-referrer', width: icon ? 20 : 80, height: icon ? 20 : 60}),
    ]);
  }

  function handleImageError(event) {
    const image = event.target;
    if (!image?.matches?.('.google-serp-image')) return;
    image.hidden = true;
    const wrapper = image.parentElement;
    if (wrapper?.classList?.contains('google-serp-thumbnail') || wrapper?.classList?.contains('google-serp-site-icon')) wrapper.hidden = true;
  }

  function panelNote(panel, shown, noun = 'results', selection = {}) {
    const total = integer(panel.count);
    const offset = integer(selection.offset);
    const savedRange = selection.selected_path === panel.path && panel.type === 'array'
      && offset !== null && shown > 0 && integer(selection.returned_count) === shown
      && total !== null && offset + shown <= total;
    return paragraph([
      savedRange ? `${title(noun)} ${offset + 1}–${offset + shown} of ${total}`
        : `${shown} ${noun} shown${total !== null ? ` of ${total} in this section` : ''}`,
      panel.truncated || (total !== null && total > shown) ? 'Preview shortened; full section is saved' : '',
    ].filter(Boolean).join(' · '), 'google-serp-coverage');
  }

  function panelSection(heading, className, children) {
    return element('section', null, `google-serp-panel ${className}`, [element('h4', heading), ...children]);
  }

  function available(panel, entity, selection) {
    const offers = rows(panel.preview).filter(row => text(row.name));
    if (!offers.length) return null;
    const cards = offers.map(row => element('article', null, 'google-serp-offer', [
      ...[media(row)].filter(Boolean),
      element('div', text(row.name), 'google-serp-offer-name'),
      ...(scalar(row.price) ? [paragraph(scalar(row.price), 'google-serp-offer-price')] : []),
      ...[link(row.link, 'View offer')].filter(Boolean),
    ]));
    return panelSection('Where to watch', 'google-serp-availability', [
      ...(entity ? [paragraph(`Google shows these offers for ${entity}.`)] : []),
      element('div', null, 'google-serp-offers', cards),
      panelNote(panel, offers.length, 'offers', selection),
      paragraph('Subscription, add-on, rental and purchase labels are reported as provided. Availability can vary by region.'),
    ]);
  }

  function organic(panel, offset, selection) {
    const sources = rows(panel.preview).filter(row => text(row.title) || url(row.link || row.url));
    if (!sources.length) return null;
    return panelSection('Web sources', 'google-serp-organic', [
      element('div', null, 'google-serp-sources', sources.map((row, index) => {
        const name = text(row.title, 500) || 'Web source';
        const position = integer(row.position) ?? offset + index + 1;
        return element('article', null, 'google-serp-source', [
          element('div', String(position), 'google-serp-position'),
          ...[media(row) || media(row, true)].filter(Boolean),
          element('div', null, 'google-serp-source-body', [
            link(row.link || row.url, name, 'google-serp-source-title') || element('div', name, 'google-serp-source-title'),
            ...([text(row.source), text(row.displayed_link), scalar(row.date)].filter(Boolean).length
              ? [paragraph([text(row.source), text(row.displayed_link), scalar(row.date)].filter(Boolean).join(' · '))] : []),
            ...(text(row.snippet, 800) ? [paragraph(text(row.snippet, 800), 'google-serp-snippet')] : []),
          ]),
        ]);
      })),
      panelNote(panel, sources.length, 'sources', selection),
    ]);
  }

  function knowledge(panel) {
    const entity = record(panel.preview) ? panel.preview : {};
    if (!text(entity.title) && !text(entity.description)) return null;
    const properties = ['release_date', 'director', 'running_time', 'airline', 'website'];
    const details = properties.flatMap(key => {
      const value = scalar(entity[key]);
      if (!value) return [];
      if (key === 'website') return [link(value, 'Official website')].filter(Boolean);
      return [paragraph(`${title(key)}: ${value}`)];
    });
    return panelSection(text(entity.title, 500) || 'Google entity', 'google-serp-entity', [
      ...[media(entity)].filter(Boolean),
      ...(scalar(entity.type) ? [paragraph(scalar(entity.type), 'google-serp-entity-type')] : []),
      ...(text(entity.description, 1400) ? [paragraph(text(entity.description, 1400), 'google-serp-description')] : []),
      ...details,
      paragraph('Entity identified by Google; individual web sources can refer to other titles or subjects.'),
      ...(panel.truncated ? [paragraph('Entity preview shortened; additional fields are saved.', 'google-serp-coverage')] : []),
    ]);
  }

  function namedResults(panel, selection, budget) {
    const preview = panel.preview;
    const container = record(preview) ? ['items', 'results'].find(key => Array.isArray(preview[key])) : null;
    const source = Array.isArray(preview) ? preview : container ? preview[container] : null;
    if (!source) return null;
    // Recognize a familiar row shape, not arbitrary objects containing a title.
    // One explicit list wrapper is supported; this never walks nested JSON.
    const nameOf = row => text(row.title, 500) || text(row.name, 500);
    const targetOf = row => url(row.link) || url(row.url);
    const named = row => record(row) && nameOf(row)
      && (targetOf(row) || text(row.snippet) || text(row.date) || text(row.duration_label)
        || text(row.duration) || imageUrl(row.thumbnail) || imageUrl(row.image_url) || imageUrl(row.image));
    const window = source.slice(0, 20);
    const recognized = window.map((row, index) => ({row, index})).filter(item => named(item.row));
    if (!recognized.length) return null;
    const extraRows = Object.fromEntries(recognized.flatMap(({row, index}) => {
      const displayed = new Set([text(row.title) ? 'title' : 'name']);
      const target = ['link', 'url'].find(key => url(row[key]));
      const image = ['thumbnail', 'image_url', 'image'].find(key => imageUrl(row[key]));
      if (target) displayed.add(target);
      if (image) displayed.add(image);
      if (integer(row.position) !== null) displayed.add('position');
      for (const key of ['snippet', 'date', 'source', 'displayed_link']) if (text(row[key])) displayed.add(key);
      if (text(row.duration_label)) displayed.add('duration_label');
      else if (text(row.duration)) displayed.add('duration');
      const extra = Object.fromEntries(Object.entries(row).filter(([key]) => !displayed.has(key)));
      return Object.keys(extra).length ? [[String(index + 1), extra]] : [];
    }));
    const unrecognized = window.filter(row => !named(row));
    const wrapperFields = container ? Object.fromEntries(Object.entries(preview).filter(([key]) => key !== container)) : {};
    const leftovers = {...(Object.keys(wrapperFields).length ? {section_fields: wrapperFields} : {}),
      ...(Object.keys(extraRows).length ? {additional_result_fields: extraRows} : {}),
      ...(unrecognized.length ? {unrecognized_items: unrecognized} : {})};
    const offset = selection.selected_path === panel.path ? integer(selection.offset) ?? 0 : 0;
    const cards = recognized.map(({row, index}) => {
      const name = nameOf(row);
      const meta = [text(row.source), text(row.displayed_link), text(row.date),
        text(row.duration_label) || text(row.duration)].filter(Boolean);
      return element('article', null, 'google-serp-source google-serp-named-result', [
        element('div', String(integer(row.position) ?? offset + index + 1), 'google-serp-position'),
        ...[media(row)].filter(Boolean),
        element('div', null, 'google-serp-source-body', [
          link(targetOf(row), name, 'google-serp-source-title') || element('div', name, 'google-serp-source-title'),
          ...(meta.length ? [paragraph(meta.join(' · '))] : []),
          ...(text(row.snippet, 800) ? [paragraph(text(row.snippet, 800), 'google-serp-snippet')] : []),
        ]),
      ]);
    });
    const countPanel = container ? {...panel, type: 'array', path: `${panel.path}/${container}`,
      count: panel.truncated ? null : source.length} : panel;
    return panelSection(title(panel.key) || 'Google results', 'google-serp-named-panel', [
      element('div', null, 'google-serp-named-results', cards),
      panelNote(countPanel, recognized.length, 'results', selection),
      ...(Object.keys(leftovers).length ? [element('details', null, 'google-serp-other-panel', [
        element('summary', 'Additional section details'), jsonTree(leftovers, budget, 0, 'Section fields'),
      ])] : []),
    ]);
  }

  function airport(value, heading) {
    if (!record(value)) return null;
    const location = [scalar(value.city), scalar(value.id)].filter(Boolean).join(' · ');
    const displayTime = (timestamp, label) => {
      const raw = scalar(timestamp), clock = scalar(label);
      const native = raw.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/);
      return native ? `${native[1]} ${clock || native[2]} · ${native[3] === 'Z' ? 'UTC' : 'UTC' + native[3]}` : clock || raw;
    };
    const times = [
      value.time || value.time_label ? displayTime(value.time, value.time_label) : '',
      value.scheduled_time || value.scheduled_time_label ? `Scheduled: ${displayTime(value.scheduled_time, value.scheduled_time_label)}` : '',
    ];
    const other = [
      scalar(value.terminal) ? `Terminal ${scalar(value.terminal)}` : '',
      scalar(value.gate) ? `Gate ${scalar(value.gate)}` : '', scalar(value.status),
    ];
    if (![location, ...times, ...other].some(Boolean)) return null;
    return element('div', null, 'google-serp-airport', [
      element('strong', heading), ...(location ? [paragraph(location)] : []),
      ...times.filter(Boolean).map(value => paragraph(value)),
      ...(other.some(Boolean) ? [paragraph(other.filter(Boolean).join(' · '))] : []),
    ]);
  }

  function flightDuration(row) {
    const label = text(row.duration_label, 100);
    if (label) return label;
    if (typeof row.duration === 'string') return text(row.duration, 100);
    // SerpApi's Flight Result schema defines numeric duration in minutes.
    const minutes = integer(row.duration);
    if (minutes === null) return '';
    const hours = Math.floor(minutes / 60), remainder = minutes % 60;
    return [hours ? `${hours}h` : '', remainder || !hours ? `${remainder}m` : ''].filter(Boolean).join(' ');
  }

  function flight(panel) {
    // Native engine=google uses singular flight_result. These are its documented
    // status/date/airport fields, not Google Flights itinerary or price guesses.
    const value = record(panel.preview) ? panel.preview : {};
    const dates = rows(value.dates);
    if (!dates.length && ![value.title, value.flight_designator, value.route].some(scalar)) return null;
    const designator = scalar(value.flight_designator) || dates.map(row => scalar(row.flight_designator)).find(Boolean);
    const datesView = dates.map(row => {
      const metadata = record(row.metadata) ? row.metadata : {};
      const route = [scalar(metadata.origin), scalar(metadata.destination)].filter(Boolean).join(' → ');
      const status = scalar(row.status) || title(scalar(metadata.status).toLowerCase());
      const airports = [airport(row.departure_airport, 'Departure'), airport(row.arrival_airport, 'Arrival')].filter(Boolean);
      const delay = value => typeof value === 'number' && Number.isFinite(value)
        ? `${value} min` : scalar(value);
      const delays = [
        scalar(metadata.departure_delay) ? `Departure delay: ${delay(metadata.departure_delay)}` : '',
        scalar(metadata.arrival_delay) ? `Arrival delay: ${delay(metadata.arrival_delay)}` : '',
      ].filter(Boolean);
      return element('article', null, 'google-serp-flight', [
        element('div', scalar(row.date) || 'Flight date not provided', 'google-serp-flight-date'),
        ...(route ? [paragraph(route)] : []),
        element('div', null, 'google-serp-flight-facts', facts([status, flightDuration(row)])),
        ...(airports.length ? [element('div', null, 'google-serp-airports', airports)] : []),
        ...delays.map(value => paragraph(value)),
        ...(scalar(row.updated_at) ? [paragraph(`${scalar(row.updated_label) || 'Updated'}: ${scalar(row.updated_at)}`)] : []),
        ...[link(row.source_url, scalar(row.source) || 'Flight source')].filter(Boolean),
      ]);
    });
    return panelSection(text(value.title, 500) || designator || 'Flight information', 'google-serp-flight-panel', [
      ...(scalar(value.airline) ? [paragraph(scalar(value.airline))] : []),
      ...(scalar(value.route) ? [paragraph(scalar(value.route))] : []),
      ...(Array.isArray(value.available_dates) ? [paragraph(`Available dates: ${value.available_dates.slice(0, 20).map(scalar).filter(Boolean).join(' · ')}`)]
        : scalar(value.available_dates) ? [paragraph(scalar(value.available_dates))] : []),
      ...datesView,
      ...(panel.truncated || (Array.isArray(value.dates) && value.dates.length > dates.length)
        ? [paragraph('Flight preview shortened; additional details are saved.', 'google-serp-coverage')] : []),
    ]);
  }

  function model(payload, options = {}) {
    if (payload.source?.provider !== 'serpapi' || payload.source?.tool !== 'serpapi_google_search'
        || payload.result?.kind !== 'google_search') return null;
    const result = payload.result;
    const panels = Array.isArray(result.panels) ? result.panels.filter(record).slice(0, 50) : [];
    const entityPanel = panels.find(panel => panel.key === 'knowledge_graph' && record(panel.preview));
    const entity = text(entityPanel?.preview?.title, 500);
    const offset = integer(result.offset) ?? 0;
    const renderers = {knowledge_graph: knowledge, available_on: panel => available(panel, entity, result),
      flight_result: flight, organic_results: panel => organic(panel, offset, result)};
    const known = [], unknown = [], budget = {remaining: 150};
    const ordered = [...panels].sort((a, b) => (
      ['knowledge_graph', 'available_on', 'flight_result', 'organic_results'].indexOf(a.key) + 1 || 10
    ) - (['knowledge_graph', 'available_on', 'flight_result', 'organic_results'].indexOf(b.key) + 1 || 10));
    for (const panel of ordered) {
      const renderer = Object.prototype.hasOwnProperty.call(renderers, panel.key) ? renderers[panel.key] : null;
      const rendered = renderer?.(panel) || namedResults(panel, result, budget);
      if (rendered) { known.push(rendered); continue; }
      const count = integer(panel.count);
      const name = title(panel.key) || 'Google section';
      unknown.push(element('details', null, 'google-serp-other-panel', [
        element('summary', `${name}${count !== null ? ` · ${count} ${panel.type === 'object' ? 'fields' : 'items'}` : ''}`),
        ...(text(panel.path, 500) ? [paragraph(`Saved section: ${text(panel.path, 500)}`)] : []),
        ...(panel.preview !== undefined ? [jsonTree(panel.preview, budget, 0, name)] : [paragraph('Preview not included; the section remains in the saved response.')]),
        ...(panel.truncated ? [paragraph('Preview shortened; full section is saved.', 'google-serp-coverage')] : []),
      ]));
    }
    const attributes = {class: 'structured-results-preview structured-results-external structured-results-google',
      'aria-label': 'Google search results'};
    if (options.embedded) {
      const surface = options.surface === 'orchestration' ? 'orchestration' : 'workflow';
      attributes.class += ` structured-results-workflow-section${surface === 'orchestration' ? ' structured-results-orchestration-section' : ''}`;
      if (options.toolName) attributes[`data-${surface}-tool`] = options.toolName;
      if ((options.call ?? options.step) != null) attributes[`data-${surface}-${surface === 'orchestration' ? 'call' : 'step'}`] = options.call ?? options.step;
      if (surface === 'orchestration' && options.occurrence != null) attributes['data-orchestration-occurrence'] = options.occurrence;
    }
    const request = record(result.request) ? result.request : {};
    const scope = [text(request.location), text(request.country, 30).toUpperCase(),
      text(request.language, 30).toUpperCase(), text(request.device, 30)].filter(Boolean).join(' · ');
    const links = [...[link(result.search_url, 'Open Google results')].filter(Boolean), ...stashLinks(payload, options.mode)];
    const children = [element('div', null, 'structured-results-header', [
      element('div', null, '', [element('div', 'Google Search', 'structured-results-eyebrow'),
        element('div', text(result.query, 500) || entity || 'Saved Google results', 'structured-results-heading'),
        element('div', [scope, text(result.searched_at, 100)].filter(Boolean).join(' · '), 'structured-results-subtitle'),
      ]),
    ]), ...known];
    if (unknown.length) children.push(element('div', null, 'google-serp-other-sections', [
      element('h4', 'Other Google sections'), ...unknown,
    ]));
    if (!panels.length) children.push(paragraph('No section preview was included. Inspect the saved response for the original result.'));
    if (Array.isArray(result.panels) && result.panels.length > panels.length) children.push(paragraph('Additional saved sections are not included in this preview.', 'google-serp-coverage'));
    if (result.has_more === true) children.push(paragraph('More rows are available in this saved section.', 'google-serp-coverage'));
    if (result.pagination?.has_more === true) children.push(paragraph('Google reported another results page. This response contains only the fetched page.', 'google-serp-coverage'));
    if (payload.limits?.raw_retention_error) children.push(paragraph('The complete response could not be saved; raw download is unavailable.', 'google-serp-coverage'));
    if (payload.limits?.truncated || payload.limits?.sample_truncated) children.push(paragraph('Response preview shortened. Saved sections may contain additional details.', 'google-serp-coverage'));
    if (links.length) children.push(element('div', null, 'google-serp-links', links));
    return {tag: 'section', attributes, text: null, children,
      disclosure: 'technical'};
  }

  return {model, handleImageError};
};
