/**
 * Inline the animated Jarvis HUD logo SVG (fetch + inject).
 * Containers need class "jarvis-hud-logo"; add "online" or "offline" for state.
 */
(function () {
  const HUD_SVG_URL = '/static/assets/jarvis-hud-logo.svg';

  function loadJarvisHudLogo(container, { online = true } = {}) {
    if (!container || container.querySelector('svg.hud-svg')) {
      return Promise.resolve();
    }

    return fetch(HUD_SVG_URL, { cache: 'no-cache' })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((svgMarkup) => {
        const cleaned = svgMarkup.replace(/<\?xml[^?]*\?>\s*/i, '');
        container.insertAdjacentHTML('beforeend', cleaned);

        const svg = container.querySelector('svg');
        if (svg) {
          svg.classList.add('hud-svg');
          svg.classList.toggle('online', online);
          svg.classList.toggle('offline', !online);
        }

        container.classList.toggle('online', online);
        container.classList.toggle('offline', !online);
      })
      .catch((err) => console.warn('[Jarvis HUD] logo load failed:', err));
  }

  function initJarvisHudLogos() {
    document.querySelectorAll('.jarvis-hud-logo').forEach((el) => {
      const online = !el.classList.contains('offline');
      loadJarvisHudLogo(el, { online });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initJarvisHudLogos);
  } else {
    initJarvisHudLogos();
  }

  window.JarvisHudLogo = { load: loadJarvisHudLogo, init: initJarvisHudLogos };
})();
