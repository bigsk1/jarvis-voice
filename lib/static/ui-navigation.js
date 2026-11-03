/** Optional host-scoped origins; callers retain their existing route suffixes. */
(function (global) {
  const configuration = global.__jarvisUINavigationConfig || {};
  delete global.__jarvisUINavigationConfig;
  const normalizeHost = value => String(value || '').toLowerCase()
    .replace(/^\[|\]$/g, '').replace(/\.$/, '');
  const currentHost = normalizeHost(global.location?.hostname);
  const origins = currentHost && currentHost === normalizeHost(configuration.hostname)
    && configuration.urls && typeof configuration.urls === 'object' ? configuration.urls : {};
  const services = new Set(['web', 'canvas', 'memory', 'intelligence', 'docs', 'opencode', 'workflows']);
  const mobileWorkflowNavigation = global.matchMedia?.('(max-width: 768px)');
  const revealedWorkflowsLinks = new WeakSet();

  function updateWorkflowsVisibility(link) {
    const mobile = mobileWorkflowNavigation?.matches === true;
    link.hidden = mobile;
    if (mobile) link.style.setProperty('display', 'none', 'important');
    else link.style.removeProperty('display');
  }

  mobileWorkflowNavigation?.addEventListener('change', () => {
    global.document?.querySelectorAll('[data-jarvis-workflows-link]').forEach(link => {
      if (revealedWorkflowsLinks.has(link)) updateWorkflowsVisibility(link);
    });
  });

  function showWorkflowsLink(origin) {
    const document = global.document;
    if (!document || origin === global.location.origin) return;
    let links = [...document.querySelectorAll('[data-jarvis-workflows-link]')];
    if (!links.length) {
      const container = document.querySelector('.header-links')
        || document.querySelector('.header-right')
        || document.querySelector('.header-actions');
      if (!container) return;
      const link = document.createElement('a');
      link.setAttribute('data-jarvis-workflows-link', '');
      link.className = container.classList.contains('header-links') ? 'header-link'
        : container.classList.contains('header-actions') ? 'ghost-btn'
        : container.querySelector('.icon-btn') ? 'icon-btn' : 'btn btn-secondary';
      link.textContent = '🔀';
      link.setAttribute('aria-label', 'Open workflow builder');
      container.appendChild(link);
      links = [link];
    }
    for (const link of links) {
      link.href = origin;
      link.target = '_blank';
      link.rel = 'noopener';
      link.title = 'Open workflow builder';
      revealedWorkflowsLinks.add(link);
      updateWorkflowsVisibility(link);
    }
  }

  async function discoverWorkflows() {
    if (origins.workflows) {
      showWorkflowsLink(origins.workflows);
      return;
    }
    // An unconfigured optional service must not add a dead navigation link.
    // HTTPS deployments need an explicit browser-reachable HTTPS origin.
    if (global.location?.protocol !== 'http:' || !global.fetch) return;
    const endpoint = new URL(global.location.origin);
    endpoint.port = '5005';
    if (endpoint.origin === global.location.origin) return;
    endpoint.pathname = '/api/status';
    const controller = new global.AbortController();
    const timeout = global.setTimeout(() => controller.abort(), 1500);
    try {
      const response = await global.fetch(endpoint.href, {
        credentials: 'omit', cache: 'no-store', signal: controller.signal,
      });
      if (!response.ok) return;
      const status = await response.json();
      if (status?.ok === true && status.service === 'jarvis-workflows') {
        showWorkflowsLink(endpoint.origin);
      }
    } catch { /* The builder is optional; leave its navigation link hidden. */ }
    finally { global.clearTimeout(timeout); }
  }

  global.JarvisUINavigation = Object.freeze({
    loginDestination(requested) {
      try {
        const target = new URL(requested || '/', global.location.origin);
        if (['http:', 'https:'].includes(target.protocol)
            && target.origin === global.location.origin
            && !target.username && !target.password) {
          // Keep the validated absolute URL: a normalized pathname can start
          // with // and become a different origin if navigation reparses it.
          return target.href;
        }
      } catch { /* Invalid destinations return to the main app. */ }
      return '/';
    },
    url(service, fallbackUrl) {
      if (services.has(service) && Object.prototype.hasOwnProperty.call(origins, service)
          && typeof origins[service] === 'string') return origins[service];
      return fallbackUrl;
    },
  });

  if (global.document) {
    if (global.document.readyState === 'loading') {
      global.document.addEventListener('DOMContentLoaded', discoverWorkflows, {once: true});
    } else {
      discoverWorkflows();
    }
  }
})(window);
