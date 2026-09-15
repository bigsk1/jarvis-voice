// Inline the packaged artwork so the panel stylesheet can animate its status ring.
// Keep the image fallback if loading fails; no server connection is needed.
try {
  const response = await fetch(new URL('../assets/jarvis.svg', import.meta.url));
  if (!response.ok) throw new Error(`Logo request failed: ${response.status}`);
  const artwork = new DOMParser().parseFromString(await response.text(), 'image/svg+xml');
  if (artwork.querySelector('parsererror')) throw new Error('Invalid logo SVG');
  for (const container of document.querySelectorAll('.jarvis-logo')) {
    const logo = document.importNode(artwork.documentElement, true);
    logo.setAttribute('aria-hidden', 'true');
    logo.setAttribute('focusable', 'false');
    container.replaceChildren(logo);
  }
} catch (error) {
  console.warn('[Jarvis] Could not animate the logo:', error);
}
