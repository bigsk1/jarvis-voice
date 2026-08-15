/**
 * Shared structured tool-result previews for Jarvis Web.
 *
 * Adapters normalize tool-specific payloads into one small presentation model.
 * Future tools can register another adapter without changing ChatUI.
 */
class StructuredResultsRenderer {
  constructor() {
    this.adapters = new Map();
    this._scrollControlsBound = false;
    this._registerDefaultAdapters();
    this._bindScrollControls();
  }

  register(toolName, adapter) {
    if (!toolName || typeof adapter !== 'function') return false;
    this.adapters.set(toolName, adapter);
    return true;
  }

  registeredTools() {
    return Array.from(this.adapters.keys());
  }

  render(toolResultsData = {}, data = {}, toolsUsed = []) {
    const workflow = this._workflowPayload(toolResultsData, data);
    if (workflow) {
      const sections = this._workflowCollections(workflow, toolResultsData, data);
      const html = sections.length ? this._renderWorkflow(workflow, sections) : '';
      if (html) this._scheduleScrollControlsRefresh();
      return html;
    }

    const orchestration = this._directOrchestrationCollections(
      toolResultsData,
      data,
      toolsUsed
    );
    if (orchestration) {
      const html = orchestration.sections.length > 1
        ? this._renderOrchestration(orchestration)
        : (orchestration.sections[0]
          ? this._renderCollection(orchestration.sections[0].collection)
          : '');
      if (html) this._scheduleScrollControlsRefresh();
      return html;
    }

    const collections = [];
    for (const [toolName, adapter] of this.adapters.entries()) {
      const rawPayload = toolResultsData?.[toolName] ?? data?.[toolName];
      const collection = this._adaptCollection(toolName, rawPayload, adapter);
      if (collection) collections.push(collection);
    }
    const html = collections.map(collection => this._renderCollection(collection)).join('');
    if (html) this._scheduleScrollControlsRefresh();
    return html;
  }

  _adaptCollection(toolName, rawPayload, adapter = this.adapters.get(toolName)) {
    if (!adapter) return null;
    const payload = ['tmdb_movies', 'tmdb_tv_shows'].includes(toolName)
      ? this._tmdbDisplayPayload(rawPayload)
      : this._latestPayload(rawPayload);
    if (!payload) return null;
    try {
      const collection = adapter(payload);
      return collection?.items?.length ? collection : null;
    } catch (error) {
      console.warn(`[StructuredResults] Could not render ${toolName}:`, error);
      return null;
    }
  }

  _directTraceEntries(toolResultsData = {}, data = {}, toolsUsed = []) {
    const traceCandidates = [
      toolResultsData?._tool_trace,
      toolResultsData?.data?._tool_trace,
      data?._tool_trace,
      data?.data?._tool_trace,
    ];
    const trace = traceCandidates.find(candidate => Array.isArray(candidate));
    if (trace) {
      return trace.filter(entry => (
        entry && typeof entry === 'object' && String(entry.tool || '').trim()
      ));
    }
    return Array.isArray(toolsUsed)
      ? toolsUsed
        .map(tool => String(tool || '').trim())
        .filter(Boolean)
        .map(tool => ({tool, ok: true}))
      : [];
  }

  _payloadForOccurrence(rawPayload, occurrenceIndex, occurrenceCount) {
    // Direct orchestration stores successful payloads only; failed calls stay
    // in _tool_trace. Match against the success index so an error between two
    // successful calls cannot shift the second payload onto the wrong card.
    if (occurrenceCount <= 1) return rawPayload;
    if (!Array.isArray(rawPayload)) {
      return occurrenceIndex === 0 ? rawPayload : null;
    }
    return occurrenceIndex < rawPayload.length
      ? rawPayload[occurrenceIndex]
      : null;
  }

  _directOrchestrationCollections(toolResultsData = {}, data = {}, toolsUsed = []) {
    const entries = this._directTraceEntries(toolResultsData, data, toolsUsed);
    if (!entries.length) return null;

    const successTotals = new Map();
    for (const entry of entries) {
      if (entry.ok === false) continue;
      const toolName = String(entry.tool || '').trim();
      successTotals.set(toolName, (successTotals.get(toolName) || 0) + 1);
    }

    const successIndexes = new Map();
    const sections = [];
    let failedCalls = 0;
    let callsWithoutCards = 0;

    entries.forEach((entry, callIndex) => {
      const toolName = String(entry.tool || '').trim();
      if (entry.ok === false) {
        failedCalls += 1;
        return;
      }

      const occurrenceIndex = successIndexes.get(toolName) || 0;
      successIndexes.set(toolName, occurrenceIndex + 1);
      const adapter = this.adapters.get(toolName);
      if (!adapter || this._usesDedicatedSurface(toolName)) {
        callsWithoutCards += 1;
        return;
      }

      const rawPayload = toolResultsData?.[toolName] ?? data?.[toolName];
      const occurrencePayload = this._payloadForOccurrence(
        rawPayload,
        occurrenceIndex,
        successTotals.get(toolName) || 0
      );
      const collection = this._adaptCollection(toolName, occurrencePayload, adapter);
      if (!collection) {
        callsWithoutCards += 1;
        return;
      }
      sections.push({
        toolName,
        call: callIndex + 1,
        occurrence: occurrenceIndex + 1,
        collection,
      });
    });

    return {
      sections,
      totalCalls: entries.length,
      failedCalls,
      callsWithoutCards,
    };
  }

  _workflowPayload(toolResultsData = {}, data = {}) {
    const directCandidates = [
      toolResultsData,
      data,
      toolResultsData?.data,
      data?.data,
    ];
    for (const candidate of directCandidates) {
      if (
        candidate
        && typeof candidate === 'object'
        && candidate.workflow_id
        && Array.isArray(candidate.results)
      ) return candidate;
    }

    for (const container of directCandidates) {
      if (!container || typeof container !== 'object') continue;
      const rawWorkflow = container.workflow;
      const candidates = Array.isArray(rawWorkflow)
        ? [...rawWorkflow].reverse()
        : [rawWorkflow];
      const workflow = candidates.find(candidate => (
        candidate
        && typeof candidate === 'object'
        && Array.isArray(candidate.results)
        && (candidate.action === 'run' || candidate.workflow_id)
      ));
      if (workflow) return workflow;
    }
    return null;
  }

  _workflowStepPayload(step) {
    const outputs = Array.isArray(step?.outputs) ? step.outputs : [];
    if (outputs.length) {
      return outputs.map(output => (
        output?.data && typeof output.data === 'object'
          ? output.data
          : (output ?? {})
      ));
    }
    return step?.data ?? null;
  }

  _usesDedicatedSurface(toolName) {
    // The chat renderer already turns the leading YouTube search result into a
    // full-size playable embed. Keep that richer surface instead of duplicating
    // the same result as a compact workflow section.
    return toolName === 'serpapi_youtube_search';
  }

  _workflowUsesDedicatedSurface(toolName) {
    return this._usesDedicatedSurface(toolName);
  }

  _workflowCollections(workflow, toolResultsData = {}, data = {}) {
    const sections = [];
    const representedTools = new Set();
    const steps = Array.isArray(workflow?.results) ? workflow.results : [];

    for (const step of steps) {
      const toolName = String(step?.tool || '').trim();
      if (!toolName) continue;
      representedTools.add(toolName);
      if (step.skipped === true || step.ok === false) continue;
      if (this._workflowUsesDedicatedSurface(toolName)) continue;

      const collection = this._adaptCollection(
        toolName,
        this._workflowStepPayload(step)
      );
      if (collection) {
        sections.push({
          toolName,
          step: step.step,
          collection,
        });
      }
    }

    // Preserve supported payloads that came back beside the explicit step
    // envelopes, but keep them inside the same workflow surface. This is the
    // compatibility fallback for older or provider-specific workflow results.
    for (const [toolName, adapter] of this.adapters.entries()) {
      if (representedTools.has(toolName) || this._workflowUsesDedicatedSurface(toolName)) continue;
      const rawPayload = toolResultsData?.[toolName]
        ?? workflow?.[toolName]
        ?? data?.[toolName];
      const collection = this._adaptCollection(toolName, rawPayload, adapter);
      if (collection) sections.push({toolName, step: null, collection});
    }
    return sections;
  }

