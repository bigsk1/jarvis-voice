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

  render(toolResultsData = {}, data = {}) {
    const collections = [];
    for (const [toolName, adapter] of this.adapters.entries()) {
      const payload = this._latestPayload(
        toolResultsData?.[toolName] ?? data?.[toolName]
      );
      if (!payload) continue;
      try {
        const collection = adapter(payload);
        if (collection?.items?.length) collections.push(collection);
      } catch (error) {
        console.warn(`[StructuredResults] Could not render ${toolName}:`, error);
      }
    }
    const html = collections.map(collection => this._renderCollection(collection)).join('');
    if (html) this._scheduleScrollControlsRefresh();
    return html;
  }

  _registerDefaultAdapters() {
    this.register('serpapi_search', payload => this._adaptAmazonProduct(payload));
    this.register('serpapi_home_depot', payload => this._adaptHomeDepotProduct(payload));
    this.register('serpapi_ebay_product', payload => this._adaptEbayProduct(payload));
    this.register('serpapi_hotel_search', payload => this._adaptHotels(payload));
    this.register('serpapi_yelp_search', payload => this._adaptYelp(payload));
    this.register('flight_search', payload => this._adaptFlights(payload));
    this.register('serpapi_maps_search', payload => this._adaptMaps(payload));
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

  _adaptAmazonProduct(payload) {
    const rows = this._rows(payload);
    const product = rows[0];
    const focused = payload.engine === 'amazon_product'
      || Boolean(payload.asin)
      || (payload.engine === 'amazon' && rows.length === 1);
    if (!focused || !product?.title || !product?.url) return { items: [] };
    const chips = [];
    if (product.rating != null) chips.push(`★ ${product.rating}`);
    if (product.reviews != null) chips.push(`${product.reviews} reviews`);
    if (product.asin) chips.push(`ASIN ${product.asin}`);
    return {
      kind: 'product',
      eyebrow: 'Amazon product',
      heading: payload.query || 'Product result',
      items: [{
        title: product.title,
        url: product.url,
        image: product.image_url || product.thumbnail,
        primary: product.price,
        chips,
        actionLabel: 'Open product',
      }],
    };
  }

  _adaptHomeDepotProduct(payload) {
    const rows = this._rows(payload);
    const product = payload.product_details || rows[0];
    if (!product?.title || !product?.url) return { items: [] };
    const chips = [];
    if (product.rating != null) chips.push(`★ ${product.rating}`);
    if (product.reviews != null) chips.push(`${product.reviews} reviews`);
    if (product.product_id) chips.push(`Product ${product.product_id}`);
    return {
      kind: 'product',
      eyebrow: 'Home Depot product',
      heading: payload.query || 'Product result',
      items: [{
        title: product.title,
        url: product.url,
        image: product.image_url || product.thumbnail || payload.top_image_url,
        primary: product.price_formatted || product.price,
        chips,
        actionLabel: 'Open product',
      }],
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
    let price = product.price || '';
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

  _renderCollection(collection) {
    const kind = ['product', 'hotel', 'local', 'flight'].includes(collection.kind)
      ? collection.kind
      : 'generic';
    const cards = collection.items.map(item => {
      const url = this._safeUrl(item.url);
      const image = this._safeUrl(item.image);
      const title = this._escape(item.title || 'Result');
      const titleHtml = url
        ? `<a class="structured-result-title" href="${url}" target="_blank" rel="noopener noreferrer">${title}</a>`
        : `<div class="structured-result-title">${title}</div>`;
      const chips = this._list(item.chips)
        .map(chip => `<span class="structured-result-chip">${this._escape(chip)}</span>`)
        .join('');
      const details = this._list(item.details)
        .map(detail => `<div class="structured-result-detail">${this._escape(detail)}</div>`)
        .join('');
      const action = url
        ? `<a class="structured-result-link" href="${url}" target="_blank" rel="noopener noreferrer">${this._escape(item.actionLabel || 'Open')}</a>`
        : '';
      return `
        <article class="structured-result-card structured-result-card-${kind}">
          ${image ? `<a class="structured-result-image" href="${url || image}" target="_blank" rel="noopener noreferrer"><img src="${image}" alt="${title}" loading="lazy" referrerpolicy="no-referrer"></a>` : ''}
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
    return `
      <section class="structured-results-preview structured-results-${kind}" aria-label="${this._escape(collection.eyebrow || 'Structured results')}">
        <div class="structured-results-header">
          <div>
            <div class="structured-results-eyebrow">${this._escape(collection.eyebrow || 'Results')}</div>
            <div class="structured-results-heading">${this._escape(collection.heading || 'Options')}</div>
            ${collection.subtitle ? `<div class="structured-results-subtitle">${this._escape(collection.subtitle)}</div>` : ''}
          </div>
          <div class="structured-results-header-meta">
            <div class="structured-results-meta-row">
              <span>${collection.items.length} shown</span>
              <div class="structured-results-scroll-controls" aria-label="Scroll results" hidden>
                <button class="structured-results-scroll-button" type="button" data-direction="previous" aria-label="Previous results" title="Previous results">&#8249;</button>
                <button class="structured-results-scroll-button" type="button" data-direction="next" aria-label="Next results" title="Next results">&#8250;</button>
              </div>
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
