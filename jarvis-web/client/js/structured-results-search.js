/**
 * Search payload adapters for structured result previews.
 *
 * Loaded before structured-results.js. The renderer supplies shared row and
 * text formatters; adapters return presentation data without rendering HTML.
 */
window.createSearchResultAdapters = function createSearchResultAdapters({
  getRows,
  list,
  formatCount,
  compactText,
  formatDateTime,
}) {
  function adaptSearchIndex(payload) {
    const items = getRows(payload).map(row => {
      const chips = [];
      if (row.date) chips.push(String(row.date));
      if (row.language) chips.push(String(row.language).toUpperCase());
      const sitelinks = list(row.sitelinks);
      if (sitelinks.length) chips.push(`${sitelinks.length} related links`);
      return {
        title: row.title || 'Indexed webpage',
        url: row.url || row.link,
        image: row.image_url || row.thumbnail,
        primary: row.displayed_link || row.source || '',
        chips,
        details: row.snippet ? [compactText(row.snippet, 280)] : [],
        actionLabel: 'Open source',
      };
    });
    const mode = String(payload.mode || 'standard').toLowerCase();
    const resultCount = payload.results_count ?? items.length;
    const total = payload.total_results;
    const countText = total != null
      ? `${formatCount(total)} indexed matches`
      : `${resultCount} source${Number(resultCount) === 1 ? '' : 's'} shown`;
    const related = list(payload.related_searches).slice(0, 3).join(' · ');
    return {
      kind: 'generic',
      layout: 'rail',
      eyebrow: mode === 'deep' ? 'Search Index · Deep recall' : 'Search Index',
      heading: payload.query || 'Indexed web sources',
      subtitle: related ? `${countText} · Related: ${related}` : countText,
      items,
    };
  }

  function adaptGoogleNewsLight(payload) {
    const resultItems = getRows(payload).map((row, index) => {
      const chips = [];
      if (row.date) chips.push(String(row.date));
      return {
        title: row.title || `News article ${index + 1}`,
        url: row.url || row.link,
        image: row.thumbnail,
        primary: row.source || '',
        chips,
        details: row.snippet ? [compactText(row.snippet, 280)] : [],
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

  function adaptGoogleImagesLight(payload) {
    const items = getRows(payload).map((row, index) => {
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

  function adaptGoogleTrends(payload) {
    const dataType = String(payload.data_type || 'interest_over_time').toLowerCase();
    const items = getRows(payload).map((row, index) => {
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
      heading: payload.query || list(payload.queries).join(', ') || 'Trend analysis',
      subtitle: [view, scope].filter(Boolean).join(' · '),
      actionUrl: payload.trends_url,
      actionLabel: 'Open Google Trends',
      items,
    };
  }

  function adaptGoogleSports(payload) {
    const resultKind = String(payload.results_kind || '').toLowerCase();
    const items = getRows(payload).map((row, index) => {
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
            ? formatDateTime(row.start_time)
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

  function adaptGoogleTrendingNow(payload) {
    const action = String(payload.action || 'trending_now').toLowerCase();
    if (action === 'news') {
      const items = getRows(payload).map((row, index) => ({
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

    const items = getRows(payload).map((row, index) => {
      const chips = [];
      if (row.active === true) chips.push('Active now');
      else if (row.active === false) chips.push('Ended');
      if (row.increase_percentage != null) chips.push(`+${row.increase_percentage}%`);
      const categories = list(row.category_names).slice(0, 3).join(' · ');
      if (categories) chips.push(categories);
      const related = list(row.trend_breakdown).slice(0, 4).join(' · ');
      return {
        title: row.query || row.title || `Trend ${index + 1}`,
        url: row.google_trends_url,
        primary: row.search_volume != null
          ? `${formatCount(row.search_volume)} searches`
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

  return {
    adaptSearchIndex,
    adaptGoogleNewsLight,
    adaptGoogleImagesLight,
    adaptGoogleTrends,
    adaptGoogleSports,
    adaptGoogleTrendingNow,
  };
};
