/** Only display bounded text and raster pixels supplied by the authenticated server. */
export function normalizeProfile(profile) {
  if (!profile || typeof profile !== 'object' || Array.isArray(profile)) return null;
  const name = typeof profile.display_name === 'string'
    ? profile.display_name.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, '').trim().slice(0, 80) : '';
  const avatar = typeof profile.avatar === 'string' && profile.avatar.length <= 400000
    && /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(profile.avatar) ? profile.avatar : null;
  return {display_name: name || 'You', avatar};
}
