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
    adaptGoogleShoppingLight,
    adaptGoogleImmersiveProduct,
  };
};
