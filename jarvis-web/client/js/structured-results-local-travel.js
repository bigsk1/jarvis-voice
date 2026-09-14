/**
 * Local and travel payload adapters for structured result previews.
 *
 * Loaded before structured-results.js. The renderer supplies shared row and
 * text formatters; adapters return presentation data without rendering HTML.
 */
window.createLocalTravelResultAdapters = function createLocalTravelResultAdapters({
  getRows,
  list,
  formatCount,
  compactText,
  displayText,
  formatDateTime,
  formatPrice,
  formatFlightTime,
}) {
  function adaptHotels(payload) {
    const items = getRows(payload).map(row => {
      const amenities = list(row.amenities);
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

  function adaptYelp(payload) {
    const items = getRows(payload).map(row => {
      const chips = [];
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (row.price && row.rating != null) chips.push(String(row.price));
      const categories = list(row.categories).slice(0, 3).join(' · ');
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

  function adaptOpenTableReviews(payload) {
    const format = String(payload.output_format || 'json').toLowerCase();
    if (format !== 'json' && payload.content) {
      const plainContent = format === 'html'
        ? String(payload.content).replace(/<[^>]*>/g, ' ')
        : String(payload.content);
      return {
        kind: 'local',
        eyebrow: 'OpenTable reviews',
        heading: payload.restaurant_name || payload.rid || 'OpenTable restaurant',
        subtitle: `${format === 'markdown' ? 'Markdown' : 'HTML'} provider response`,
        actionUrl: payload.restaurant_url,
        actionLabel: 'Open on OpenTable',
        items: [{
          title: `${format === 'markdown' ? 'Markdown' : 'HTML'} review document`,
          url: payload.restaurant_url,
          primary: payload.content_chars != null
            ? `${formatCount(payload.content_chars)} characters`
            : '',
          chips: ['Untrusted external content'],
          details: [compactText(plainContent, 420)],
          actionLabel: 'Open restaurant',
        }],
      };
    }

    const rows = Array.isArray(payload.reviews)
      ? payload.reviews.slice(0, 5)
      : getRows(payload);
    const items = rows.map((row, index) => {
      const user = row.user && typeof row.user === 'object' ? row.user : {};
      const rating = row.rating && typeof row.rating === 'object' ? row.rating : {};
      const response = row.response && typeof row.response === 'object' ? row.response : {};
      const images = Array.isArray(row.images) ? row.images : [];
      const categoryRatings = [
        rating.food != null ? `Food ${rating.food}` : '',
        rating.service != null ? `Service ${rating.service}` : '',
        rating.ambience != null ? `Ambience ${rating.ambience}` : '',
        rating.value != null ? `Value ${rating.value}` : '',
        rating.noise ? `Noise: ${rating.noise}` : '',
      ].filter(Boolean).join(' · ');
      const chips = [
        user.location,
        row.dined_at ? `Dined ${formatDateTime(row.dined_at)}` : '',
        user.vip === true ? 'VIP diner' : '',
      ].filter(Boolean).map(String);
      return {
        title: user.name || `Review ${index + 1}`,
        url: payload.restaurant_url,
        image: images[0]?.url || user.avatar,
        primary: rating.overall != null ? `★ ${rating.overall}` : '',
        chips,
        details: [
          row.text ? compactText(row.text, 320) : '',
          categoryRatings,
          response.content
            ? `Restaurant response: ${compactText(response.content, 180)}`
            : '',
        ].filter(Boolean),
        actionLabel: 'Open restaurant',
      };
    });
    const summary = payload.reviews_summary && typeof payload.reviews_summary === 'object'
      ? payload.reviews_summary
      : {};
    const ratings = summary.ratings_summary && typeof summary.ratings_summary === 'object'
      ? summary.ratings_summary
      : {};
    const subtitle = [
      ratings.overall != null ? `★ ${ratings.overall} overall` : '',
      summary.reviews_count != null
        ? `${formatCount(summary.reviews_count)} total reviews`
        : '',
      payload.total_pages != null ? `Page ${payload.page || 1} of ${payload.total_pages}` : '',
    ].filter(Boolean).join(' · ');
    return {
      kind: 'local',
      layout: 'rail',
      eyebrow: 'OpenTable reviews',
      heading: payload.restaurant_name || payload.rid || 'OpenTable restaurant',
      subtitle,
      actionUrl: payload.restaurant_url,
      actionLabel: 'Open on OpenTable',
      items,
    };
  }

  function adaptTripadvisor(payload) {
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
          details: row.text ? [compactText(row.text, 260)] : [],
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
        image: place.thumbnail || list(place.images)[0],
        primary: place.rating != null ? `★ ${place.rating}` : '',
        chips: placeChips,
        details: [
          place.address,
          list(place.categories).slice(0, 3).join(' · '),
          place.description ? compactText(place.description, 220) : '',
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
            list(row.categories).slice(0, 3).join(' · '),
            row.additional_info ? compactText(row.additional_info, 180) : '',
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

    const items = getRows(payload).map(row => {
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
          row.description ? compactText(row.description, 220) : '',
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

  function adaptFlights(payload) {
    const currency = payload.currency || 'USD';
    const items = getRows(payload).map((row, index) => {
      const airlines = list(row.airlines).join(', ');
      const chips = [];
      const flightNumbers = list(row.flight_numbers).join(', ');
      if (flightNumbers) chips.push(flightNumbers);
      if (row.departure_time) chips.push(`Departs ${formatFlightTime(row.departure_time)}`);
      if (row.arrival_time) chips.push(`Arrives ${formatFlightTime(row.arrival_time)}`);
      const route = [row.departure_airport, row.arrival_airport].filter(Boolean).join(' → ');
      return {
        title: airlines || `Flight option ${index + 1}`,
        primary: formatPrice(row.price, currency),
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

  function adaptTravelExplore(payload) {
    const currency = payload.currency || 'USD';
    const items = getRows(payload).map((row, index) => {
      const chips = [];
      if (row.hotel_price != null) {
        chips.push(`Hotel signal ${formatPrice(row.hotel_price, currency)}`);
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
          ? `${formatPrice(row.flight_price, currency)} flight signal`
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

  function adaptGoogleEvents(payload) {
    const items = getRows(payload).map((row, index) => {
      const venue = row.venue && typeof row.venue === 'object' ? row.venue : {};
      const tickets = Array.isArray(row.ticket_info)
        ? row.ticket_info.filter(ticket => ticket && typeof ticket === 'object')
        : (row.ticket_info && typeof row.ticket_info === 'object' ? [row.ticket_info] : []);
      const firstTicket = tickets.find(ticket => ticket.link) || {};
      const timing = row.when || row.date_text || row.time || row.start_date || '';
      const address = row.address_text || list(row.address).join(', ');
      const chips = [
        row.type,
        row.price,
        venue.rating != null ? `Venue ★ ${venue.rating}` : '',
        venue.reviews != null ? `${formatCount(venue.reviews)} venue reviews` : '',
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
          compactText(row.description, 260),
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

  function adaptMaps(payload) {
    const items = getRows(payload).map(row => {
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

  function adaptGoogleLocal(payload) {
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
          compactText(row.description, 220),
        ].filter(Boolean),
        actionLabel: row.website ? 'Open website' : 'Open place',
      };
    };

    const resultItems = getRows(payload).map((row, index) => placeItem(row, index));
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
      details: [compactText(displayText(row.places), 220)].filter(Boolean),
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

  function adaptGoogleLocalServices(payload) {
    const rows = getRows(payload);
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

  return {
    adaptHotels,
    adaptYelp,
    adaptOpenTableReviews,
    adaptTripadvisor,
    adaptFlights,
    adaptTravelExplore,
    adaptGoogleEvents,
    adaptMaps,
    adaptGoogleLocal,
    adaptGoogleLocalServices,
  };
};
