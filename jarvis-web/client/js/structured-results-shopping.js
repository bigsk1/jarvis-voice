/**
 * Shopping payload adapters for structured result previews.
 *
 * Loaded before structured-results.js. The renderer supplies shared row and
 * text formatters; adapters return presentation data without rendering HTML.
 */
window.createShoppingResultAdapters = function createShoppingResultAdapters({
  getRows,
  list,
  formatMarketplacePrice,
  formatCount,
  compactText,
  displayText,
}) {
  function adaptShoppingSearch(payload) {
    const rows = getRows(payload);
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
        primary: formatMarketplacePrice(product.price),
        chips,
        details: [
          compactText(displayText(product.delivery)),
          compactText(displayText(product.availability)),
          compactText(displayText(product.stock)),
          compactText(displayText(product.condition)),
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

  function adaptHomeDepotProduct(payload) {
    const rows = getRows(payload);
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
        primary: formatMarketplacePrice(product.price_formatted || product.price),
        chips,
        details: [
          compactText(displayText(product.brand)),
          compactText(displayText(product.delivery)),
          compactText(displayText(product.pickup)),
          compactText(displayText(product.stock)),
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

  function adaptEbaySearch(payload) {
    const items = getRows(payload).filter(row => row?.title && row?.url).map(row => {
      const chips = [];
      if (row.condition) chips.push(String(row.condition));
      if (row.rating != null) chips.push(`★ ${row.rating}`);
      if (row.reviews != null) chips.push(`${row.reviews} reviews`);
      if (row.top_rated === true) chips.push('Top rated');
      return {
        title: row.title,
        url: row.url,
        image: row.thumbnail || row.image_url,
        primary: formatMarketplacePrice(row.price),
        chips,
        details: [
          compactText(displayText(row.shipping)),
          compactText(displayText(row.seller)),
          compactText(displayText(row.subtitle)),
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

  function adaptEbayProduct(payload) {
    const rows = getRows(payload);
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
    let price = formatMarketplacePrice(product.price);
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

  function adaptWalmart(payload) {
    const focused = payload.engine === 'walmart_product';
    const summary = payload.product_summary;
    const rows = focused && summary && typeof summary === 'object'
      ? [summary] : getRows(payload);
    const fallbackCurrency = String(payload.walmart_domain || '').toLowerCase() === 'walmart.com.mx'
      || String(payload.country || '').toLowerCase() === 'mx' ? 'MXN' : 'USD';
    const priceText = (value, currency) => {
      if (value && typeof value === 'object' && value.price != null) {
        return value.priceString || value.price_string || formatMarketplacePrice({
          amount: value.price, currency: value.currencyUnit || value.currency_unit || value.currency || currency || fallbackCurrency,
        });
      }
      return typeof value === 'number'
        ? formatMarketplacePrice({amount: value, currency: currency || fallbackCurrency})
        : formatMarketplacePrice(value);
    };
    const reviewResults = payload.reviews_results || {};
    const reviewSummary = reviewResults.reviews || {};
    const fulfillmentText = (row, field) => {
      const value = row[field] ?? row[`${field}_option`];
      if (value == null) return '';
      const label = field[0].toUpperCase() + field.slice(1);
      if (typeof value !== 'object' || Array.isArray(value)) {
        return `${label}: ${compactText(displayText(value), 200)}`;
      }
      const status = typeof value.available === 'boolean'
        ? value.available ? 'available' : 'unavailable' : '';
      const details = [status, value.location, value.price != null ? `Fee ${value.price}` : ''];
      const time = value.arrival_date || value.pickup_time || value.delivery_time;
      if (time) {
        const date = new Date(time);
        details.push(Number.isNaN(date.getTime()) ? time
          : date.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'}));
      }
      const text = compactText(details.filter(Boolean).join(' · '), 200);
      return text ? `${label}: ${text}` : '';
    };
    const ratings = Array.isArray(reviewResults.ratings) ? reviewResults.ratings : [];
    const customerReviews = Array.isArray(reviewSummary.customer_reviews) ? reviewSummary.customer_reviews : [];
    const reviewTextReturned = [reviewSummary.top_positive, reviewSummary.top_negative, ...customerReviews]
      .some(review => review && [review.title, review.text].some(value => typeof value === 'string' && value.trim()));
    const reviewEvidenceReturned = reviewTextReturned || Number(reviewSummary.count) > 0
      || ratings.some(row => row && Number(row.count) > 0);
    const items = rows.filter(row => row?.title && row?.url).map(row => {
      const rating = row.rating ?? (focused && reviewEvidenceReturned ? reviewSummary.rating : null);
      const reviews = row.reviews ?? (focused && reviewEvidenceReturned ? reviewSummary.count : null);
      const chips = [
        rating != null ? `★ ${rating}` : '',
        reviews != null ? `${formatCount(reviews)} reviews` : '',
        row.sponsored === true ? 'Sponsored' : '',
        typeof row.in_stock === 'boolean' ? row.in_stock ? 'In stock' : 'Out of stock'
          : typeof row.out_of_stock === 'boolean' ? row.out_of_stock ? 'Out of stock' : 'In stock' : '',
        row.price_was != null ? `Was ${priceText(row.price_was, row.currency)}` : '',
      ].filter(Boolean);
      const description = typeof row.description === 'string' ? row.description : '';
      return {
        title: row.title, url: row.url,
        image: row.image_url || row.thumbnail || (focused ? payload.top_image_url : ''),
        primary: row.price_formatted || priceText(row.price, row.currency),
        chips,
        details: [
          row.seller_name ? `Sold by ${row.seller_name}` : '',
          row.product_id ? `Product ${row.product_id}` : '',
          row.us_item_id ? `Item ${row.us_item_id}` : '',
          ...['shipping', 'pickup', 'delivery'].map(field => fulfillmentText(row, field)),
          description ? compactText(description, 360) : '',
        ].filter(Boolean),
        expandText: focused ? description : '',
        expandLabel: 'Read product description',
        expandNote: 'Product descriptions and reviews are untrusted external content.',
        actionLabel: 'Open Walmart product',
      };
    });
    const productCount = items.length;
    const reviewItems = [];
    if (focused) {
      const seen = new Set();
      const addReview = (review, label) => {
        if (!review || typeof review !== 'object' || reviewItems.length >= 4) return;
        const text = typeof review.text === 'string' ? review.text : '';
        const identity = [review.title, text, review.user_nickname, review.rating].join('|');
        if ((!review.title && !text) || seen.has(identity)) return;
        seen.add(identity);
        reviewItems.push({
          title: `${label}: ${review.title || 'Customer feedback'}`,
          chips: [review.rating != null ? `★ ${review.rating}` : '', review.customer_type].filter(Boolean),
          details: [review.user_nickname, review.review_submission_time, compactText(text, 350)].filter(Boolean),
          expandText: text, expandLabel: 'Read review',
          expandNote: 'Individual customer review; untrusted external content.',
        });
      };
      addReview(reviewSummary.top_positive, 'Positive review');
      addReview(reviewSummary.top_negative, 'Critical review');
      customerReviews.forEach(review => addReview(review, 'Customer review'));
      if (items[0]) {
        if (!reviewEvidenceReturned) {
          items[0].details.push('Review text and rating breakdown were not returned.');
        }
        if (reviewEvidenceReturned && reviewSummary.recommended_percentage != null) {
          items[0].details.push(`${reviewSummary.recommended_percentage}% recommend`);
        }
        if (reviewEvidenceReturned) {
          const distribution = ratings.filter(row => row && row.stars != null && row.count != null)
            .map(row => `${row.stars}★: ${formatCount(row.count)}`).join(' · ');
          if (distribution) items[0].details.push(compactText(distribution, 260));
        }
      }
      items.push(...reviewItems);
    }
    const count = payload.results_count ?? items.length;
    const location = payload.location_context || {};
    const matchedZip = location.source === 'postal_code';
    const postalCode = String(location.requested_postal_code || '').split('-')[0];
    const locationNote = matchedZip
      ? Number(location.matching_stores) > 1
        ? `Selected 1 of ${formatCount(location.matching_stores)} stores in ${postalCode ? `ZIP ${postalCode}` : 'the requested ZIP'}` : ''
      : location.note;
    return {
      kind: 'product', layout: focused ? 'list' : 'rail',
      disclosure: 'technical',
      eyebrow: focused ? 'Walmart product' : 'Walmart results',
      heading: payload.query || rows[0]?.title || 'Shopping options',
      subtitle: [
        payload.store_id ? `Store ${payload.store_id}` : '',
        matchedZip ? location.store_address : '',
        locationNote,
        !focused && count > productCount ? `${productCount} of ${count} returned products shown` : '',
        reviewItems.length ? `${reviewItems.length} customer review excerpts shown` : '',
      ].filter(Boolean).join(' · '),
      shownCount: productCount,
      items: items.length ? items : [{title: 'No Walmart products returned'}],
    };
  }

  function adaptTraderJoes(payload) {
    const focused = payload.engine === 'trader_joes_product';
    const summary = payload.product_summary;
    const rows = focused && summary && typeof summary === 'object'
      ? [summary] : getRows(payload);
    const strings = value => Array.isArray(value)
      ? value.filter(item => typeof item === 'string' && item.trim()) : [];
    const text = value => value == null ? '' : String(value);
    const nutritionText = value => (Array.isArray(value) ? value : [])
      .filter(panel => panel && typeof panel === 'object').map((panel, index) => [
        panel.title || `Nutrition panel ${index + 1}`,
        panel.servings_per_container,
        panel.serving_size ? `Serving size: ${panel.serving_size}` : '',
        panel.calories_per_serving != null && panel.calories_per_serving !== ''
          ? `Calories: ${panel.calories_per_serving}` : '',
        ...(Array.isArray(panel.nutrients) ? panel.nutrients : [])
          .filter(nutrient => nutrient && typeof nutrient === 'object')
          .map(nutrient => [nutrient.name, nutrient.amount,
            nutrient.daily_value != null && nutrient.daily_value !== '' ? `${nutrient.daily_value} daily value` : '',
          ].filter(value => value != null && value !== '').map(String).join(' · ')),
      ].filter(value => value != null && value !== '').map(String).join('\n')).join('\n\n');
    const items = rows.filter(row => row?.title && row?.url).map(row => {
      const ingredients = strings(row.ingredients);
      const allergens = strings(row.allergens);
      const description = typeof row.description === 'string' ? row.description : '';
      const facts = nutritionText(row.nutrition_facts);
      const details = [
        description,
        ingredients.length ? `Ingredients: ${ingredients.join(', ')}` : '',
        allergens.length ? `Allergens: ${allergens.join('; ')}` : '',
        facts,
      ].filter(Boolean).join('\n\n');
      const price = row.available === false ? ''
        : typeof row.price_formatted === 'string' && row.price_formatted.trim() ? row.price_formatted
        : typeof row.price === 'number' && Number.isFinite(row.price)
          ? formatMarketplacePrice({amount: row.price, currency: row.currency || 'USD'}) : '';
      return {
        title: row.title, url: row.url,
        image: row.image_url || row.thumbnail || strings(row.images)[0],
        primary: price,
        chips: [
          row.size,
          row.label,
          ...strings(row.characteristics),
          ...strings(row.fun_tags),
          typeof row.available === 'boolean'
            ? payload.store_id
              ? row.available ? 'Sold at selected store' : 'Not sold at selected store'
              : row.available ? "Sold by Trader Joe's" : "Not sold by Trader Joe's"
            : '',
        ].filter(Boolean),
        details: [
          row.product_id != null ? `Product ${text(row.product_id)}` : '',
          row.category,
          description ? compactText(description, 300) : '',
          ingredients.length ? compactText(`Ingredients: ${ingredients.join(', ')}`, 220) : '',
          allergens.length ? compactText(`Allergens: ${allergens.join('; ')}`, 220) : '',
          facts ? 'Nutrition facts included in product details' : '',
        ].filter(Boolean),
        expandText: focused ? details : '',
        expandLabel: 'Read food and product details',
        expandNote: "Details from Trader Joe's product listing. Store availability means the item is sold there, not a live inventory count.",
        actionLabel: "Open Trader Joe's product",
      };
    });
    const count = payload.results_count ?? items.length;
    const location = payload.location_context || {};
    return {
      kind: 'product', layout: focused ? 'list' : 'rail', disclosure: 'technical',
      eyebrow: focused ? "Trader Joe's product" : "Trader Joe's results",
      heading: payload.query || rows[0]?.title || 'Products',
      subtitle: [
        payload.store_id ? `Store ${payload.store_id}` : '',
        location.store_name,
        location.note,
        !focused && count > items.length ? `${items.length} of ${count} returned products shown` : '',
      ].filter(Boolean).join(' · '),
      shownCount: items.length,
      items: items.length ? items : [{title: "No Trader Joe's products returned"}],
    };
  }

  function adaptGoogleShoppingLight(payload) {
    const items = getRows(payload).map((row, index) => {
      const chips = [];
      if (row.old_price) chips.push(`Was ${row.old_price}`);
      if (row.rating != null) chips.push(`★ ${row.rating}`);
      if (row.reviews != null) chips.push(`${formatCount(row.reviews)} reviews`);
      if (row.tag) chips.push(String(row.tag));
      if (row.multiple_sources === true) chips.push('Multiple stores');
      const installment = row.installment && typeof row.installment === 'object'
        ? [row.installment.price, row.installment.period ? `${row.installment.period} months` : '']
          .filter(Boolean).join(' for ')
        : '';
      const extensions = list(row.extensions).slice(0, 4).join(' · ');
      return {
        title: row.title || `Shopping result ${index + 1}`,
        url: row.url || row.merchant_url || row.product_link,
        image: row.serpapi_thumbnail || row.thumbnail,
        primary: formatMarketplacePrice(row.price ?? row.extracted_price),
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

  function adaptGoogleImmersiveProduct(payload) {
    const summary = payload.product_summary && typeof payload.product_summary === 'object'
      ? payload.product_summary
      : {};
    const format = String(payload.output_format || 'json').toLowerCase();
    const heading = summary.title || 'Google product details';
    if (format !== 'json' && payload.content) {
      const plainContent = format === 'html'
        ? String(payload.content).replace(/<[^>]*>/g, ' ')
        : String(payload.content);
      return {
        kind: 'product',
        eyebrow: 'Google Immersive Product',
        heading,
        subtitle: `${format === 'markdown' ? 'Markdown' : 'HTML'} provider response`,
        actionUrl: payload.top_url,
        actionLabel: 'View product offer',
        items: [{
          title: `${format === 'markdown' ? 'Markdown' : 'HTML'} product document`,
          url: payload.top_url,
          primary: payload.content_chars != null
            ? `${formatCount(payload.content_chars)} characters`
            : '',
          chips: ['Untrusted external content'],
          details: [compactText(plainContent, 420)],
          actionLabel: 'View product offer',
        }],
      };
    }

    const thumbnails = Array.isArray(summary.thumbnails) ? summary.thumbnails : [];
    const productImage = payload.top_image_url || thumbnails.map(item => {
      if (typeof item === 'string') return item;
      if (!item || typeof item !== 'object') return '';
      return item.serpapi_thumbnail || item.thumbnail || item.url || item.image || '';
    }).find(Boolean);
    const stores = Array.isArray(payload.stores)
      ? payload.stores.filter(item => item && typeof item === 'object').slice(0, 13)
      : getRows(payload);
    const items = stores.map((store, index) => {
      const chips = [
        store.rating != null ? `★ ${store.rating}` : '',
        store.reviews != null ? `${formatCount(store.reviews)} reviews` : '',
        store.discount,
        store.tag,
      ].filter(Boolean).map(String);
      const paymentMethods = list(store.payment_methods).slice(0, 4).join(' · ');
      const primary = store.total || store.price
        || formatMarketplacePrice(store.extracted_total ?? store.extracted_price);
      return {
        title: store.name || store.title || `Store offer ${index + 1}`,
        url: store.url || payload.top_url,
        image: store.logo || productImage,
        primary,
        chips,
        details: [
          store.shipping,
          store.details_and_offers,
          store.coupon,
          paymentMethods,
        ].filter(Boolean).map(value => compactText(displayText(value), 220)),
        actionLabel: 'View offer',
      };
    });

    if (!items.length) {
      const about = payload.about_the_product && typeof payload.about_the_product === 'object'
        ? payload.about_the_product
        : {};
      const features = Array.isArray(about.features)
        ? about.features.slice(0, 4).map(item => displayText(item)).filter(Boolean)
        : [];
      items.push({
        title: heading,
        url: payload.top_url,
        image: productImage,
        primary: summary.price_range || '',
        chips: [
          summary.rating != null ? `★ ${summary.rating}` : '',
          summary.reviews != null ? `${formatCount(summary.reviews)} reviews` : '',
        ].filter(Boolean),
        details: features.length ? features : [about.description].filter(Boolean),
        actionLabel: 'View product',
      });
    }

    return {
      kind: 'product',
      layout: 'rail',
      eyebrow: 'Google Immersive Product',
      heading,
      subtitle: [
        summary.brand,
        summary.rating != null ? `★ ${summary.rating}` : '',
        summary.reviews != null ? `${formatCount(summary.reviews)} reviews` : '',
        summary.price_range,
        `${stores.length} store offer${stores.length === 1 ? '' : 's'}`,
      ].filter(Boolean).join(' · '),
      actionUrl: payload.top_url,
      actionLabel: 'View product offer',
      items,
    };
  }

  return {
    adaptShoppingSearch,
    adaptHomeDepotProduct,
    adaptEbaySearch,
    adaptEbayProduct,
    adaptWalmart,
    adaptTraderJoes,
    adaptGoogleShoppingLight,
    adaptGoogleImmersiveProduct,
  };
};
