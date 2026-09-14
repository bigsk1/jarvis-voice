/**
 * HTML fragments for assistant tool results.
 *
 * ChatUI prepares tool entries and selects which surfaces to display. These
 * helpers return markup; message identity, events and cleanup stay in ChatUI.
 * Loaded after utils.js and before chat.js as a classic script.
 */
window.assistantMessageRenderer = {
  renderToolCards(entries, renderCard) {
    if (!entries.length) return '';
    return '<div class="tool-cards">' + entries.map(renderCard).join('') + '</div>';
  },

  renderConvertedFile(convertResult) {
    let convertedFileHtml = '';
    if (convertResult && convertResult.stash_ref) {
      const stashMatch = convertResult.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
      if (stashMatch) {
        // Use existing stash route: /api/stash/{space_id}/{file_id}
        const stashUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
        const targetFormat = convertResult.target_format || '';
        const filename = convertResult.filename || 'converted file';
        const sizeChange = convertResult.size_change || '';

        // Check if it's an image format
        const imageFormats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico'];
        const isImage = imageFormats.includes(targetFormat.toLowerCase());

        // Check if it's a video format
        const videoFormats = ['mp4', 'webm', 'mov', 'avi', 'mkv'];
        const isVideo = videoFormats.includes(targetFormat.toLowerCase());

        // Check if it's an audio format
        const audioFormats = ['mp3', 'wav', 'flac', 'ogg', 'aac', 'm4a'];
        const isAudio = audioFormats.includes(targetFormat.toLowerCase());

        // Download button HTML (reusable)
        const downloadBtn = `
            <a href="${stashUrl}" download="${filename}" class="convert-download-btn" title="Download ${filename}">
              ⬇️ Download ${targetFormat.toUpperCase()}
            </a>
          `;

        if (isImage) {
          // Display image inline with download button
          convertedFileHtml = `
              <div class="converted-media-container">
                <div class="message-image converted-file" onclick="window.showImageLightbox('${stashUrl}')">
                  <img src="${stashUrl}" alt="Converted ${targetFormat.toUpperCase()}" loading="lazy">
                  <div class="image-overlay">
                    <span>🔍 Click to expand</span>
                  </div>
                </div>
                <div class="convert-actions">
                  <span class="convert-info">${Utils.escapeHtml(filename)} ${sizeChange ? `(${sizeChange})` : ''}</span>
                  ${downloadBtn}
                </div>
              </div>
            `;
        } else if (isVideo) {
          // Display video player with download button
          convertedFileHtml = `
              <div class="converted-media-container">
                <div class="message-video converted-file">
                  <div class="video-header">
                    <span class="video-icon">🎬</span>
                    <span class="video-title">Converted: ${Utils.escapeHtml(filename)}</span>
                  </div>
                  <video controls preload="metadata" class="video-player">
                    <source src="${stashUrl}" type="video/${targetFormat}">
                    Your browser does not support video playback.
                  </video>
                </div>
                <div class="convert-actions">
                  <span class="convert-info">${sizeChange ? `Size: ${sizeChange}` : ''}</span>
                  ${downloadBtn}
                </div>
              </div>
            `;
        } else if (isAudio) {
          // Display audio player with download button
          convertedFileHtml = `
              <div class="converted-media-container">
                <div class="message-audio converted-file">
                  <div class="audio-header">
                    <span class="audio-icon">🎵</span>
                    <span class="audio-title">Converted: ${Utils.escapeHtml(filename)}</span>
                  </div>
                  <audio controls preload="metadata" class="audio-player">
                    <source src="${stashUrl}" type="audio/${targetFormat}">
                    Your browser does not support audio playback.
                  </audio>
                </div>
                <div class="convert-actions">
                  <span class="convert-info">${sizeChange ? `Size: ${sizeChange}` : ''}</span>
                  ${downloadBtn}
                </div>
              </div>
            `;
        } else {
          // Download link for other formats
          convertedFileHtml = `
              <div class="message-file converted-file">
                <a href="${stashUrl}" download="${filename}" class="file-download-link">
                  <span class="file-icon">📁</span>
                  <span class="file-name">${Utils.escapeHtml(filename)}</span>
                  ${sizeChange ? `<span class="file-size">(${sizeChange})</span>` : ''}
                  <span class="download-icon">⬇️</span>
                </a>
              </div>
            `;
        }
      }
    }
    return convertedFileHtml;
  },

  renderShoppingFallback(toolResultsData, data) {
    let shoppingHtml = '';
    // Shopping/product preview card for focused SerpApi product lookups
    // and single clear product results where a link + image is helpful.
    const serpapiPayload = toolResultsData.serpapi_amazon_search
      || data.serpapi_amazon_search
      || toolResultsData.serpapi_search
      || data.serpapi_search;
    const latestSerpapi = Array.isArray(serpapiPayload)
      ? serpapiPayload[serpapiPayload.length - 1]
      : serpapiPayload;

    if (latestSerpapi && typeof latestSerpapi === 'object') {
      const engine = latestSerpapi.engine;
      const results = Array.isArray(latestSerpapi.top_results) && latestSerpapi.top_results.length > 0
        ? latestSerpapi.top_results
        : (Array.isArray(latestSerpapi.results) ? latestSerpapi.results : []);
      const product = results[0];
      const isFocusedProduct =
        engine === 'amazon_product'
        || Boolean(latestSerpapi.asin)
        || (results.length === 1 && engine === 'amazon');

      if (isFocusedProduct && product && product.url && product.title) {
        const title = Utils.escapeHtml(product.title);
        const link = Utils.escapeHtml(product.url);
        const image = (product.image_url || product.thumbnail) ? Utils.escapeHtml(product.image_url || product.thumbnail) : '';
        const price = product.price ? Utils.escapeHtml(String(product.price)) : '';
        const rating = product.rating != null ? Utils.escapeHtml(String(product.rating)) : '';
        const reviews = product.reviews != null ? Utils.escapeHtml(String(product.reviews)) : '';
        const asin = product.asin ? Utils.escapeHtml(String(product.asin)) : '';
        const metaParts = [];
        if (price) metaParts.push(`<span class="product-chip price">${price}</span>`);
        if (rating) metaParts.push(`<span class="product-chip">⭐ ${rating}</span>`);
        if (reviews) metaParts.push(`<span class="product-chip">${reviews} reviews</span>`);
        if (asin) metaParts.push(`<span class="product-chip">ASIN ${asin}</span>`);

        shoppingHtml = `
          <div class="product-preview-card">
            ${image ? `
              <a class="product-preview-image" href="${link}" target="_blank" rel="noopener noreferrer">
                <img src="${image}" alt="${title}" loading="lazy" referrerpolicy="no-referrer">
              </a>
            ` : ''}
            <div class="product-preview-body">
              <div class="product-preview-label">Amazon Product</div>
              <a class="product-preview-title" href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>
              ${metaParts.length ? `<div class="product-preview-meta">${metaParts.join('')}</div>` : ''}
              <div class="product-preview-actions">
                <a class="product-preview-link" href="${link}" target="_blank" rel="noopener noreferrer">Open product</a>
              </div>
            </div>
          </div>
        `;
      }
    }

    const homeDepotPayload = toolResultsData.serpapi_home_depot || data.serpapi_home_depot;
    const latestHomeDepot = Array.isArray(homeDepotPayload)
      ? homeDepotPayload[homeDepotPayload.length - 1]
      : homeDepotPayload;

    if (!shoppingHtml && latestHomeDepot && typeof latestHomeDepot === 'object') {
      const results = Array.isArray(latestHomeDepot.top_results) && latestHomeDepot.top_results.length > 0
        ? latestHomeDepot.top_results
        : (Array.isArray(latestHomeDepot.results) ? latestHomeDepot.results : []);
      const product = latestHomeDepot.product_details || results[0];

      if (product && product.url && product.title) {
        const title = Utils.escapeHtml(product.title);
        const link = Utils.escapeHtml(product.url);
        const image = (product.image_url || product.thumbnail || latestHomeDepot.top_image_url)
          ? Utils.escapeHtml(product.image_url || product.thumbnail || latestHomeDepot.top_image_url)
          : '';
        const price = (product.price_formatted || product.price) ? Utils.escapeHtml(String(product.price_formatted || product.price)) : '';
        const rating = product.rating != null ? Utils.escapeHtml(String(product.rating)) : '';
        const reviews = product.reviews != null ? Utils.escapeHtml(String(product.reviews)) : '';
        const productId = product.product_id ? Utils.escapeHtml(String(product.product_id)) : '';
        const metaParts = [];
        if (price) metaParts.push(`<span class="product-chip price">${price}</span>`);
        if (rating) metaParts.push(`<span class="product-chip">⭐ ${rating}</span>`);
        if (reviews) metaParts.push(`<span class="product-chip">${reviews} reviews</span>`);
        if (productId) metaParts.push(`<span class="product-chip">Product ID ${productId}</span>`);

        shoppingHtml = `
          <div class="product-preview-card">
            ${image ? `
              <a class="product-preview-image" href="${link}" target="_blank" rel="noopener noreferrer">
                <img src="${image}" alt="${title}" loading="lazy" referrerpolicy="no-referrer">
              </a>
            ` : ''}
            <div class="product-preview-body">
              <div class="product-preview-label">Home Depot Product</div>
              <a class="product-preview-title" href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>
              ${metaParts.length ? `<div class="product-preview-meta">${metaParts.join('')}</div>` : ''}
              <div class="product-preview-actions">
                <a class="product-preview-link" href="${link}" target="_blank" rel="noopener noreferrer">Open product</a>
              </div>
            </div>
          </div>
        `;
      }
    }

    const ebayProductPayload = toolResultsData.serpapi_ebay_product || data.serpapi_ebay_product;
    const latestEbayProduct = Array.isArray(ebayProductPayload)
      ? ebayProductPayload[ebayProductPayload.length - 1]
      : ebayProductPayload;

    if (!shoppingHtml && latestEbayProduct && typeof latestEbayProduct === 'object') {
      const results = Array.isArray(latestEbayProduct.top_results) && latestEbayProduct.top_results.length > 0
        ? latestEbayProduct.top_results
        : (Array.isArray(latestEbayProduct.results) ? latestEbayProduct.results : []);
      const summary = latestEbayProduct.product_summary;
      const product = (summary && typeof summary === 'object') ? summary : results[0];

      if (product && product.title) {
        const linkRaw = product.url || (results[0] && results[0].url);
        if (linkRaw) {
          const title = Utils.escapeHtml(product.title);
          const link = Utils.safeHttpUrlForAttr(linkRaw) || Utils.escapeHtml(linkRaw);
          let image = '';
          if (summary && Array.isArray(summary.image_urls) && summary.image_urls.length > 0) {
            image = Utils.safeHttpUrlForAttr(summary.image_urls[summary.image_urls.length - 1])
              || Utils.safeHttpUrlForAttr(summary.image_urls[0]);
          }
          if (!image && product.thumbnail) {
            image = Utils.safeHttpUrlForAttr(product.thumbnail);
          }
          if (!image && latestEbayProduct.top_image_url) {
            image = Utils.safeHttpUrlForAttr(latestEbayProduct.top_image_url);
          }

          let priceStr = '';
          const buy = summary && typeof summary.buy === 'object' ? summary.buy : null;
          if (buy && buy.buy_it_now && typeof buy.buy_it_now === 'object') {
            const pr = buy.buy_it_now.price;
            if (pr && pr.amount != null && pr.currency) {
              priceStr = `${pr.currency} ${pr.amount}`;
            }
          }
          if (!priceStr && buy && buy.bid && typeof buy.bid === 'object') {
            const pr = buy.bid.price;
            if (pr && pr.amount != null && pr.currency) {
              priceStr = `Bid ${pr.currency} ${pr.amount}`;
            }
          }

          const rating = product.rating != null ? Utils.escapeHtml(String(product.rating)) : '';
          const reviews = product.review_count != null ? Utils.escapeHtml(String(product.review_count)) : '';
          const productId = (latestEbayProduct.product_id || product.product_id)
            ? Utils.escapeHtml(String(latestEbayProduct.product_id || product.product_id))
            : '';
          const metaParts = [];
          if (priceStr) metaParts.push(`<span class="product-chip price">${Utils.escapeHtml(priceStr)}</span>`);
          if (rating) metaParts.push(`<span class="product-chip">⭐ ${rating}</span>`);
          if (reviews) metaParts.push(`<span class="product-chip">${reviews} reviews</span>`);
          if (productId) metaParts.push(`<span class="product-chip">Item ${productId}</span>`);

          shoppingHtml = `
          <div class="product-preview-card">
            ${image ? `
              <a class="product-preview-image" href="${link}" target="_blank" rel="noopener noreferrer">
                <img src="${image}" alt="${title}" loading="lazy">
              </a>
            ` : ''}
            <div class="product-preview-body">
              <div class="product-preview-label">eBay Product</div>
              <a class="product-preview-title" href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>
              ${metaParts.length ? `<div class="product-preview-meta">${metaParts.join('')}</div>` : ''}
              <div class="product-preview-actions">
                <a class="product-preview-link" href="${link}" target="_blank" rel="noopener noreferrer">Open listing</a>
              </div>
            </div>
          </div>
        `;
        }
      }
    }
    return shoppingHtml;
  },
};
