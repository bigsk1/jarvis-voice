/** Self-contained property snapshots embedded in fenced property-listings JSON.
 * Rendering and controls use DOM text only; browsing never retrieves or runs work.
 */
window.CanvasPropertyReport = (() => {
    const MAX_ITEMS = 2000;
    const MAX_CHARS = 4 * 1024 * 1024;
    const PAGE_SIZE = 24;
    const reports = new WeakMap();
    const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const text = (value, limit = 300) => typeof value === 'string' ? value.slice(0, limit) : '';
    const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
    const numeric = value => number(value) === null ? 'Not provided' : value.toLocaleString('en-US');
    const count = value => Number.isSafeInteger(value) && value >= 0 ? String(value) : 'unknown';
    const human = value => {
        const words = text(value, 80).replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase();
        return words ? words[0].toUpperCase() + words.slice(1) : 'Not provided';
    };
    function element(tag, className = '', value = null) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (value !== null) node.textContent = value;
        return node;
    }
    function safeUrl(value, source, image = false) {
        if (typeof value !== 'string' || value.length > 4096) return '';
        try {
            const url = new URL(value);
            const hosts = image ? source === 'zillow' ? ['photos.zillowstatic.com'] : ['ssl.cdn-redfin.com', 'cdn-redfin.com']
                : source === 'zillow' ? ['zillow.com', 'www.zillow.com'] : ['redfin.com', 'www.redfin.com'];
            return url.protocol === 'https:' && !url.username && !url.password
                && !url.port && hosts.includes(url.hostname)
                && !(image && /\.svg(?:$|\/)/i.test(url.pathname)) ? url.href : '';
        } catch (_error) { return ''; }
    }
    function price(row) {
        if (text(row.price_text, 100)) return text(row.price_text, 100);
        if (number(row.price) === null) return 'Price not provided';
        if (!/^[A-Z]{3}$/.test(row.currency || '')) return numeric(row.price);
        try {
            return new Intl.NumberFormat('en-US', {style: 'currency', currency: row.currency,
                maximumFractionDigits: row.price % 1 === 0 ? 0 : 2}).format(row.price);
        } catch (_error) { return `${numeric(row.price)} ${text(row.currency, 12)}`; }
    }
    function location(row) {
        return [text(row.city, 100), [text(row.state, 64), text(row.postal_code, 24)].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    }
    function listingLink(row, className = '') {
        const url = safeUrl(row.url, row.source);
        const title = text(row.address) || 'Address not provided';
        if (!url) return element('span', className, title);
        const link = element('a', className, title);
        link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        return link;
    }
    function photo(row) {
        const media = element('div', 'property-report-media');
        const src = safeUrl(row.image_url, row.source, true);
        const fallback = element('div', 'property-report-photo-fallback', src ? 'Photo unavailable' : 'No photo provided');
        if (src) {
            const image = element('img', 'property-report-photo');
            image.src = src; image.alt = ''; image.loading = 'lazy'; image.decoding = 'async';
            image.referrerPolicy = 'no-referrer';
            fallback.hidden = true;
            image.addEventListener('error', () => { image.hidden = true; fallback.hidden = false; });
            media.append(image);
        }
        media.append(fallback);
        return media;
    }
    function propertyCard(row) {
        const card = element('article', 'property-report-card');
        const body = element('div', 'property-report-card-body');
        const top = element('div', 'property-report-card-top');
        top.append(element('span', 'property-report-status', human(row.listing_status)),
            element('span', 'property-report-source', row.source === 'zillow' ? 'Zillow' : 'Redfin'));
        const address = element('h3', 'property-report-address');
        address.append(listingLink(row));
        const facts = [number(row.bedrooms) !== null ? `${numeric(row.bedrooms)} beds` : '',
            number(row.bathrooms) !== null ? `${numeric(row.bathrooms)} baths` : '',
            number(row.area) !== null ? `${numeric(row.area)} ${text(row.area_unit, 24) || '(area unit not provided)'}` : ''].filter(Boolean);
        body.append(top, element('div', 'property-report-price', price(row)), address);
        if (location(row) && !text(row.address).includes(location(row))) body.append(element('p', 'property-report-location', location(row)));
        if (facts.length) body.append(element('p', 'property-report-facts', facts.join(' · ')));
        body.append(element('p', 'property-report-secondary', [human(row.property_type),
            number(row.days_on_zillow) === null ? 'Listing age not provided' : `${numeric(row.days_on_zillow)} days on Zillow`].join(' · ')));
        card.append(photo(row), body);
        return card;
    }
    function propertyTable(rows) {
        const scroll = element('div', 'property-report-table-scroll');
        scroll.tabIndex = 0; scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', 'Property listings table');
        const table = element('table', 'property-report-table'), head = element('thead'), header = element('tr');
        for (const title of ['Address', 'City', 'Price', 'Beds / baths', 'Area', 'Status', 'Listing age']) {
            const th = element('th', '', title); th.scope = 'col'; header.append(th);
        }
        head.append(header);
        const body = element('tbody');
        for (const row of rows) {
            const tr = element('tr'), address = element('td'); address.append(listingLink(row));
            tr.append(address, element('td', '', text(row.city, 100) || 'Not provided'), element('td', '', price(row)),
                element('td', '', `${numeric(row.bedrooms)} / ${numeric(row.bathrooms)}`),
                element('td', '', number(row.area) === null ? 'Not provided' : `${numeric(row.area)} ${text(row.area_unit, 24)}`),
                element('td', '', human(row.listing_status)),
                element('td', '', number(row.days_on_zillow) === null ? 'Not provided' : `${numeric(row.days_on_zillow)} days`));
            body.append(tr);
        }
        table.append(head, body); scroll.append(table); return scroll;
    }
    function labeledControl(label, control) {
        const wrapper = element('label', 'property-report-control');
        wrapper.append(element('span', '', label), control); return wrapper;
    }
    function option(value, title) {
        const node = element('option', '', title); node.value = value; return node;
    }

    function buildReport(data) {
        if (!record(data) || data.version !== 1 || !['zillow', 'redfin', 'mixed'].includes(data.source)
            || !Array.isArray(data.items) || data.items.length > MAX_ITEMS
            || !data.items.every(row => record(row) && row.kind === 'property_listing'
                && ['zillow', 'redfin'].includes(row.source)
                && (data.source === 'mixed' || row.source === data.source))) {
            throw new Error('Unsupported property report data.');
        }
        const rows = data.items;
        const section = element('section', 'canvas-property-report');
        section.setAttribute('aria-label', 'Property snapshot report');
        const heading = element('div', 'property-report-heading');
        heading.append(element('h2', '', `${data.source === 'mixed' ? 'Zillow and Redfin' : data.source === 'zillow' ? 'Zillow' : 'Redfin'} property snapshot`));
        const captured = text(data.snapshot_at, 100), date = captured ? new Date(captured) : null;
        heading.append(element('p', 'property-report-snapshot', date && Number.isFinite(date.getTime())
            ? `Snapshot: ${date.toLocaleString()}` : 'Snapshot time not provided'));
        section.append(heading);
        if (text(data.criteria_text, 2000)) {
            const criteria = element('div', 'property-report-criteria');
            criteria.append(element('strong', '', 'Requested criteria'), element('p', '', text(data.criteria_text, 2000)));
            section.append(criteria);
        }
        section.append(element('p', 'property-report-notice', 'Unofficial listing snapshot from an Apify Actor. Prices and availability can change. Requested criteria are not proof that the source honored every filter.'));
        const coverage = record(data.coverage) ? data.coverage : {};
        if ('fetched_count' in coverage || 'unrecognized_count' in coverage) {
            if (![coverage.fetched_count, coverage.unrecognized_count, coverage.returned_count]
                .every(value => Number.isSafeInteger(value) && value >= 0)
                || coverage.fetched_count !== coverage.returned_count + coverage.unrecognized_count
                || coverage.returned_count < rows.length) throw new Error('Invalid property report recognition counts.');
        }
        const fetched = coverage.fetched_count ?? coverage.returned_count;
        const excluded = Number.isSafeInteger(coverage.unrecognized_count) && coverage.unrecognized_count >= 0 ? coverage.unrecognized_count : 0;
        const coveragePosition = Number.isSafeInteger(coverage.offset) && coverage.offset >= 0
            ? `Saved source records start at offset ${coverage.offset} (counted from zero).`
            : 'No single starting offset: combined datasets or unknown position.';
        section.append(element('p', 'property-report-coverage', `${rows.length} saved listing rows · ${count(fetched)} fetched · ${count(coverage.total_items)} items in the source dataset. `
            + coveragePosition + ' ' + (coverage.complete === true ? 'Fetched results cover the source dataset.' : 'Dataset coverage is partial or unknown.')));
        if (excluded) section.append(element('p', 'property-report-notice', `${excluded} fetched record${excluded === 1 ? ' was' : 's were'} not recognized as property listings and ${excluded === 1 ? 'is' : 'are'} excluded from this report. Original records remain in the retained source archive. Dataset coverage describes fetched records, not listing recognition.`));
        const cityCounts = new Map();
        for (const row of rows) {
            const city = text(row.city, 100) || 'City not provided';
            cityCounts.set(city, (cityCounts.get(city) || 0) + 1);
        }
        const metrics = element('div', 'property-report-metrics');
        const metric = (value, title) => {
            const box = element('div', 'property-report-metric');
            box.append(element('strong', '', String(value)), element('span', '', title)); return box;
        };
        metrics.append(metric(rows.length, 'Saved listing rows'));
        const cities = [...cityCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
        for (const [city, amount] of cities.slice(0, 8)) metrics.append(metric(amount, city));
        section.append(metrics);
        const unknownAge = rows.filter(row => number(row.days_on_zillow) === null).length;
        const notes = [];
        if (unknownAge) notes.push(`${unknownAge} listing${unknownAge === 1 ? '' : 's'} without listing age; newest sorting places them last.`);
        notes.push(Number.isSafeInteger(data.duplicates_removed) && data.duplicates_removed >= 0
            ? `${data.duplicates_removed} duplicate rows removed before this report.` : 'Duplicate listings have not been independently checked. Counts describe saved rows.');
        section.append(element('p', 'property-report-note', notes.join(' ')));

        const controls = element('div', 'property-report-controls');
        const city = element('select'); city.setAttribute('aria-label', 'Filter listings by city');
        city.append(option('', `All cities (${rows.length})`));
        for (const [name, amount] of cities) city.append(option(name, `${name} (${amount})`));
        const sort = element('select'); sort.setAttribute('aria-label', 'Sort listings');
        for (const [value, title] of [['newest', 'Newest known listing first'], ['price_up', 'Price: low to high'],
            ['price_down', 'Price: high to low'], ['area_down', 'Area: largest first']]) sort.append(option(value, title));
        const search = element('input'); search.type = 'search'; search.placeholder = 'Address, city or ZIP';
        search.setAttribute('aria-label', 'Search property listings'); search.maxLength = 200;
        const view = element('select'); view.setAttribute('aria-label', 'Listings view');
        view.append(option('cards', 'Photo cards'), option('table', 'Table'));
        controls.append(labeledControl('City', city), labeledControl('Sort', sort),
            labeledControl('Search', search), labeledControl('View', view));
        const status = element('p', 'property-report-results-status'); status.setAttribute('aria-live', 'polite');
        const output = element('div', 'property-report-results');
        const navigation = element('div', 'property-report-pagination');
        const previous = element('button', '', 'Previous listings'), next = element('button', '', 'Next listings');
        previous.type = next.type = 'button';
        const position = element('span');
        navigation.append(previous, position, next);
        section.append(controls, status, output, navigation);
        let page = 0, printState = null;
        const draw = (printing = false) => {
            const query = search.value.trim().toLocaleLowerCase();
            const filtered = rows.map((row, index) => ({row, index})).filter(({row}) => (
                (!city.value || (text(row.city, 100) || 'City not provided') === city.value)
                && (!query || [row.address, row.city, row.state, row.postal_code].map(value => text(value))
                    .join(' ').toLocaleLowerCase().includes(query))
            ));
            const field = sort.value === 'area_down' ? 'area' : sort.value === 'newest' ? 'days_on_zillow' : 'price';
            const descending = ['price_down', 'area_down'].includes(sort.value);
            filtered.sort((a, b) => {
                const left = number(a.row[field]), right = number(b.row[field]);
                return left === null ? right === null ? a.index - b.index : 1 : right === null ? -1
                    : (descending ? right - left : left - right) || a.index - b.index;
            });
            const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
            page = Math.min(page, pages - 1);
            const selected = (printing ? filtered : filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)).map(item => item.row);
            status.textContent = filtered.length ? printing
                ? `Printing all ${filtered.length} matching listing rows (${rows.length} in this snapshot).`
                    + (city.value ? ` City: ${city.value}.` : '') + (query ? ` Search: ${search.value.trim()}.` : '')
                : `Showing ${page * PAGE_SIZE + 1}–${page * PAGE_SIZE + selected.length} of ${filtered.length} matching listing rows (${rows.length} in this snapshot).`
                : 'No listings match these local filters.';
            if (view.value === 'table') output.replaceChildren(propertyTable(selected));
            else {
                const grid = element('div', 'property-report-grid'); grid.append(...selected.map(propertyCard)); output.replaceChildren(grid);
            }
            previous.disabled = page === 0; next.disabled = page >= pages - 1;
            position.textContent = `Page ${page + 1} of ${pages}`;
            navigation.hidden = filtered.length <= PAGE_SIZE;
        };
        const reset = () => { page = 0; draw(); };
        city.addEventListener('change', reset); sort.addEventListener('change', reset);
        search.addEventListener('input', reset); view.addEventListener('change', reset);
        previous.addEventListener('click', () => { if (page > 0) { page--; draw(); } });
        next.addEventListener('click', () => { page++; draw(); });
        if (record(data.geography_attribution) && data.geography_attribution.provider === 'openstreetmap') {
            const credit = element('p', 'property-report-note');
            credit.append(document.createTextNode('City-to-area lookup: '));
            const link = element('a', '', '© OpenStreetMap contributors');
            link.href = 'https://www.openstreetmap.org/copyright'; link.target = '_blank'; link.rel = 'noopener noreferrer';
            credit.append(link, document.createTextNode('. Search map rectangles can include nearby places.'));
            section.append(credit);
        }
        // Native controls default to their first option in browsers. Explicit
        // values also make restoring a replaced report deterministic.
        city.value = ''; sort.value = 'newest'; search.value = ''; view.value = 'cards';
        reports.set(section, {
            prepare() {
                if (printState) return;
                printState = {page, city: city.value, sort: sort.value, search: search.value, view: view.value};
                draw(true);
            },
            restore() {
                if (!printState) return;
                page = printState.page; city.value = printState.city; sort.value = printState.sort;
                search.value = printState.search; view.value = printState.view;
                printState = null;
                draw();
            },
        });
        draw();
        return section;
    }

    function hydrate(root = document) {
        const blocks = root.querySelectorAll('pre > code.language-property-listings');
        for (const block of Array.from(blocks).slice(0, 4)) {
            let report;
            try {
                if (block.textContent.length > MAX_CHARS) throw new Error('Report data exceeds the supported limit.');
                report = buildReport(JSON.parse(block.textContent));
            } catch (_error) {
                report = element('p', 'property-report-notice', 'This property report cannot be displayed because its saved data is invalid or exceeds the supported limit.');
            }
            block.parentElement.replaceWith(report);
        }
    }
    function preparePrint(root = document) {
        for (const section of root.querySelectorAll('.canvas-property-report')) reports.get(section)?.prepare();
    }
    function restorePrint(root = document) {
        for (const section of root.querySelectorAll('.canvas-property-report')) reports.get(section)?.restore();
    }
    // Also cover the browser's own Print command, not only Canvas's button.
    window.addEventListener?.('beforeprint', () => preparePrint());
    window.addEventListener?.('afterprint', () => restorePrint());
    return {hydrate, buildReport, preparePrint, restorePrint};
})();
