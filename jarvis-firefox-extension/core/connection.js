/** Connection policy shared by settings and the privileged background client. */
export function isLoopbackHost(hostname) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host.endsWith('.localhost') || host === '::1') return true;
  if (!/^\d+\.\d+\.\d+\.\d+$/.test(host)) return false;
  const parts = host.split('.').map(Number);
  if (parts.some(part => part > 255)) return false;
  return parts[0] === 127;
}

export function normalizeServerUrl(input, {allowInsecureLocal = false} = {}) {
  let url;
  try { url = new URL(String(input).trim()); }
  catch { throw new Error('Enter the full Jarvis Web address, including https:// and its port.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('Use an HTTP(S) server address without credentials, query parameters, or fragments.');
  }
  if (url.pathname !== '/') throw new Error('Use the Jarvis Web server origin, without a page or API path.');
  if (url.protocol === 'http:' && (!allowInsecureLocal || !isLoopbackHost(url.hostname))) {
    throw new Error('HTTPS is required for servers on another machine, including private LAN addresses. HTTP is available only for an explicitly enabled localhost connection on this computer.');
  }
  return url.origin;
}

export function originPermission(serverUrl) {
  const url = new URL(serverUrl);
  // Firefox match patterns do not scope host permissions to a port.
  return `${url.protocol}//${url.hostname}/*`;
}

export function pageTextSupported(status) {
  return status?.extension?.features?.text === true;
}

export function assertCapabilities(status) {
  const contract = status?.extension;
  if (contract?.api !== 1 || contract.socket_auth !== true ||
      ['chat', 'images', 'conversations', 'recovery', 'cancel'].some(key => contract.features?.[key] !== true)) {
    throw new Error('This Jarvis server does not support Companion API 1 with authenticated sockets. Update Jarvis Web before connecting.');
  }
  if (typeof status?.features?.auth !== 'boolean') throw new Error('The server did not advertise its authentication requirements.');
  return contract;
}