  _workflowTitle(workflow) {
    const raw = String(workflow?.workflow_name || workflow?.name || workflow?.workflow_id || 'Workflow');
    return raw
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, letter => letter.toUpperCase());
  }

  _renderWorkflow(workflow, sections) {
    const workflowId = String(workflow?.workflow_id || workflow?.id || 'workflow');
    const skipped = Array.isArray(workflow?.optional_tools_skipped)
      ? workflow.optional_tools_skipped.filter(Boolean).length
      : 0;
    const subtitle = [
      `${sections.length} tool section${sections.length === 1 ? '' : 's'} combined`,
      skipped ? `${skipped} optional source${skipped === 1 ? '' : 's'} unavailable` : '',
    ].filter(Boolean).join(' · ');
    const sectionHtml = sections.map(section => this._renderCollection(
      section.collection,
      {
        embedded: true,
        toolName: section.toolName,
        step: section.step,
      }
    )).join('');

    return `
      <section class="structured-results-workflow-preview" data-workflow-id="${this._escape(workflowId)}" aria-label="Workflow results: ${this._escape(this._workflowTitle(workflow))}">
        <div class="structured-results-workflow-header">
          <div class="structured-results-eyebrow">Workflow results</div>
          <div class="structured-results-heading">${this._escape(this._workflowTitle(workflow))}</div>
          <div class="structured-results-subtitle">${this._escape(subtitle)}</div>
        </div>
        <div class="structured-results-workflow-sections">${sectionHtml}</div>
      </section>
    `;
  }

  _renderOrchestration(orchestration) {
    const sections = orchestration.sections || [];
    const subtitle = [
      `${sections.length} visual section${sections.length === 1 ? '' : 's'} from ${orchestration.totalCalls} tool call${orchestration.totalCalls === 1 ? '' : 's'}`,
      orchestration.failedCalls
        ? `${orchestration.failedCalls} failed`
        : '',
      orchestration.callsWithoutCards
        ? `${orchestration.callsWithoutCards} call${orchestration.callsWithoutCards === 1 ? '' : 's'} without visual cards`
        : '',
    ].filter(Boolean).join(' · ');
    const sectionHtml = sections.map(section => this._renderCollection(
      section.collection,
      {
        embedded: true,
        surface: 'orchestration',
        toolName: section.toolName,
        call: section.call,
        occurrence: section.occurrence,
      }
    )).join('');

    return `
      <section class="structured-results-workflow-preview structured-results-orchestration-preview" data-orchestration-results="true" aria-label="Combined tool results">
        <div class="structured-results-workflow-header">
          <div class="structured-results-eyebrow">Tool results</div>
          <div class="structured-results-heading">Combined results</div>
          <div class="structured-results-subtitle">${this._escape(subtitle)}</div>
        </div>
        <div class="structured-results-workflow-sections">${sectionHtml}</div>
      </section>
    `;
  }

  _registerDefaultAdapters() {
    this.register('serpapi_amazon_search', payload => this._adaptShoppingSearch(payload));
    // Saved conversations may still contain the pre-rename result key.
    this.register('serpapi_search', payload => this._adaptShoppingSearch(payload));
    this.register('serpapi_home_depot', payload => this._adaptHomeDepotProduct(payload));
    this.register('serpapi_ebay_search', payload => this._adaptEbaySearch(payload));
    this.register('serpapi_ebay_product', payload => this._adaptEbayProduct(payload));
    this.register('serpapi_hotel_search', payload => this._adaptHotels(payload));
    this.register('serpapi_yelp_search', payload => this._adaptYelp(payload));
    this.register('serpapi_search_index', payload => this._adaptSearchIndex(payload));
    this.register('serpapi_google_images_light', payload => this._adaptGoogleImagesLight(payload));
    this.register('serpapi_google_news_light', payload => this._adaptGoogleNewsLight(payload));
    this.register('serpapi_google_shopping_light', payload => this._adaptGoogleShoppingLight(payload));
    this.register('serpapi_google_sports', payload => this._adaptGoogleSports(payload));
    this.register('serpapi_google_trends', payload => this._adaptGoogleTrends(payload));
    this.register('serpapi_google_trending_now', payload => this._adaptGoogleTrendingNow(payload));
    this.register('serpapi_travel_explore', payload => this._adaptTravelExplore(payload));
    this.register('serpapi_google_events', payload => this._adaptGoogleEvents(payload));
    this.register('serpapi_tripadvisor', payload => this._adaptTripadvisor(payload));
    this.register('trakt_movies', payload => this._adaptTraktMovies(payload));
    this.register('trakt_account', payload => this._adaptTraktAccount(payload));
    this.register('tmdb_movies', payload => this._adaptTmdbMovies(payload));
    this.register('trakt_tv_shows', payload => this._adaptTraktMovies(payload, 'show'));
    this.register('tmdb_tv_shows', payload => this._adaptTmdbMovies(payload, 'show'));
    this.register('flight_search', payload => this._adaptFlights(payload));
    this.register('serpapi_google_local', payload => this._adaptGoogleLocal(payload));
    this.register('serpapi_google_local_services', payload => this._adaptGoogleLocalServices(payload));
    this.register('serpapi_maps_search', payload => this._adaptMaps(payload));
    this.register('serpapi_youtube_search', payload => this._adaptYouTubeSearch(payload));
    this.register('weather', payload => this._adaptWeather(payload));
    this.register('gpu_hot_status', payload => this._adaptGpuHotStatus(payload));
  }

  _bindScrollControls() {
    if (
      this._scrollControlsBound
      || typeof document === 'undefined'
      || typeof document.addEventListener !== 'function'
    ) return;

    this._scrollControlsBound = true;
    document.addEventListener('click', event => {
      const button = event.target?.closest?.('.structured-results-scroll-button');
      if (!button || button.disabled) return;
      const section = button.closest('.structured-results-preview');
      const track = section?.querySelector('.structured-results-track');
      if (!track) return;
      const direction = button.dataset.direction === 'previous' ? -1 : 1;
      const distance = Math.max(track.clientWidth * 0.82, 240);
      track.scrollBy({left: direction * distance, behavior: 'smooth'});
      window.setTimeout?.(() => this._refreshScrollControls(track), 350);
    });
    document.addEventListener('scroll', event => {
      if (event.target?.classList?.contains('structured-results-track')) {
        this._refreshScrollControls(event.target);
      }
    }, true);
    window.addEventListener?.('resize', () => this._refreshAllScrollControls());
  }

  _scheduleScrollControlsRefresh() {
    if (typeof document === 'undefined') return;
    const refresh = () => this._refreshAllScrollControls();
    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(refresh);
    } else {
      window.setTimeout?.(refresh, 0);
    }
  }

  _refreshAllScrollControls() {
    if (typeof document === 'undefined') return;
    document.querySelectorAll('.structured-results-track')
      .forEach(track => this._refreshScrollControls(track));
  }

  _refreshScrollControls(track) {
    const section = track?.closest?.('.structured-results-preview');
    const controls = section?.querySelector('.structured-results-scroll-controls');
    if (!controls) return;
    const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
    controls.hidden = maxScroll <= 4;
    if (controls.hidden) return;
    const previous = controls.querySelector('[data-direction="previous"]');
    const next = controls.querySelector('[data-direction="next"]');
    if (previous) previous.disabled = track.scrollLeft <= 2;
    if (next) next.disabled = track.scrollLeft >= maxScroll - 2;
  }

  _latestPayload(raw) {
    if (!raw) return null;
    if (Array.isArray(raw)) {
      if (!raw.length) return null;
      const looksLikeRepeatedRuns = raw.some(item => item && typeof item === 'object' && (
        item.data || item.results || item.top_results || item.candidates
        || item.engine || item.provider || item.destination || item.find_loc
      ));
      if (!looksLikeRepeatedRuns) return { results: raw };
      raw = raw[raw.length - 1];
    }
    if (!raw || typeof raw !== 'object') return null;
    if (raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)) {
      raw = raw.data;
    }
    return raw;
  }

  _tmdbDisplayPayload(raw) {
    if (!Array.isArray(raw)) return this._latestPayload(raw);
    const looksLikeRepeatedRuns = raw.some(item => item && typeof item === 'object' && (
      item.data || item.action || item.results || item.top_results
    ));
    if (!looksLikeRepeatedRuns) return this._latestPayload(raw);
    const payloads = raw
      .map(item => this._latestPayload(item))
      .filter(item => item && typeof item === 'object');
    if (!payloads.length) return null;

    // A complete mixed artwork call is more representative than a provider's
    // redundant poster/backdrop/logo drill-down that follows it.
    const mixedArtwork = [...payloads].reverse().find(item => (
      item.action === 'images' && item.image_type === 'all'
    ));
    return mixedArtwork || payloads[payloads.length - 1];
  }

  _rows(payload) {
    for (const key of ['top_results', 'results', 'candidates', 'items']) {
      if (Array.isArray(payload?.[key]) && payload[key].length) {
        return payload[key].filter(item => item && typeof item === 'object').slice(0, 5);
      }
    }
    return [];
  }

  _list(value) {
    if (Array.isArray(value)) return value.filter(Boolean).map(item => String(item));
    if (value == null || value === '') return [];
    return [String(value)];
  }

  _formatPrice(value, currency = 'USD') {
    if (value == null || value === '') return '';
    if (typeof value === 'string' && /[^0-9.,]/.test(value)) return value;
    const amount = String(value);
    return String(currency || 'USD').toUpperCase() === 'USD'
      ? `$${amount}`
      : `${String(currency).toUpperCase()} ${amount}`;
  }

  _formatMarketplacePrice(value) {
    if (value == null || value === '') return '';
    if (typeof value !== 'object') return String(value);
    if (value.raw) return String(value.raw);
    const from = value.from?.raw || value.from?.formatted;
    const to = value.to?.raw || value.to?.formatted;
    if (from) return to ? `${from} – ${to}` : String(from);
    if (value.amount != null) {
      return value.currency ? `${value.currency} ${value.amount}` : String(value.amount);
    }
    return '';
  }

  _formatCount(value) {
    if (value == null || value === '') return '';
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString('en-US') : String(value);
  }

  _formatDateTime(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;
    try {
      return new Intl.DateTimeFormat(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
      }).format(date);
    } catch (_error) {
      return text;
    }
  }

  _compactText(value, maxLength = 150) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
  }

  _displayText(value) {
    if (value == null || value === '') return '';
    if (Array.isArray(value)) return value.filter(Boolean).map(item => String(item)).join(' · ');
    if (typeof value !== 'object') return String(value);
    for (const key of ['raw', 'formatted', 'text', 'label', 'name', 'username', 'status', 'message']) {
      if (value[key] != null && value[key] !== '') return String(value[key]);
    }
    return Object.values(value)
      .filter(item => ['string', 'number', 'boolean'].includes(typeof item) && item !== '')
      .slice(0, 3)
      .map(item => String(item))
      .join(' · ');
  }

  _formatFlightTime(value) {
    const text = String(value || '').trim();
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    if (!match) return text;
    const [, year, month, day, rawHour, minute] = match;
    const hour = Number(rawHour);
    const clockHour = hour % 12 || 12;
    const meridiem = hour >= 12 ? 'PM' : 'AM';
    return `${month}/${day}/${year} · ${clockHour}:${minute} ${meridiem}`;
  }

  _adaptHotels(payload) {
    const items = this._rows(payload).map(row => {
      const amenities = this._list(row.amenities);
      const petFriendly = row.pet_friendly === true || amenities.some(value => (
        ['pet-friendly', 'pets allowed', 'pets-allowed'].includes(value.toLowerCase())
      ));
      const chips = [];
      if (row.price_per_night && row.price_total) chips.push(`${row.price_total} total`);
      if (row.rating != null) chips.push(`★ ${row.rating}`);
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (petFriendly) chips.push('Pet-friendly');
      if (row.free_cancellation === true) chips.push('Free cancellation');
      return {
        title: row.title || row.name || 'Hotel option',
        url: row.url,
        image: row.thumbnail || row.image_url,
        primary: row.price_per_night ? `${row.price_per_night}/night` : row.price_total,
        chips,
        details: [row.hotel_class, row.address].filter(Boolean),
        actionLabel: 'View hotel',
      };
    });
    const dates = [payload.check_in_date, payload.check_out_date].filter(Boolean).join(' → ');
    return {
      kind: 'hotel',
      eyebrow: 'Hotels',
      heading: payload.destination || payload.query || 'Hotel options',
      subtitle: dates,
      items,
    };
  }

  _adaptYelp(payload) {
    const items = this._rows(payload).map(row => {
      const chips = [];
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (row.price && row.rating != null) chips.push(String(row.price));
      const categories = this._list(row.categories).slice(0, 3).join(' · ');
      return {
        title: row.title || row.name || 'Yelp result',
        url: row.url || row.link,
        image: row.thumbnail || row.image_url,
        primary: row.rating != null ? `★ ${row.rating}` : row.price,
        chips,
        details: [row.neighborhoods, row.open_state, categories].filter(Boolean),
        actionLabel: 'View on Yelp',
      };
    });
    const description = payload.find_desc || 'Local places';
    const location = payload.find_loc ? ` near ${payload.find_loc}` : '';
    return {
      kind: 'local',
      eyebrow: 'Yelp',
      heading: `${description}${location}`,
      subtitle: payload.sort_by ? `Sorted by ${payload.sort_by.replace(/_/g, ' ')}` : '',
      items,
    };
  }

  _adaptSearchIndex(payload) {
    const items = this._rows(payload).map(row => {
      const chips = [];
      if (row.date) chips.push(String(row.date));
      if (row.language) chips.push(String(row.language).toUpperCase());
      const sitelinks = this._list(row.sitelinks);
      if (sitelinks.length) chips.push(`${sitelinks.length} related links`);
      return {
        title: row.title || 'Indexed webpage',
        url: row.url || row.link,
        image: row.image_url || row.thumbnail,
        primary: row.displayed_link || row.source || '',
        chips,
        details: row.snippet ? [this._compactText(row.snippet, 280)] : [],
        actionLabel: 'Open source',
      };
    });
    const mode = String(payload.mode || 'standard').toLowerCase();
    const resultCount = payload.results_count ?? items.length;
    const total = payload.total_results;
    const countText = total != null
      ? `${this._formatCount(total)} indexed matches`
      : `${resultCount} source${Number(resultCount) === 1 ? '' : 's'} shown`;
    const related = this._list(payload.related_searches).slice(0, 3).join(' · ');
    return {
      kind: 'generic',
      layout: 'rail',
      eyebrow: mode === 'deep' ? 'Search Index · Deep recall' : 'Search Index',
      heading: payload.query || 'Indexed web sources',
      subtitle: related ? `${countText} · Related: ${related}` : countText,
      items,
    };
  }

  _adaptGoogleNewsLight(payload) {
    const resultItems = this._rows(payload).map((row, index) => {
      const chips = [];
      if (row.date) chips.push(String(row.date));
      return {
        title: row.title || `News article ${index + 1}`,
        url: row.url || row.link,
        image: row.thumbnail,
        primary: row.source || '',
        chips,
        details: row.snippet ? [this._compactText(row.snippet, 280)] : [],
        actionLabel: 'Read article',
      };
    });
    const topStoryGroups = Array.isArray(payload.top_stories)
      ? payload.top_stories.filter(group => group && typeof group === 'object').slice(0, 5)
      : [];
    const topStoryItems = topStoryGroups.flatMap(group => {
      const groupTitle = group && group.title ? String(group.title) : 'Top Stories';
      const stories = Array.isArray(group.stories)
        ? group.stories.filter(story => story && typeof story === 'object').slice(0, 5)
        : [];
      return stories.map((story, index) => ({
        title: story.title || `Top story ${index + 1}`,
        url: story.url || story.link,
        primary: story.source || '',
        chips: [story.date, 'Top story'].filter(Boolean).map(String),
        details: [groupTitle],
        actionLabel: 'Read article',
      }));
    });
    const resultCount = payload.provider_results_count ?? resultItems.length;
    const storyCount = payload.provider_top_story_articles_count ?? topStoryItems.length;
    const scope = [payload.location, payload.country && String(payload.country).toUpperCase()]
      .filter(Boolean)
      .join(' · ');
    return {
      kind: 'generic',
      layout: 'rail',
      eyebrow: 'Google News Light',
      heading: payload.query_displayed || payload.query || 'Recent news',
      subtitle: [
        `${resultCount} news result${Number(resultCount) === 1 ? '' : 's'}`,
        storyCount ? `${storyCount} top-story article${Number(storyCount) === 1 ? '' : 's'}` : '',
        scope,
      ].filter(Boolean).join(' · '),
      actionUrl: payload.google_news_light_url,
      actionLabel: 'Open Google News',
      items: [...topStoryItems, ...resultItems],
    };
  }

  _adaptGoogleImagesLight(payload) {
    const items = this._rows(payload).map((row, index) => {
      const width = Number(row.original_width);
      const height = Number(row.original_height);
      const dimensions = Number.isFinite(width) && width > 0
        && Number.isFinite(height) && height > 0
        ? `${width} × ${height}`
        : '';
      const chips = [
        dimensions,
        row.is_product === true ? 'Product' : '',
        row.in_stock === true ? 'In stock' : '',
        row.unsafe === true ? 'Unsafe' : '',
      ]
        .filter(Boolean);
      return {
        title: row.title || `Image result ${index + 1}`,
        url: row.source_url,
        // Only auto-load provider/Google thumbnails. The untrusted original is
        // available as an explicit click target, never an automatic page load.
        image: row.unsafe === true ? '' : (row.serpapi_thumbnail || row.thumbnail),
        imageUrl: row.image_url || row.original,
        primary: row.source || '',
        chips,
        actionLabel: 'Open source',
      };
    });
    const providerCount = payload.provider_results_count ?? items.length;
    const filters = [
      payload.image_type,
      payload.image_size,
      payload.aspect_ratio,
      payload.image_color,
    ].filter(Boolean).map(value => String(value).replace(/_/g, ' '));
    return {
      kind: 'image',
      layout: 'gallery',
      eyebrow: 'Google Images Light · Untrusted web content',
      heading: payload.query_displayed || payload.query || 'Image results',
      subtitle: [
        `${providerCount} image${Number(providerCount) === 1 ? '' : 's'} found`,
        filters.join(' · '),
        'Open the source page to verify rights',
      ].filter(Boolean).join(' · '),
      actionUrl: payload.google_images_light_url,
      actionLabel: 'Open Google Images',
      items,
    };
  }

  _adaptGoogleShoppingLight(payload) {
    const items = this._rows(payload).map((row, index) => {
      const chips = [];
      if (row.old_price) chips.push(`Was ${row.old_price}`);
      if (row.rating != null) chips.push(`★ ${row.rating}`);
      if (row.reviews != null) chips.push(`${this._formatCount(row.reviews)} reviews`);
      if (row.tag) chips.push(String(row.tag));
      if (row.multiple_sources === true) chips.push('Multiple stores');
      const installment = row.installment && typeof row.installment === 'object'
        ? [row.installment.price, row.installment.period ? `${row.installment.period} months` : '']
          .filter(Boolean).join(' for ')
        : '';
      const extensions = this._list(row.extensions).slice(0, 4).join(' · ');
      return {
        title: row.title || `Shopping result ${index + 1}`,
        url: row.url || row.merchant_url || row.product_link,
        image: row.serpapi_thumbnail || row.thumbnail,
        primary: this._formatMarketplacePrice(row.price ?? row.extracted_price),
        chips,
        details: [
          row.source,
          row.delivery,
          installment ? `Installment: ${installment}` : '',
          extensions,
        ].filter(Boolean),
        actionLabel: 'View offer',
      };
    });
    const providerCount = payload.provider_results_count ?? items.length;
    const filters = [
      payload.sort_by && payload.sort_by !== 'relevance'
        ? String(payload.sort_by).replace(/_/g, ' ')
        : '',
      payload.on_sale === true ? 'On sale' : '',
      payload.free_shipping === true ? 'Free shipping' : '',
      payload.small_business === true ? 'Small business' : '',
    ].filter(Boolean);
    const location = payload.provider_location_used || payload.location || '';
    return {
      kind: 'product',
      layout: 'rail',
      eyebrow: 'Google Shopping Light',
      heading: payload.query_displayed || payload.query || 'Shopping offers',
      subtitle: [
        `${providerCount} offer${Number(providerCount) === 1 ? '' : 's'} found`,
        location,
        filters.join(' · '),
      ].filter(Boolean).join(' · '),
      actionUrl: payload.google_shopping_light_url,
      actionLabel: 'Open Google Shopping',
      items,
    };
  }

  _adaptGoogleTrends(payload) {
    const dataType = String(payload.data_type || 'interest_over_time').toLowerCase();
    const items = this._rows(payload).map((row, index) => {
      if (dataType === 'interest_over_time') {
        const chips = [];
        if (row.direction) chips.push(String(row.direction));
        if (row.average_value != null) chips.push(`Average ${row.average_value}`);
        if (row.peak_value != null) chips.push(`Peak ${row.peak_value}`);
        const changes = [];
        if (row.change_from_previous != null) {
          const prefix = Number(row.change_from_previous) > 0 ? '+' : '';
          changes.push(`${prefix}${row.change_from_previous} from previous`);
        }
        if (row.change_over_period != null) {
          const prefix = Number(row.change_over_period) > 0 ? '+' : '';
          changes.push(`${prefix}${row.change_over_period} over period`);
        }
        return {
          title: row.query || row.title || `Trend ${index + 1}`,
          primary: row.latest_value != null ? `Latest ${row.latest_value}` : '',
          chips,
          details: [row.latest_date, ...changes].filter(Boolean),
        };
      }

      if (dataType === 'compared_by_region' || dataType === 'interest_by_region') {
        const values = Array.isArray(row.values) ? row.values : [];
        const comparison = values.slice(0, 5).map(value => {
          const score = value.extracted_value ?? value.value;
          return [value.query, score].filter(part => part != null && part !== '').join(' ');
        }).filter(Boolean).join(' · ');
        return {
          title: row.location || row.title || `Region ${index + 1}`,
          primary: row.top_query
            ? `${row.top_query} · ${row.top_value ?? ''}`.trim()
            : (row.extracted_value ?? row.value ?? ''),
          chips: row.geo ? [String(row.geo)] : [],
          details: comparison ? [comparison] : [],
        };
      }

      const chips = [];
      if (row.trend_type) chips.push(String(row.trend_type));
      if (row.topic_type) chips.push(String(row.topic_type));
      return {
        title: row.title || row.query || `Related trend ${index + 1}`,
        url: row.url,
        primary: row.value ?? row.extracted_value ?? '',
        chips,
        details: row.topic_id ? [String(row.topic_id)] : [],
        actionLabel: 'Open trend',
      };
    });
    const view = dataType.replace(/_/g, ' ');
    const scope = [payload.date, payload.geo].filter(Boolean).join(' · ');
    return {
      kind: 'generic',
      layout: 'rail',
      eyebrow: 'Google Trends',
      heading: payload.query || this._list(payload.queries).join(', ') || 'Trend analysis',
      subtitle: [view, scope].filter(Boolean).join(' · '),
      actionUrl: payload.trends_url,
      actionLabel: 'Open Google Trends',
      items,
    };
  }

  _adaptGoogleSports(payload) {
    const resultKind = String(payload.results_kind || '').toLowerCase();
    const items = this._rows(payload).map((row, index) => {
      const kind = String(row.kind || resultKind || '').toLowerCase();
      const teams = Array.isArray(row.teams) ? row.teams.slice(0, 4) : [];
      const chips = [];
      const details = [];
      let primary = '';
      let image = row.thumbnail || '';

      if (kind === 'game') {
        const score = teams.map(team => {
          const name = team.short_code || team.short_name || team.name;
          const value = team.score_original ?? team.score;
          return [name, value].filter(part => part != null && part !== '').join(' ');
        }).filter(Boolean).join(' · ');
        primary = score || row.status_original || row.status || '';
        // A single team logo reads as a matchup thumbnail and stretches poorly.
        // Game rows use the score/date hierarchy instead; non-game views may
        // still show a player or team image when the provider supplies one.
        image = '';
        if (row.status_original || row.status) chips.push(String(row.status_original || row.status));
        if (row.start_time || row.date || row.time) {
          const dateTime = row.start_time
            ? this._formatDateTime(row.start_time)
            : [row.date, row.time].filter(Boolean).join(' · ');
          if (dateTime) chips.push(dateTime);
        }
        const league = row.league && typeof row.league === 'object'
          ? (row.league.short_name || row.league.name)
          : row.league;
        if (league || row.tournament) chips.push(String(league || row.tournament));
        if (row.group) chips.push(String(row.group));
        const venue = row.venue && typeof row.venue === 'object'
          ? [row.venue.name, row.venue.location].filter(Boolean).join(' · ')
          : '';
        if (venue || row.stadium) details.push(venue || String(row.stadium));
        const highlight = Array.isArray(row.highlights) ? row.highlights[0] : null;
        if (highlight?.title) details.push(`Highlight: ${highlight.title}`);
      } else if (kind === 'standing' || kind === 'ranking') {
        primary = row.rank != null ? `#${row.rank}` : '';
        if (row.group) chips.push(String(row.group));
        if (row.division) chips.push(String(row.division));
        if (row.league_movement) details.push(String(row.league_movement));
        const stats = Array.isArray(row.stats) ? row.stats.slice(0, 5) : [];
        const statLine = stats.map(stat => {
          const label = stat.short_title || stat.title;
          const value = stat.value ?? (Array.isArray(stat.values) ? stat.values.join('-') : '');
          return [label, value].filter(part => part != null && part !== '').join(' ');
        }).filter(Boolean).join(' · ');
        if (statLine) details.push(statLine);
      } else {
        const stats = Array.isArray(row.stats) ? row.stats.slice(0, 5) : [];
        primary = row.value ?? row.player_position ?? stats[0]?.value ?? '';
        if (row.rank != null) chips.push(`#${row.rank}`);
        if (row.player_position) chips.push(String(row.player_position));
        if (row.jersey_number) chips.push(`#${row.jersey_number}`);
        if (row.team) {
          chips.push(String(
            row.team && typeof row.team === 'object'
              ? (row.team.short_name || row.team.name || '')
              : row.team
          ));
        }
        if (row.group) chips.push(String(row.group));
        const statLine = stats.map(stat => {
          const label = stat.short_title || stat.title;
          const value = stat.value ?? (Array.isArray(stat.values) ? stat.values.join('-') : '');
          return [label, value].filter(part => part != null && part !== '').join(' ');
        }).filter(Boolean).join(' · ');
        if (statLine) details.push(statLine);
      }

      return {
        title: row.title || row.name || `Sports result ${index + 1}`,
        url: row.url,
        image,
        primary,
        chips,
        details,
        actionLabel: 'Open sports result',
      };
    });
    const view = String(payload.tab || payload.results_kind || 'game details').replace(/_/g, ' ');
    const scope = [
      String(payload.sport || '').replace(/_/g, ' '),
      String(payload.entity_type || '').replace(/_/g, ' '),
      view,
    ].filter(Boolean).join(' · ');
    const resultCount = payload.results_count ?? items.length;
    const providerCount = payload.provider_results_count;
    const searches = payload.serpapi_searches_used;
    return {
      kind: 'sport',
      layout: 'list',
      eyebrow: 'Google Sports',
      heading: payload.query || payload.kgmid || 'Sports results',
      subtitle: [
        scope,
        `${resultCount} result${Number(resultCount) === 1 ? '' : 's'} returned`,
        providerCount != null && Number(providerCount) !== Number(resultCount)
          ? `${providerCount} available from Google`
          : '',
        searches != null ? `${searches} SerpApi search${Number(searches) === 1 ? '' : 'es'}` : '',
      ].filter(Boolean).join(' · '),
      actionUrl: payload.google_sports_url,
      actionLabel: 'Open Google Sports',
      items,
    };
  }

  _adaptGoogleTrendingNow(payload) {
    const action = String(payload.action || 'trending_now').toLowerCase();
    if (action === 'news') {
      const items = this._rows(payload).map((row, index) => ({
        title: row.title || `News article ${index + 1}`,
        url: row.url || row.link,
        image: row.thumbnail,
        primary: row.source || '',
        chips: row.date ? [String(row.date)] : [],
        actionLabel: 'Read article',
      }));
      return {
        kind: 'generic',
        layout: 'rail',
        eyebrow: 'Google Trends News',
        heading: payload.trend_query || 'Associated trend news',
        subtitle: `${payload.provider_results_count ?? items.length} article${Number(payload.provider_results_count ?? items.length) === 1 ? '' : 's'} found`,
        items,
      };
    }

    const items = this._rows(payload).map((row, index) => {
      const chips = [];
      if (row.active === true) chips.push('Active now');
      else if (row.active === false) chips.push('Ended');
      if (row.increase_percentage != null) chips.push(`+${row.increase_percentage}%`);
      const categories = this._list(row.category_names).slice(0, 3).join(' · ');
      if (categories) chips.push(categories);
      const related = this._list(row.trend_breakdown).slice(0, 4).join(' · ');
      return {
        title: row.query || row.title || `Trend ${index + 1}`,
        url: row.google_trends_url,
        primary: row.search_volume != null
          ? `${this._formatCount(row.search_volume)} searches`
          : '',
        chips,
        details: related ? [`Related: ${related}`] : [],
        actionLabel: 'Explore trend',
      };
    });
    const providerCount = payload.provider_results_count ?? items.length;
    const activeCount = payload.active_results_count;
    const countText = activeCount != null
      ? `${activeCount} active · ${providerCount} total`
      : `${providerCount} trend${Number(providerCount) === 1 ? '' : 's'} found`;
    return {
      kind: 'generic',
      layout: 'rail',
      eyebrow: 'Google Trends · Trending Now',
      heading: `Current trends in ${payload.geo || 'US'}`,
      subtitle: `Past ${payload.hours || 24} hours · ${countText}`,
      actionUrl: payload.trending_now_url,
      actionLabel: 'Open Trending Now',
      items,
    };
  }

  _adaptTripadvisor(payload) {
    const action = String(payload.action || 'search').toLowerCase();
    if (action === 'reviews') {
      const reviewData = payload.review_data && typeof payload.review_data === 'object'
        ? payload.review_data
        : payload;
      const rows = Array.isArray(reviewData.reviews) ? reviewData.reviews.slice(0, 5) : [];
      const items = rows.map((row, index) => {
        const chips = [];
        if (row.date) chips.push(String(row.date));
        if (row.author_name) chips.push(String(row.author_name));
        if (row.trip_type) chips.push(String(row.trip_type).toLowerCase().replace(/_/g, ' '));
        return {
          title: row.title || `Review ${index + 1}`,
          url: row.url,
          image: row.author_avatar,
          primary: row.rating != null ? `★ ${row.rating}` : '',
          chips,
          details: row.text ? [this._compactText(row.text, 260)] : [],
          actionLabel: 'Read review',
        };
      });
      return {
        kind: 'local',
        layout: 'rail',
        eyebrow: 'Tripadvisor reviews',
        heading: payload.place?.title || `Place ${payload.place_id || ''}`.trim(),
        subtitle: reviewData.total_reviews != null
          ? `${reviewData.total_reviews} total reviews`
          : '',
        items,
      };
    }

    const detailData = payload.detail_data && typeof payload.detail_data === 'object'
      ? payload.detail_data
      : payload;
    if (action === 'details' || detailData.place) {
      const place = detailData.place || {};
      const interesting = Array.isArray(detailData.interesting_places)
        ? detailData.interesting_places.slice(0, 4)
        : [];
      const placeChips = [];
      if (place.reviews != null) placeChips.push(`${place.reviews} reviews`);
      if (place.ranking) placeChips.push(String(place.ranking));
      if (place.price_level) placeChips.push(String(place.price_level));
      const mainItem = {
        title: place.title || place.name || 'Tripadvisor place',
        url: place.url || place.website,
        image: place.thumbnail || this._list(place.images)[0],
        primary: place.rating != null ? `★ ${place.rating}` : '',
        chips: placeChips,
        details: [
          place.address,
          this._list(place.categories).slice(0, 3).join(' · '),
          place.description ? this._compactText(place.description, 220) : '',
        ].filter(Boolean),
        actionLabel: 'View on Tripadvisor',
      };
      const nearbyItems = interesting.map(row => {
        const chips = [];
        if (row.reviews != null) chips.push(`${row.reviews} reviews`);
        if (row.distance != null) chips.push(String(row.distance));
        if (row.group) chips.push(String(row.group));
        return {
          title: row.title || row.name || 'Nearby place',
          url: row.url || row.link,
          image: row.thumbnail,
          primary: row.rating != null ? `★ ${row.rating}` : row.price,
          chips,
          details: [
            row.address,
            this._list(row.categories).slice(0, 3).join(' · '),
            row.additional_info ? this._compactText(row.additional_info, 180) : '',
          ].filter(Boolean),
          actionLabel: 'View nearby place',
        };
      });
      return {
        kind: 'local',
        layout: 'rail',
        eyebrow: 'Tripadvisor details',
        heading: mainItem.title,
        subtitle: nearbyItems.length ? `${nearbyItems.length} nearby suggestions shown` : '',
        items: [mainItem, ...nearbyItems],
      };
    }

    const items = this._rows(payload).map(row => {
      const chips = [];
      if (row.place_type) chips.push(String(row.place_type).toLowerCase().replace(/_/g, ' '));
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      return {
        title: row.title || row.name || 'Tripadvisor result',
        url: row.url || row.link,
        image: row.thumbnail || row.image_url,
        primary: row.rating != null ? `★ ${row.rating}` : '',
        chips,
        details: [
          row.location,
          row.description ? this._compactText(row.description, 220) : '',
        ].filter(Boolean),
        actionLabel: 'View on Tripadvisor',
      };
    });
    return {
      kind: 'local',
      layout: 'rail',
      eyebrow: 'Tripadvisor',
      heading: payload.query || 'Travel ideas',
      subtitle: payload.category && payload.category !== 'all'
        ? String(payload.category).replace(/_/g, ' ')
        : '',
      items,
    };
  }

  _adaptTraktMovies(payload, mediaType = 'movie') {
    const isShow = mediaType === 'show';
    const items = this._rows(payload).map((row, index) => {
      const chips = [];
      if (row.year) chips.push(String(row.year));
      const runtime = isShow ? row.episode_runtime_minutes : row.runtime_minutes;
      if (runtime) chips.push(`${runtime} min${isShow ? '/episode' : ''}`);
      if (row.certification) chips.push(String(row.certification));
      if (isShow && row.network) chips.push(String(row.network));
      if (isShow && row.status) chips.push(String(row.status));
      const signals = this._list(row.source_signals)
        .slice(0, 3)
        .map(signal => String(signal).replace(/^related:/, 'Like '));
      chips.push(...signals);
      const genres = this._list(row.genres).slice(0, 4).join(' · ');
      const details = [];
      if (genres) details.push(genres);
      if (row.overview) details.push(this._compactText(row.overview, 260));
      if (row.trailer_url) details.push('Trailer available');
      const rating = row.rating != null ? Number(row.rating) : null;
      const primary = Number.isFinite(rating)
        ? `★ ${rating.toFixed(1)}${row.votes ? ` · ${this._formatCount(row.votes)} votes` : ''}`
        : '';
      return {
        title: row.title || `${isShow ? 'Show' : 'Movie'} ${index + 1}`,
        url: row.trakt_url || row.imdb_url || row.trailer_url,
        primary,
        chips,
        details,
        actionLabel: row.trakt_url ? 'Open on Trakt' : `Open ${isShow ? 'show' : 'movie'}`,
      };
    });
    const action = String(payload.action || 'recommend').replace(/_/g, ' ');
    const references = (Array.isArray(payload.resolved_references) ? payload.resolved_references : [])
      .map(item => item && typeof item === 'object' ? item.title : item)
      .filter(Boolean)
      .slice(0, 3)
      .join(', ');
    const subtitle = [
      action,
      references ? `Inspired by ${references}` : '',
      payload.streaming_provider_data === 'not returned' ? 'Provider availability not included' : '',
    ].filter(Boolean).join(' · ');
    return {
      kind: 'generic',
      layout: 'rail',
      eyebrow: isShow ? 'Trakt TV shows' : 'Trakt movies',
      heading: payload.request || payload.query || (isShow ? 'TV-show ideas' : 'Movie ideas'),
      subtitle,
      actionUrl: payload.top_url,
      actionLabel: `Open top ${isShow ? 'show' : 'movie'}`,
      items,
    };
  }

  _adaptTraktAccount(payload) {
    const rows = this._rows(payload);
    if (payload.action === 'status') {
      const user = payload.user && typeof payload.user === 'object' ? payload.user : {};
      const chips = ['Read only'];
      if (user.vip === true) chips.push('VIP');
      if (user.private === true) chips.push('Private profile');
      return {
        kind: 'generic',
        layout: 'rail',
        eyebrow: 'Trakt account · read only',
        heading: user.username ? `@${user.username}` : 'Trakt authorization',
        subtitle: payload.authorized ? 'OAuth active' : 'Authorization status',
        items: [{
          title: payload.authorized ? 'Account connected' : 'Account status',
          primary: user.joined_at ? `Joined ${user.joined_at}` : '',
          chips,
          details: [user.location, user.about].filter(Boolean),
        }],
      };
    }
    if (['personal_lists', 'smart_lists'].includes(payload.action)) {
      return {
        kind: 'generic',
        layout: 'rail',
        eyebrow: 'Trakt account · read only',
        heading: payload.action === 'smart_lists' ? 'Smart lists' : 'Personal lists',
        subtitle: `${rows.length} list${rows.length === 1 ? '' : 's'} · OAuth`,
        items: rows.map((row, index) => ({
          title: row.name || `List ${index + 1}`,
          url: row.share_link || row.trakt_url,
          primary: row.item_count != null ? `${row.item_count} items` : '',
          chips: [row.privacy, row.sort_by].filter(Boolean),
          details: row.description ? [this._compactText(row.description, 260)] : [],
          actionLabel: row.share_link || row.trakt_url ? 'Open list' : '',
        })),
      };
    }
    const firstType = rows.find(row => row && row.media_type)?.media_type;
    const mediaType = firstType === 'show' || payload.action === 'show_recommendations'
      || payload.action === 'tv_night_context' ? 'show' : 'movie';
    const adapted = this._adaptTraktMovies(payload, mediaType);
    adapted.eyebrow = 'Trakt account · read only';
    const accountLabel = payload.user?.username ? `@${payload.user.username}` : '';
    adapted.subtitle = [accountLabel, String(payload.action || 'account').replace(/_/g, ' '), 'OAuth']
      .filter(Boolean).join(' · ');
    adapted.items.forEach((item, index) => {
      const row = rows[index] || {};
      if (row.user_rating != null) item.chips.push(`Your rating ${row.user_rating}/10`);
      if (row.progress != null) item.chips.push(`${row.progress}% progress`);
      if (row.watched_at) item.details.push(`Watched ${row.watched_at}`);
      if (row.listed_at) item.details.push(`Added ${row.listed_at}`);
    });
    return adapted;
  }

  _adaptTmdbMovies(payload, mediaType = 'movie') {
    const isShow = mediaType === 'show';
    const action = String(payload.action || 'search').replace(/_/g, ' ');
    const media = payload[isShow ? 'show' : 'movie'];
    const movie = media && typeof media === 'object' ? media : null;
    const mediaLabel = isShow ? 'TV show' : 'Movie';
    const attribution = payload.attribution_notice
      || 'This product uses the TMDB API but is not endorsed or certified by TMDB.';

    if (payload.action === 'images') {
      const items = this._rows(payload).map((row, index) => {
        const width = Number(row.width);
        const height = Number(row.height);
        const dimensions = Number.isFinite(width) && width > 0
          && Number.isFinite(height) && height > 0
          ? `${width} × ${height}`
          : '';
        return {
          title: row.title || `${movie?.title || mediaLabel} artwork ${index + 1}`,
          url: row.source_url || movie?.tmdb_url || payload.top_url,
          image: index === 0
            ? (row.image_url || row.thumbnail)
            : (row.thumbnail || row.image_url),
          imageUrl: row.original_url || row.image_url,
          imageVariant: row.image_type,
          featured: index === 0,
          primary: row.image_type ? String(row.image_type) : '',
          chips: [dimensions, row.language || 'No language', row.rating != null ? `★ ${row.rating}` : '']
            .filter(Boolean),
          actionLabel: 'Open on TMDB',
        };
      });
      return {
        kind: 'image',
        layout: 'gallery',
        eyebrow: `TMDB ${isShow ? 'TV' : 'movie'} artwork · External content`,
        heading: movie?.title || payload.query || `${mediaLabel} artwork`,
        subtitle: [
          `${payload.results_count ?? items.length} image${Number(payload.results_count ?? items.length) === 1 ? '' : 's'}`,
          payload.image_type && payload.image_type !== 'all' ? payload.image_type : '',
          attribution,
        ].filter(Boolean).join(' · '),
        actionUrl: movie?.tmdb_url || payload.top_url || payload.attribution_url,
        actionLabel: 'Open on TMDB',
        items,
      };
    }

    if (payload.action === 'credits') {
      const items = this._rows(payload).map((row, index) => ({
        title: row.name || `Cast member ${index + 1}`,
        url: row.tmdb_url,
        image: row.profile_thumbnail || row.profile_url,
        imageUrl: row.profile_url,
        primary: row.character ? `as ${row.character}` : '',
        chips: [row.known_for_department].filter(Boolean),
        actionLabel: 'Open person',
      }));
      return {
        kind: 'generic',
        layout: 'rail',
        eyebrow: 'TMDB cast and crew',
        heading: movie?.title || payload.query || `${mediaLabel} credits`,
        subtitle: attribution,
        actionUrl: movie?.tmdb_url || payload.top_url || payload.attribution_url,
        actionLabel: 'Open on TMDB',
        items,
      };
    }

    if (payload.action === 'videos') {
      const items = this._rows(payload).map((row, index) => ({
        title: row.title || `${movie?.title || mediaLabel} video ${index + 1}`,
        url: row.url,
        primary: row.site || '',
        chips: [row.type, row.official === true ? 'Official' : '', row.published_at]
          .filter(Boolean),
        actionLabel: 'Watch video',
      }));
      return {
        kind: 'video',
        layout: 'rail',
        eyebrow: `TMDB ${isShow ? 'TV' : 'movie'} videos`,
        heading: movie?.title || payload.query || `${mediaLabel} videos`,
        subtitle: attribution,
        actionUrl: movie?.tmdb_url || payload.top_url || payload.attribution_url,
        actionLabel: 'Open on TMDB',
        items,
      };
    }

    const items = this._rows(payload).map((row, index) => {
      const rating = row.rating != null ? Number(row.rating) : null;
      return {
        title: row.title || `${mediaLabel} ${index + 1}`,
        url: row.tmdb_url || row.imdb_url,
        image: row.poster_thumbnail || row.poster_url,
        imageUrl: row.poster_original_url || row.backdrop_original_url || row.poster_url,
        primary: Number.isFinite(rating)
          ? `★ ${rating.toFixed(1)}${row.votes ? ` · ${this._formatCount(row.votes)} votes` : ''}`
          : '',
        chips: [
          row.year,
          (isShow ? row.episode_runtime_minutes : row.runtime_minutes)
            ? `${isShow ? row.episode_runtime_minutes : row.runtime_minutes} min${isShow ? '/episode' : ''}`
            : '',
          isShow ? row.content_rating : row.certification,
          isShow && row.number_of_seasons ? `${row.number_of_seasons} season${Number(row.number_of_seasons) === 1 ? '' : 's'}` : '',
          isShow ? row.status : '',
          row.source_signal ? String(row.source_signal).replace(/_/g, ' ') : '',
        ].filter(Boolean).map(String),
        details: [
          this._list(row.genres).slice(0, 4).join(' · '),
          isShow ? this._list(row.networks).slice(0, 3).join(' · ') : '',
          row.overview ? this._compactText(row.overview, 260) : '',
        ].filter(Boolean),
        actionLabel: 'Open on TMDB',
      };
    });
    return {
      kind: 'generic',
      layout: 'rail',
      eyebrow: `TMDB ${isShow ? 'TV shows' : 'movies'} · External content`,
      heading: movie?.title || payload.query || `${action.charAt(0).toUpperCase()}${action.slice(1)} ${isShow ? 'TV shows' : 'movies'}`,
      subtitle: [
        `${payload.results_count ?? items.length} result${Number(payload.results_count ?? items.length) === 1 ? '' : 's'}`,
        attribution,
      ].filter(Boolean).join(' · '),
      actionUrl: payload.top_url || movie?.tmdb_url || payload.attribution_url,
      actionLabel: 'Open on TMDB',
      items,
    };
  }

  _adaptFlights(payload) {
    const currency = payload.currency || 'USD';
    const items = this._rows(payload).map((row, index) => {
      const airlines = this._list(row.airlines).join(', ');
      const chips = [];
      const flightNumbers = this._list(row.flight_numbers).join(', ');
      if (flightNumbers) chips.push(flightNumbers);
      if (row.departure_time) chips.push(`Departs ${this._formatFlightTime(row.departure_time)}`);
      if (row.arrival_time) chips.push(`Arrives ${this._formatFlightTime(row.arrival_time)}`);
      const route = [row.departure_airport, row.arrival_airport].filter(Boolean).join(' → ');
      return {
        title: airlines || `Flight option ${index + 1}`,
        primary: this._formatPrice(row.price, currency),
        chips,
        details: [route, row.duration_display, row.stops_label].filter(Boolean),
      };
    });
    const route = [payload.departure_id, payload.arrival_id].filter(Boolean).join(' → ');
    const dates = [payload.outbound_date, payload.return_date].filter(Boolean).join(' → ');
    return {
      kind: 'flight',
      eyebrow: 'Flights',
      heading: route || 'Flight options',
      subtitle: dates,
      actionUrl: payload.booking_url,
      actionLabel: 'Open Google Flights',
      items,
    };
  }

  _adaptTravelExplore(payload) {
    const currency = payload.currency || 'USD';
    const items = this._rows(payload).map((row, index) => {
      const chips = [];
      if (row.hotel_price != null) {
        chips.push(`Hotel signal ${this._formatPrice(row.hotel_price, currency)}`);
      }
      if (row.start_date && row.end_date) chips.push(`${row.start_date} → ${row.end_date}`);
      else if (row.start_date) chips.push(`Starts ${row.start_date}`);
      if (row.stops_label) chips.push(row.stops_label);
      const airport = [row.airport_code, row.airport_location].filter(Boolean).join(' · ');
      const transfer = row.ground_transfer_display
        ? `${row.ground_transfer_display} ground transfer`
        : '';
      return {
        title: row.name || `Destination ${index + 1}`,
        url: row.google_travel_url,
        image: row.thumbnail,
        primary: row.flight_price != null
          ? `${this._formatPrice(row.flight_price, currency)} flight signal`
          : '',
        chips,
        details: [row.country, airport, row.flight_duration_display, transfer, row.airline].filter(Boolean),
        actionLabel: 'Explore destination',
      };
    });
    const duration = payload.travel_duration
      ? String(payload.travel_duration).replace(/_/g, ' ')
      : '';
    return {
      kind: 'travel',
      eyebrow: 'Travel Explore · Planning prices',
      heading: `Destination ideas from ${payload.departure_id || 'your origin'}`,
      subtitle: [payload.month_label, duration, payload.interest].filter(Boolean).join(' · '),
      actionUrl: payload.google_travel_url || payload.top_url,
      actionLabel: 'Open Google Travel',
      items,
    };
  }

  _adaptGoogleEvents(payload) {
    const items = this._rows(payload).map((row, index) => {
      const venue = row.venue && typeof row.venue === 'object' ? row.venue : {};
      const tickets = Array.isArray(row.ticket_info)
        ? row.ticket_info.filter(ticket => ticket && typeof ticket === 'object')
        : (row.ticket_info && typeof row.ticket_info === 'object' ? [row.ticket_info] : []);
      const firstTicket = tickets.find(ticket => ticket.link) || {};
      const timing = row.when || row.date_text || row.time || row.start_date || '';
      const address = row.address_text || this._list(row.address).join(', ');
      const chips = [
        row.type,
        row.price,
        venue.rating != null ? `Venue ★ ${venue.rating}` : '',
        venue.reviews != null ? `${this._formatCount(venue.reviews)} venue reviews` : '',
        tickets.length ? `${tickets.length} link${tickets.length === 1 ? '' : 's'}` : '',
      ].filter(Boolean).map(String);
      return {
        title: row.title || `Event ${index + 1}`,
        url: row.url || row.link || firstTicket.link || venue.link || row.event_location_map?.link,
        image: row.thumbnail || row.image || row.event_location_map?.image,
        imageUrl: row.image || row.thumbnail,
        primary: timing,
        chips,
        details: [
          venue.name,
          address,
          this._compactText(row.description, 260),
        ].filter(Boolean),
        actionLabel: firstTicket.link ? 'Tickets / details' : 'Event details',
      };
    });
    const location = payload.location || (payload.uule_used ? 'encoded location' : '');
    return {
      kind: 'events',
      layout: 'rail',
      eyebrow: 'Google Events · External content',
      heading: payload.effective_query || payload.query || 'Upcoming events',
      subtitle: [
        `${payload.results_count ?? items.length} event${Number(payload.results_count ?? items.length) === 1 ? '' : 's'}`,
        location,
        payload.date_filter ? String(payload.date_filter).replace(/_/g, ' ') : '',
        payload.virtual ? 'Virtual only' : '',
        payload.location_ambiguity_warning || '',
      ].filter(Boolean).join(' · '),
      actionUrl: payload.google_events_url || payload.top_url,
      actionLabel: 'Open Google Events',
      items,
    };
  }

  _adaptMaps(payload) {
    const items = this._rows(payload).map(row => {
      const chips = [];
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (row.price && row.rating != null) chips.push(String(row.price));
      return {
        title: row.title || row.name || 'Map result',
        url: row.url || row.link,
        image: row.thumbnail || row.image_url,
        primary: row.rating != null ? `★ ${row.rating}` : row.price,
        chips,
        details: [row.address, row.type].filter(Boolean),
        actionLabel: 'Open place',
      };
    });
    return {
      kind: 'local',
      eyebrow: 'Places',
      heading: payload.query || 'Map results',
      subtitle: payload.location || '',
      items,
    };
  }

  _adaptGoogleLocal(payload) {
    const placeItem = (row, index, sponsored = false) => {
      const serviceOptions = row.service_options && typeof row.service_options === 'object'
        ? Object.entries(row.service_options)
          .filter(([, enabled]) => enabled === true)
          .slice(0, 3)
          .map(([name]) => name.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()))
        : [];
      const chips = [];
      if (sponsored || row.sponsored === true) chips.push('Sponsored');
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (row.price) chips.push(String(row.price));
      chips.push(...serviceOptions);
      return {
        title: row.title || `Local result ${index + 1}`,
        url: row.url || row.website || row.directions_url || row.google_maps_url || row.place_id_search,
        image: row.thumbnail || row.thumbnail_small,
        primary: row.rating != null ? `★ ${row.rating}` : row.type || '',
        chips,
        details: [
          row.address,
          row.type,
          row.hours,
          this._compactText(row.description, 220),
        ].filter(Boolean),
        actionLabel: row.website ? 'Open website' : 'Open place',
      };
    };

    const resultItems = this._rows(payload).map((row, index) => placeItem(row, index));
    const adRows = Array.isArray(payload.ads)
      ? payload.ads.filter(row => row && typeof row === 'object').slice(0, 3)
      : [];
    const adItems = adRows.map((row, index) => placeItem(row, index, true));
    const discoverRows = Array.isArray(payload.discover_more_places)
      ? payload.discover_more_places.filter(row => row && typeof row === 'object').slice(0, 3)
      : [];
    const discoverItems = discoverRows.map((row, index) => ({
      title: row.title || `Related local search ${index + 1}`,
      url: row.url,
      image: row.thumbnail,
      primary: 'Related search',
      details: [this._compactText(this._displayText(row.places), 220)].filter(Boolean),
      actionLabel: 'Explore nearby',
    }));
    const location = payload.provider_location_used || payload.location || '';
    const providerCount = payload.provider_results_count ?? resultItems.length;
    return {
      kind: 'local',
      layout: 'rail',
      eyebrow: 'Google Local',
      heading: payload.query || 'Local places',
      subtitle: [
        location,
        `${providerCount} local result${Number(providerCount) === 1 ? '' : 's'}`,
      ].filter(Boolean).join(' · '),
      actionUrl: payload.google_local_url,
      actionLabel: 'Open Google Local',
      items: [...resultItems, ...adItems, ...discoverItems],
    };
  }

  _adaptGoogleLocalServices(payload) {
    const rows = this._rows(payload);
    const items = rows.map((row, index) => {
      const chips = [];
      if (row.badge) chips.push(String(row.badge).replace(/_/g, ' '));
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (row.years_in_business != null) {
        chips.push(`${row.years_in_business} year${Number(row.years_in_business) === 1 ? '' : 's'} in business`);
      }
      if (row.bookings_nearby != null) chips.push(`${row.bookings_nearby} bookings nearby`);
      const services = Array.isArray(row.services)
        ? row.services.slice(0, 3).join(' · ')
        : '';
      return {
        title: row.title || `Service provider ${index + 1}`,
        url: row.url || row.website,
        image: row.thumbnail || (Array.isArray(row.images) ? row.images[0] : ''),
        primary: row.rating != null ? `★ ${row.rating}` : row.type || '',
        chips,
        details: [
          row.service_area,
          row.type,
          row.hours_current,
          row.phone,
          services,
        ].filter(Boolean),
        actionLabel: row.website && !row.url ? 'Open website' : 'View provider',
      };
    });
    const location = payload.resolved_location || payload.location || '';
    const providerCount = payload.provider_results_count ?? items.length;
    const searchesUsed = Number(payload.serpapi_searches_used);
    return {
      kind: 'local',
      layout: 'rail',
      eyebrow: payload.mode === 'provider_details'
        ? 'Google Local Services · Provider details'
        : 'Google Local Services',
      heading: payload.query || 'Local service providers',
      subtitle: [
        location,
        `${providerCount} provider${Number(providerCount) === 1 ? '' : 's'}`,
        Number.isFinite(searchesUsed)
          ? `${searchesUsed} SerpApi search${searchesUsed === 1 ? '' : 'es'}`
          : '',
      ].filter(Boolean).join(' · '),
      actionUrl: payload.google_local_services_url,
      actionLabel: 'Open Google Local Services',
      items,
    };
  }

  _adaptShoppingSearch(payload) {
    const rows = this._rows(payload);
    const engine = String(payload.engine || '').toLowerCase();
    if (!['amazon', 'amazon_product', 'google_shopping'].includes(engine)) {
      return { items: [] };
    }
    const focused = payload.engine === 'amazon_product'
      || Boolean(payload.asin)
      || (payload.engine === 'amazon' && rows.length === 1);
    const items = rows.filter(product => product?.title && product?.url).map(product => {
      const chips = [];
      if (product.rating != null) chips.push(`★ ${product.rating}`);
      if (product.reviews != null) chips.push(`${product.reviews} reviews`);
      if (product.asin) chips.push(`ASIN ${product.asin}`);
      if (product.prime === true || product.is_prime === true) chips.push('Prime');
      return {
        title: product.title,
        url: product.url,
        image: product.image_url || product.thumbnail,
        primary: this._formatMarketplacePrice(product.price),
        chips,
        details: [
          this._compactText(this._displayText(product.delivery)),
          this._compactText(this._displayText(product.availability)),
          this._compactText(this._displayText(product.stock)),
          this._compactText(this._displayText(product.condition)),
        ].filter(Boolean),
        actionLabel: 'Open product',
      };
    });
    const isGoogleShopping = engine === 'google_shopping';
    return {
      kind: 'product',
      layout: 'rail',
      eyebrow: isGoogleShopping
        ? 'Google Shopping'
        : (focused ? 'Amazon product' : 'Amazon results'),
      heading: payload.query || (focused ? 'Product result' : 'Shopping options'),
      items,
    };
  }

  _adaptHomeDepotProduct(payload) {
    const rows = this._rows(payload);
    const products = rows.length ? rows : [payload.product_details].filter(Boolean);
    const items = products.filter(product => product?.title && product?.url).map(product => {
      const chips = [];
      if (product.rating != null) chips.push(`★ ${product.rating}`);
      if (product.reviews != null) chips.push(`${product.reviews} reviews`);
      if (product.product_id) chips.push(`Product ${product.product_id}`);
      return {
        title: product.title,
        url: product.url,
        image: product.image_url || product.thumbnail || payload.top_image_url,
        primary: this._formatMarketplacePrice(product.price_formatted || product.price),
        chips,
        details: [
          this._compactText(this._displayText(product.brand)),
          this._compactText(this._displayText(product.delivery)),
          this._compactText(this._displayText(product.pickup)),
          this._compactText(this._displayText(product.stock)),
        ].filter(Boolean),
        actionLabel: 'Open product',
      };
    });
    return {
      kind: 'product',
      layout: 'rail',
      eyebrow: items.length === 1 ? 'Home Depot product' : 'Home Depot results',
      heading: payload.query || 'Product result',
      items,
    };
  }

  _adaptEbaySearch(payload) {
    const items = this._rows(payload).filter(row => row?.title && row?.url).map(row => {
      const chips = [];
      if (row.condition) chips.push(String(row.condition));
      if (row.rating != null) chips.push(`★ ${row.rating}`);
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (row.top_rated === true) chips.push('Top rated');
      return {
        title: row.title,
        url: row.url,
        image: row.thumbnail || row.image_url,
        primary: this._formatMarketplacePrice(row.price),
        chips,
        details: [
          this._compactText(this._displayText(row.shipping)),
          this._compactText(this._displayText(row.seller)),
          this._compactText(this._displayText(row.subtitle)),
        ].filter(Boolean),
        actionLabel: 'Open listing',
      };
    });
    return {
      kind: 'product',
      layout: 'rail',
      eyebrow: 'eBay results',
      heading: payload.query || 'Listings',
      items,
    };
  }

  _adaptEbayProduct(payload) {
    const rows = this._rows(payload);
    const summary = payload.product_summary && typeof payload.product_summary === 'object'
      ? payload.product_summary
      : null;
    const product = summary || rows[0];
    const url = product?.url || rows[0]?.url;
    if (!product?.title || !url) return { items: [] };

    let image = product.thumbnail || payload.top_image_url;
    if (Array.isArray(summary?.image_urls) && summary.image_urls.length) {
      image = summary.image_urls[summary.image_urls.length - 1] || summary.image_urls[0];
    }
    let price = this._formatMarketplacePrice(product.price);
    const buy = summary?.buy;
    const buyNow = buy?.buy_it_now?.price;
    const bid = buy?.bid?.price;
    if (buyNow?.amount != null && buyNow?.currency) {
      price = `${buyNow.currency} ${buyNow.amount}`;
    } else if (bid?.amount != null && bid?.currency) {
      price = `Bid ${bid.currency} ${bid.amount}`;
    }

    const chips = [];
    if (product.rating != null) chips.push(`★ ${product.rating}`);
    if (product.review_count != null) chips.push(`${product.review_count} reviews`);
    const productId = payload.product_id || product.product_id;
    if (productId) chips.push(`Item ${productId}`);
    return {
      kind: 'product',
      eyebrow: 'eBay product',
      heading: 'Product result',
      items: [{
        title: product.title,
        url,
        image,
        primary: price,
        chips,
        actionLabel: 'Open listing',
      }],
    };
  }

  _adaptYouTubeSearch(payload) {
    const items = this._rows(payload).filter(row => row?.title && (row?.url || row?.video_id)).map(row => {
      const chips = [];
      if (row.channel) chips.push(String(row.channel));
      const views = this._formatCount(row.views ?? row.extracted_views);
      if (views) chips.push(String(views).toLowerCase().includes('view') ? String(views) : `${views} views`);
      if (row.published_date) chips.push(String(row.published_date));
      if (row.live === true) chips.push('Live');
      return {
        title: row.title,
        url: row.url || `https://www.youtube.com/watch?v=${encodeURIComponent(row.video_id)}`,
        image: row.thumbnail,
        primary: row.duration || (row.live === true ? 'Live' : ''),
        chips,
        details: row.description ? [this._compactText(row.description)] : [],
        actionLabel: 'Watch on YouTube',
      };
    });
    return {
      kind: 'video',
      layout: 'rail',
      eyebrow: 'YouTube',
      heading: payload.search_query || 'Video results',
      subtitle: payload.ranking_mode === 'views_desc' ? 'Sorted by views' : '',
      items,
    };
  }

  _adaptWeather(payload) {
    const forecast = Array.isArray(payload.daily_forecast) && payload.daily_forecast.length
      ? payload.daily_forecast
      : (Array.isArray(payload.forecast) ? payload.forecast : []);
    const degree = value => value != null && value !== '' ? `${value}°` : '';
    let items = forecast.slice(0, 10).map((row, index) => {
      const title = row.day
        ? [row.day, row.date].filter(Boolean).join(' · ')
        : (row.date || row.time || `Forecast ${index + 1}`);
      const highLow = row.high != null || row.low != null
        ? [degree(row.high), degree(row.low)].filter(Boolean).join(' / ')
        : degree(row.temp);
      const chips = [];
      if (row.precip_probability != null) chips.push(`${row.precip_probability}% precipitation`);
      if (row.humidity != null) chips.push(`${row.humidity}% humidity`);
      if (row.wind_max != null) chips.push(`Wind ${row.wind_max} mph`);
      return {
        title,
        primary: highLow,
        chips,
        details: row.condition ? [row.condition] : [],
      };
    });
    if (!items.length && payload.temperature != null) {
      items = [{
        title: 'Current conditions',
        primary: degree(payload.temperature),
        chips: [
          payload.feels_like != null ? `Feels like ${degree(payload.feels_like)}` : '',
          payload.humidity != null ? `${payload.humidity}% humidity` : '',
          payload.wind_speed != null ? `Wind ${payload.wind_speed} ${payload.wind_unit || 'mph'}` : '',
        ].filter(Boolean),
        details: payload.condition ? [payload.condition] : [],
      }];
    }
    const current = [];
    if (payload.temperature != null) current.push(`Currently ${degree(payload.temperature)}`);
    if (payload.condition) current.push(String(payload.condition));
    if (payload.feels_like != null && payload.feels_like !== payload.temperature) {
      current.push(`Feels like ${degree(payload.feels_like)}`);
    }
    return {
      kind: 'weather',
      layout: 'metrics',
      eyebrow: 'Weather',
      heading: payload.location || 'Forecast',
      subtitle: current.join(' · '),
      items,
    };
  }

  _adaptGpuHotStatus(payload) {
    const gpus = Array.isArray(payload.gpus) ? payload.gpus : [];
    const processes = Array.isArray(payload.processes) ? payload.processes : [];
    const formatNumber = value => {
      const number = Number(value);
      return Number.isFinite(number) ? number.toLocaleString(undefined, {maximumFractionDigits: 1}) : '';
    };
    const items = gpus.map((gpu, index) => {
      const gpuIndex = String(gpu.index ?? index);
      const gpuProcesses = processes.filter(process => String(process.gpu_index ?? '') === gpuIndex);
      const chips = [];
      if (gpu.utilization_percent != null) chips.push(`${formatNumber(gpu.utilization_percent)}% utilized`);
      if (gpu.vram_capacity_percent != null) chips.push(`${formatNumber(gpu.vram_capacity_percent)}% VRAM`);
      if (gpu.power_draw_w != null) chips.push(`${formatNumber(gpu.power_draw_w)} W`);
      const details = [];
      if (gpu.vram_used_mib != null && gpu.vram_total_mib != null) {
        details.push(`${formatNumber(Number(gpu.vram_used_mib) / 1024)} / ${formatNumber(Number(gpu.vram_total_mib) / 1024)} GiB allocated`);
      }
      if (gpuProcesses.length) {
        details.push(gpuProcesses.slice(0, 4).map(process => {
          const memory = process.vram_mib != null ? ` ${formatNumber(process.vram_mib)} MiB` : '';
          return `${process.name || 'process'}${memory}`;
        }).join(' · '));
      }
      return {
        title: gpu.name || `GPU ${gpuIndex}`,
        primary: gpu.temperature_c != null ? `${formatNumber(gpu.temperature_c)} °C` : '',
        chips,
        details,
      };
    });
    const system = payload.system && typeof payload.system === 'object' ? payload.system : {};
    const subtitle = [
      system.cpu_percent != null ? `Host CPU ${formatNumber(system.cpu_percent)}%` : '',
      system.ram_percent != null ? `RAM ${formatNumber(system.ram_percent)}%` : '',
      payload.transport ? String(payload.transport) : '',
    ].filter(Boolean).join(' · ');
    return {
      kind: 'generic',
      layout: 'metrics',
      eyebrow: 'GPU Hot',
      heading: payload.host_label || payload.node_name || 'GPU host',
      subtitle,
      actionUrl: payload.dashboard_url,
      actionLabel: 'Open dashboard',
      items,
    };
  }

  _safeUrl(value) {
    if (!value) return '';
    try {
      return Utils.safeHttpUrlForAttr(value) || '';
    } catch (_error) {
      return '';
    }
  }

  _escape(value) {
    return Utils.escapeHtml(String(value ?? ''));
  }

  _renderCollection(collection, options = {}) {
    const kind = ['product', 'hotel', 'local', 'flight', 'video', 'weather', 'image', 'sport'].includes(collection.kind)
      ? collection.kind
      : 'generic';
    const layout = ['rail', 'list', 'metrics', 'gallery'].includes(collection.layout)
      ? collection.layout
      : 'rail';
    const embedded = options.embedded === true;
    const single = collection.items.length === 1;
    const cards = collection.items.map(item => {
      const url = this._safeUrl(item.url);
      const image = this._safeUrl(item.image);
      const imageUrl = this._safeUrl(item.imageUrl);
      const title = this._escape(item.title || 'Result');
      const titleHtml = url
        ? `<a class="structured-result-title" href="${url}" target="_blank" rel="noopener noreferrer" title="${title}">${title}</a>`
        : `<div class="structured-result-title" title="${title}">${title}</div>`;
      const chips = this._list(item.chips)
        .map(chip => `<span class="structured-result-chip">${this._escape(chip)}</span>`)
        .join('');
      const details = this._list(item.details)
        .map(detail => `<div class="structured-result-detail">${this._escape(detail)}</div>`)
        .join('');
      const action = url
        ? `<a class="structured-result-link" href="${url}" target="_blank" rel="noopener noreferrer">${this._escape(item.actionLabel || 'Open')}</a>`
        : '';
      const imageVariant = ['poster', 'backdrop', 'logo'].includes(item.imageVariant)
        ? ` structured-result-image-${item.imageVariant}`
        : '';
      const featured = item.featured === true ? ' structured-result-card-featured' : '';
      return `
        <article class="structured-result-card structured-result-card-${kind}${imageVariant}${featured}">
          ${image ? `<a class="structured-result-image" href="${imageUrl || url || image}" target="_blank" rel="noopener noreferrer"><img src="${image}" alt="${title}" loading="lazy" referrerpolicy="no-referrer"></a>` : ''}
          <div class="structured-result-body">
            ${titleHtml}
            ${item.primary ? `<div class="structured-result-primary">${this._escape(item.primary)}</div>` : ''}
            ${chips ? `<div class="structured-result-chips">${chips}</div>` : ''}
            ${details ? `<div class="structured-result-details">${details}</div>` : ''}
            ${action}
          </div>
        </article>
      `;
    }).join('');
    const actionUrl = this._safeUrl(collection.actionUrl);
    const collectionAction = actionUrl
      ? `<a class="structured-results-action" href="${actionUrl}" target="_blank" rel="noopener noreferrer">${this._escape(collection.actionLabel || 'Open results')}</a>`
      : '';
    const scrollControls = layout === 'rail' && !single
      ? `
        <div class="structured-results-scroll-controls" role="group" aria-label="Scroll results" hidden>
          <button class="structured-results-scroll-button" type="button" data-direction="previous" aria-label="Previous results" title="Previous results">&#8249;</button>
          <button class="structured-results-scroll-button" type="button" data-direction="next" aria-label="Next results" title="Next results">&#8250;</button>
        </div>
      `
      : '';
    const orchestration = embedded && options.surface === 'orchestration';
    const surfaceTool = embedded && options.toolName
      ? ` data-${orchestration ? 'orchestration' : 'workflow'}-tool="${this._escape(options.toolName)}"`
      : '';
    const surfacePosition = embedded && (orchestration ? options.call : options.step) != null
      ? ` data-${orchestration ? 'orchestration-call' : 'workflow-step'}="${this._escape(orchestration ? options.call : options.step)}"`
      : '';
    const occurrence = orchestration && options.occurrence != null
      ? ` data-orchestration-occurrence="${this._escape(options.occurrence)}"`
      : '';
    const embeddedClass = embedded
      ? ` structured-results-workflow-section${orchestration ? ' structured-results-orchestration-section' : ''}`
      : '';
    const singleClass = single ? ' structured-results-single' : '';
    return `
      <section class="structured-results-preview structured-results-${kind} structured-results-layout-${layout}${embeddedClass}${singleClass}"${surfaceTool}${surfacePosition}${occurrence} aria-label="${this._escape(collection.eyebrow || 'Structured results')}">
        <div class="structured-results-header">
          <div>
            <div class="structured-results-eyebrow">${this._escape(collection.eyebrow || 'Results')}</div>
            <div class="structured-results-heading">${this._escape(collection.heading || 'Options')}</div>
            ${collection.subtitle ? `<div class="structured-results-subtitle">${this._escape(collection.subtitle)}</div>` : ''}
          </div>
          <div class="structured-results-header-meta">
            <div class="structured-results-meta-row">
              <span>${collection.items.length} shown</span>
              ${scrollControls}
            </div>
            ${collectionAction}
          </div>
        </div>
        <div class="structured-results-track">${cards}</div>
      </section>
    `;
  }
}

window.StructuredResultsRenderer = StructuredResultsRenderer;
window.structuredResultsRenderer = new StructuredResultsRenderer();
