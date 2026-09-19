/** Optional host-scoped origins; callers retain their existing route suffixes. */
(function (global) {
  const configuration = global.__jarvisUINavigationConfig || {};
  delete global.__jarvisUINavigationConfig;
  const normalizeHost = value => String(value || '').toLowerCase()
    .replace(/^\[|\]$/g, '').replace(/\.$/, '');
  const currentHost = normalizeHost(global.location?.hostname);
  const origins = currentHost && currentHost === normalizeHost(configuration.hostname)
    && configuration.urls && typeof configuration.urls === 'object' ? configuration.urls : {};
  const services = new Set(['web', 'canvas', 'memory', 'intelligence', 'docs', 'opencode']);

  global.JarvisUINavigation = Object.freeze({
    url(service, fallbackUrl) {
      if (services.has(service) && Object.prototype.hasOwnProperty.call(origins, service)
          && typeof origins[service] === 'string') return origins[service];
      return fallbackUrl;
    },
  });
})(window);
