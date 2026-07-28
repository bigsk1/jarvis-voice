#!/usr/bin/env python3
"""
Spotify Control Tool for Jarvis
Controls Spotify playback via the Spotify Web API.

Actions:
  - play: Resume playback or play specific content
  - pause: Pause playback
  - next: Skip to next track
  - previous: Go to previous track
  - current: Get currently playing track
  - search: Search for tracks/artists/playlists
  - volume: Set volume (0-100)
  - devices: List available playback devices
  - transfer: Transfer playback to a specific device
  - shuffle: Toggle shuffle on/off
  - queue: Add track to queue

Requires: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET in config
Run ./bin/spotify-auth first to authenticate.
"""

import sys
import json
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value

import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Token cache location
CACHE_PATH = Path(__file__).parent.parent / 'data' / '.spotify_cache'

# Required scopes
SCOPES = [
    'user-read-playback-state',
    'user-modify-playback-state',
    'user-read-currently-playing',
    'playlist-read-private',
    'playlist-read-collaborative',
    'user-library-read',
    'user-read-recently-played',   # For finding recently played playlists/context
    'user-top-read',               # For recommendations based on top tracks/artists
    'user-follow-read',            # For followed playlists/artists
]

# Personalized playlist keywords (Spotify's "Made For You" playlists)
PERSONALIZED_PLAYLIST_KEYWORDS = [
    'discover weekly', 'release radar', 'daily mix',
    'on repeat', 'repeat rewind', 'your top songs',
    'time capsule', 'your summer rewind', 'your year'
]


def get_spotify_client():
    """Get authenticated Spotify client."""
    load_config()
    
    client_id = get_config_value('SPOTIFY_CLIENT_ID')
    client_secret = get_config_value('SPOTIFY_CLIENT_SECRET')
    redirect_uri = get_config_value('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')
    
    if not client_id or not client_secret:
        raise ValueError("Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET in config")
    
    if not CACHE_PATH.exists():
        raise ValueError("Not authenticated. Run ./bin/spotify-auth first")
    
    sp_oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=' '.join(SCOPES),
        cache_path=str(CACHE_PATH),
        open_browser=False
    )
    
    return spotipy.Spotify(auth_manager=sp_oauth)


def get_active_device(sp) -> tuple[str | None, str | None]:
    """
    Get active device ID with smart fallback.
    Priority: 1) Already active, 2) Configured default, 3) First available.
    Returns (device_id, device_name) or (None, None) if no devices.
    """
    try:
        result = sp.devices()
        devices = result.get('devices', [])
        
        if not devices:
            return None, None
        
        # 1. First try to find already active device
        for dev in devices:
            if dev.get('is_active'):
                return dev['id'], dev['name']
        
        # 2. Try configured default device (from env or hardcoded)
        default_device = get_config_value('SPOTIFY_DEFAULT_DEVICE', 'Office fire TV')
        for dev in devices:
            if default_device.lower() in dev['name'].lower():
                return dev['id'], dev['name']
        
        # 3. Fallback to first available
        return devices[0]['id'], devices[0]['name']
    except Exception:
        return None, None


def resolve_device_id_by_name(sp, device_name: str) -> tuple[str | None, str | None]:
    """Match a human-readable name to a Spotify Connect device (substring match, same as transfer)."""
    if not device_name or not str(device_name).strip():
        return None, None
    needle = device_name.lower().strip()
    try:
        result = sp.devices()
        for dev in result.get('devices', []):
            name = (dev.get('name') or '').lower()
            if needle in name:
                return dev.get('id'), dev.get('name')
    except Exception:
        return None, None
    return None, None


def _is_personalized_spotify_playlist(playlist: dict) -> bool:
    """Check if playlist is a Spotify-generated personalized playlist (Discover Weekly, Daily Mix, etc.).
    
    Note: Spotify's personalized playlists can have either:
    - owner_id == 'spotify' (some playlists)
    - A user-specific dynamic owner ID (Discover Weekly, Daily Mix, etc.)
    
    So we also check by name pattern if the name strongly matches personalized keywords.
    """
    if not playlist:
        return False
    owner = playlist.get('owner', {})
    name = playlist.get('name', '').lower()
    owner_id = owner.get('id') or ''
    
    # Check if owner is 'spotify'
    if owner_id == 'spotify' and any(keyword in name for keyword in PERSONALIZED_PLAYLIST_KEYWORDS):
        return True
    
    # Also check by name alone for known personalized playlist patterns
    # These have dynamic per-user owner IDs
    exact_personalized_names = [
        'discover weekly', 'release radar', 'on repeat', 'repeat rewind',
        'your top songs', 'time capsule'
    ]
    if any(name == exact_name or name.startswith(exact_name) for exact_name in exact_personalized_names):
        return True
    
    # Daily Mix 1-6 pattern
    if name.startswith('daily mix'):
        return True
    
    return False


def _get_personalized_playlists(sp) -> list:
    """Get all personalized Spotify playlists (Discover Weekly, Daily Mix 1-6, Release Radar, etc.)."""
    all_playlists = []
    offset = 0
    
    # Paginate through all user playlists (includes followed personalized ones)
    while True:
        try:
            res = sp.current_user_playlists(limit=50, offset=offset)
            items = [p for p in res.get('items', []) if p]
            all_playlists.extend(items)
            if not res.get('next'):
                break
            offset += 50
            if offset > 500:  # Safety limit
                break
        except Exception:
            break
    
    # Filter to only Spotify's personalized playlists
    personalized = [p for p in all_playlists if _is_personalized_spotify_playlist(p)]
    return personalized


def _find_personalized_playlist(sp, query: str) -> dict | None:
    """Find a personalized playlist matching the query.
    
    First checks user's library, then falls back to search API for playlists
    that the user hasn't followed yet (like Discover Weekly).
    """
    import re
    query_lower = query.lower()
    
    # Remove common prefixes
    for prefix in ['play', 'my', 'the']:
        query_lower = query_lower.replace(prefix, '').strip()
    
    # First: Check user's library for followed personalized playlists
    personalized = _get_personalized_playlists(sp)
    
    # Try exact match first
    for p in personalized:
        if query_lower == p['name'].lower():
            return p
    
    # Try contains match
    for p in personalized:
        if query_lower in p['name'].lower() or p['name'].lower() in query_lower:
            return p
    
    # Try keyword match (e.g., "daily mix 2" should match "Daily Mix 2")
    for p in personalized:
        p_name = p['name'].lower()
        if 'daily mix' in query_lower and 'daily mix' in p_name:
            query_num = re.search(r'(\d+)', query_lower)
            p_num = re.search(r'(\d+)', p_name)
            if query_num and p_num:
                if query_num.group(1) == p_num.group(1):
                    return p
            elif not query_num:
                return p
    
    # Second: Search API fallback for playlists not yet followed
    # This finds Discover Weekly, Release Radar, etc. even if user hasn't followed them
    search_terms = {
        'discover weekly': 'Discover Weekly',
        'release radar': 'Release Radar',
        'daily mix': 'Daily Mix',
        'on repeat': 'On Repeat',
        'repeat rewind': 'Repeat Rewind',
    }
    
    for keyword, search_term in search_terms.items():
        if keyword in query_lower:
            try:
                results = sp.search(q=search_term, type='playlist', limit=10)
                playlists = [p for p in results.get('playlists', {}).get('items', []) if p]
                
                for p in playlists:
                    p_name = p['name'].lower()
                    # For "daily mix X", match the number
                    if 'daily mix' in query_lower:
                        query_num = re.search(r'(\d+)', query_lower)
                        p_num = re.search(r'(\d+)', p_name)
                        if query_num and p_num and query_num.group(1) == p_num.group(1):
                            return p
                        elif not query_num and 'daily mix' in p_name:
                            return p  # Return first daily mix
                    elif keyword in p_name:
                        return p
            except Exception:
                pass
    
    return None


def _has_episode_number(query: str) -> bool:
    """Check if query contains an episode number pattern like '#2425' or 'episode 2425'."""
    import re
    # Match patterns like "#2425", "episode 2425", "ep 2425", "#2425"
    patterns = [
        r'#\d{1,5}',           # #2425
        r'episode\s*\d{1,5}',  # episode 2425
        r'ep\s*\d{1,5}',       # ep 2425
        r'number\s*\d{1,5}',   # number 2425
    ]
    for pattern in patterns:
        if re.search(pattern, query.lower()):
            return True
    return False


def _parse_episode_request(query: str) -> tuple[str, str]:
    """
    Parse query like "Joe Rogan #2425" into (show_name, episode_number).
    Returns (show_name, episode_num) or (None, None) if not parseable.
    """
    import re
    
    query_lower = query.lower()
    
    # Find episode number
    episode_num = None
    for pattern in [r'#(\d{1,5})', r'episode\s*(\d{1,5})', r'ep\s*(\d{1,5})', r'number\s*(\d{1,5})']:
        match = re.search(pattern, query_lower)
        if match:
            episode_num = match.group(1)
            break
    
    if not episode_num:
        return None, None
    
    # Remove episode number and common words to get show name
    show_name = query_lower
    show_name = re.sub(r'#\d{1,5}', '', show_name)
    show_name = re.sub(r'episode\s*\d{1,5}', '', show_name)
    show_name = re.sub(r'ep\s*\d{1,5}', '', show_name)
    show_name = re.sub(r'number\s*\d{1,5}', '', show_name)
    
    for word in ['play', 'the', 'podcast', 'from', 'of']:
        show_name = show_name.replace(word, '')
    
    show_name = show_name.strip()
    # Titles like "#2483 - Spencer Pratt" leave a leading dash or hyphen
    show_name = re.sub(r'^[\s\-–—]+', '', show_name)
    show_name = re.sub(r'[\s\-–—]+$', '', show_name).strip()
    
    return show_name if show_name else None, episode_num


def _try_play_episode_via_global_episode_search(
    sp, query: str, episode_num: str, device_id: str, guest_hint: str | None
) -> dict | None:
    """Resolve episode via Spotify episode search.

    Queries like "#2483 - Guest Name" do not include the podcast title. A show-only
    search for the guest name can return the wrong podcast (e.g. another show with
    "Spencer" in the name). Episode search matches the full episode title instead.
    """
    queries: list[str] = []
    q = (query or "").strip()
    if q:
        queries.append(q)
    if guest_hint:
        gh = guest_hint.strip()
        if gh and gh not in q.lower():
            queries.append(f"{gh} #{episode_num}")
    seen: set[str] = set()
    guest_words = [w for w in (guest_hint or "").lower().split() if len(w) > 2]

    for search_q in queries:
        if not search_q or search_q in seen:
            continue
        seen.add(search_q)
        try:
            res = sp.search(q=search_q, type='episode', limit=50)
        except Exception:
            continue
        items = [e for e in res.get('episodes', {}).get('items', []) if e]
        for ep in items:
            name = (ep.get('name') or '')
            if f"#{episode_num}" not in name and f"#{episode_num} " not in name and f"#{episode_num}:" not in name:
                continue
            if guest_words and not any(w in name.lower() for w in guest_words):
                continue
            try:
                sp.start_playback(uris=[ep['uri']], device_id=device_id)
            except Exception:
                continue
            show = ep.get('show') or {}
            show_nm = show.get('name', 'Podcast')
            return {
                "ok": True,
                "speech": f"Playing {name}",
                "data": {"uri": ep['uri'], "name": name, "show": show_nm, "type": "episode"},
            }
    return None


def _check_memory_for_playlist(query: str) -> str | None:
    """
    Check Jarvis memory for saved playlist URIs.
    Only triggers for explicit personal requests (e.g., "my rock playlist", "saved christmas music").
    
    This prevents generic queries like "christmas music" from accidentally matching
    unrelated playlists in memory that happen to contain "music".
    """
    try:
        from memory_db import MemoryDB
        
        query_lower = query.lower()
        
        # Only check memory for EXPLICIT personal playlist requests
        # Must contain "my", "saved", or be very specific
        personal_indicators = ['my ', 'my-', 'saved ', 'saved-', 'favorite ', 'favourite ']
        is_personal_request = any(ind in query_lower for ind in personal_indicators)
        
        if not is_personal_request:
            return None  # Skip memory for generic queries like "christmas music"
        
        db = MemoryDB()
        
        # Clean query - remove common words
        clean_query = query_lower
        for word in ['my', 'play', 'the', 'playlist', 'saved', 'on spotify', 'favorite', 'favourite']:
            clean_query = clean_query.replace(word, '')
        clean_query = clean_query.strip()
        
        if not clean_query or len(clean_query) < 3:
            return None
        
        # Search memory for playlist URIs
        memories = db.search_memory(clean_query, limit=5)
        
        # Extract meaningful search words (longer than 3 chars, not generic)
        generic_words = {'music', 'songs', 'playlist', 'album', 'track', 'spotify'}
        search_words = [w for w in clean_query.split() if len(w) > 3 and w not in generic_words]
        
        if not search_words:
            # If only generic words remain, require exact match
            search_words = [clean_query]
        
        for mem in memories:
            value = mem.get('value', '')
            key = mem.get('key', '').lower()
            
            # Check if this is a Spotify playlist URI
            if 'spotify:playlist:' in value:
                # Require at least one meaningful word to match in the key
                # This prevents "my music" from matching "rock_playlist" just because both exist
                if any(word in key for word in search_words):
                    return value
            
            # Also check if value IS a URI (not just contains one)
            if value.startswith('spotify:playlist:'):
                if any(word in key for word in search_words):
                    return value
        
        return None
    except Exception:
        return None


def _search_user_playlists(sp, query: str) -> dict | None:
    """
    Search user's saved playlists (library) with fuzzy matching.
    Returns the best matching playlist or None if no match.
    """
    import re
    query_lower = query.lower().strip()
    # Extract words, ignoring emojis and special chars
    query_words = set(re.findall(r'[a-z0-9]+', query_lower))
    
    try:
        # Get all user playlists (paginate)
        all_playlists = []
        offset = 0
        while True:
            result = sp.current_user_playlists(limit=50, offset=offset)
            items = [i for i in result.get('items', []) if i]
            if not items:
                break
            all_playlists.extend(items)
            offset += 50
            if offset >= result.get('total', 0):
                break
        
        if not all_playlists:
            return None
        
        # Score each playlist by how well it matches the query
        best_match = None
        best_score = 0
        
        for playlist in all_playlists:
            name = playlist.get('name', '').lower()
            # Extract words, ignoring emojis
            name_words = set(re.findall(r'[a-z0-9]+', name))
            
            # Exact match (case-insensitive, ignoring emojis)
            name_clean = re.sub(r'[^\w\s]', '', name).strip()
            if query_lower == name_clean:
                return playlist
            
            # Check if query is substring of name (high confidence)
            if query_lower in name:
                score = 90  # High score for substring match
                if score > best_score:
                    best_score = score
                    best_match = playlist
                continue
            
            # Check if ALL query words appear in name
            if query_words and query_words.issubset(name_words):
                score = 85  # All words present
                if score > best_score:
                    best_score = score
                    best_match = playlist
                continue
            
            # Word overlap scoring - any match counts
            overlap = len(query_words & name_words)
            if overlap > 0:
                # Score based on how many query words matched
                score = (overlap / len(query_words)) * 70 if query_words else 0
                if score > best_score:
                    best_score = score
                    best_match = playlist
        
        # Return if we have a reasonable match (> 40% confidence)
        if best_match and best_score > 40:
            return best_match
        
        return None
    except Exception:
        return None


def action_play(args: dict) -> dict:
    """Resume playback or play specific content."""
    sp = get_spotify_client()
    
    query = args.get('query', '')
    device_id = args.get('device_id')
    search_type = args.get('type', '').lower()  # Explicit type hint from LLM
    
    # Resolve device name (LLM passes `device`, e.g. "Office Fire TV") — not only `device_id`.
    # Without this, get_active_device() prefers whichever device is *already* active (often a phone),
    # so playback succeeds on the wrong device while the TV never starts.
    device_name_hint = (args.get('device') or '').strip() or None
    if not device_id and device_name_hint:
        device_id, resolved_name = resolve_device_id_by_name(sp, device_name_hint)
        if not device_id:
            return {
                "ok": False,
                "speech": (
                    f"Couldn't find a Spotify device matching \"{device_name_hint}\". "
                    "Open the Spotify app on that device so it appears in Connect, then try again."
                ),
                "error": "DEVICE_NOT_FOUND",
            }
    
    # Auto-detect device if not specified
    if not device_id:
        device_id, device_name = get_active_device(sp)
        if not device_id:
            return {
                "ok": False,
                "speech": "No Spotify devices found. Open Spotify on your phone, computer, or web browser first, then try again.",
                "error": "NO_ACTIVE_DEVICE"
            }
    
    if query:
        # Search and play
        query_lower = query.lower()
        
        # Check memory for saved playlist URIs FIRST (before any search)
        # This allows users to save personalized playlists that can't be found via search
        saved_uri = _check_memory_for_playlist(query_lower)
        if saved_uri:
            try:
                sp.start_playback(context_uri=saved_uri, device_id=device_id)
                # Extract name from query for speech
                name = query_lower.replace('my ', '').replace('saved ', '').replace('playlist', '').strip()
                return {
                    "ok": True,
                    "speech": f"Playing your {name} from saved playlists",
                    "data": {"uri": saved_uri, "type": "playlist", "source": "memory"}
                }
            except Exception:
                pass  # Fall through to other search methods
        
        # Check for Spotify's personalized playlists (Discover Weekly, Daily Mix, Release Radar, etc.)
        # These are owned by "spotify" and have dynamic per-user IDs - can't be found via normal search
        if any(kw in query_lower for kw in PERSONALIZED_PLAYLIST_KEYWORDS):
            personalized = _find_personalized_playlist(sp, query_lower)
            if personalized:
                try:
                    sp.start_playback(context_uri=personalized['uri'], device_id=device_id)
                    return {
                        "ok": True,
                        "speech": f"Playing {personalized['name']}",
                        "data": {"uri": personalized['uri'], "name": personalized['name'], "type": "personalized_playlist"}
                    }
                except Exception:
                    pass  # Fall through to other search methods
        
        # Handle direct Spotify URIs (e.g., spotify:track:xxx, spotify:episode:xxx)
        if query.startswith('spotify:'):
            uri_type = query.split(':')[1] if ':' in query else 'unknown'
            try:
                if uri_type in ['track', 'episode']:
                    # Single item - use uris parameter
                    sp.start_playback(uris=[query], device_id=device_id)
                else:
                    # Context (album, playlist, artist, show) - use context_uri
                    sp.start_playback(context_uri=query, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing {uri_type}",
                    "data": {"uri": query, "type": uri_type}
                }
            except Exception as e:
                return {
                    "ok": False,
                    "speech": f"Failed to play: {e}",
                    "error": str(e)
                }
        
        # Determine search type based on explicit type hint OR keywords
        
        # If LLM passed explicit type='playlist', use that
        if search_type == 'playlist':
            # FIRST: Search user's saved playlists (library)
            user_playlist = _search_user_playlists(sp, query)
            if user_playlist:
                uri = user_playlist['uri']
                name = user_playlist['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing your playlist {name}",
                    "data": {"uri": uri, "name": name, "type": "playlist", "source": "library"}
                }
            
            # SECOND: Fall back to public Spotify search
            results = sp.search(q=query, type='playlist', limit=5)
            items = [i for i in results.get('playlists', {}).get('items', []) if i]
            if items:
                uri = items[0]['uri']
                name = items[0]['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing playlist {name}",
                    "data": {"uri": uri, "name": name, "type": "playlist", "source": "public"}
                }
            else:
                return {
                    "ok": False,
                    "speech": f"No playlist found for '{query}'",
                    "error": "NOT_FOUND"
                }
        
        # If LLM passed explicit type='album', use that
        if search_type == 'album':
            results = sp.search(q=query, type='album', limit=5)  # Get more in case some are None
            items = [i for i in results.get('albums', {}).get('items', []) if i]  # Filter None
            if items:
                uri = items[0]['uri']
                name = items[0]['name']
                artist = items[0]['artists'][0]['name'] if items[0].get('artists') else 'Unknown'
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing album {name} by {artist}",
                    "data": {"uri": uri, "name": name, "artist": artist, "type": "album"}
                }
            else:
                return {
                    "ok": False,
                    "speech": f"No album found for '{query}'",
                    "error": "NOT_FOUND"
                }
        
        # If LLM passed explicit type='artist', use that
        if search_type == 'artist':
            results = sp.search(q=query, type='artist', limit=5)  # Get more in case some are None
            items = [i for i in results.get('artists', {}).get('items', []) if i]  # Filter None
            if items:
                uri = items[0]['uri']
                name = items[0]['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing {name}",
                    "data": {"uri": uri, "name": name, "type": "artist"}
                }
            else:
                return {
                    "ok": False,
                    "speech": f"No artist found for '{query}'",
                    "error": "NOT_FOUND"
                }
        
        # Special case: Liked Songs (user's saved tracks)
        if 'liked' in query_lower or 'saved' in query_lower or 'favorites' in query_lower:
            # Get user's saved/liked tracks
            saved = sp.current_user_saved_tracks(limit=50)
            items = saved.get('items', [])
            if items:
                # Extract track URIs
                uris = [item['track']['uri'] for item in items if item.get('track')]
                if uris:
                    sp.start_playback(uris=uris, device_id=device_id)
                    return {
                        "ok": True,
                        "speech": f"Playing your liked songs ({len(uris)} tracks)",
                        "data": {"type": "liked_songs", "count": len(uris)}
                    }
            return {
                "ok": False,
                "speech": "No liked songs found",
                "error": "Empty library"
            }
        
        if 'playlist' in query_lower:
            search_query = query_lower.replace('playlist', '').strip()
            
            # FIRST: Search user's library
            user_playlist = _search_user_playlists(sp, search_query)
            if user_playlist:
                uri = user_playlist['uri']
                name = user_playlist['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing your playlist {name}",
                    "data": {"uri": uri, "name": name, "type": "playlist", "source": "library"}
                }
            
            # SECOND: Public search
            results = sp.search(q=search_query, type='playlist', limit=5)
            items = [i for i in results.get('playlists', {}).get('items', []) if i]
            if items:
                uri = items[0]['uri']
                name = items[0]['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing playlist {name}",
                    "data": {"uri": uri, "name": name, "type": "playlist", "source": "public"}
                }
        elif 'album' in query_lower:
            search_query = query_lower.replace('album', '').strip()
            results = sp.search(q=search_query, type='album', limit=5)
            items = [i for i in results.get('albums', {}).get('items', []) if i]
            if items:
                uri = items[0]['uri']
                name = items[0]['name']
                artists = items[0].get('artists', [])
                artist = artists[0]['name'] if artists else 'Unknown'
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing album {name} by {artist}",
                    "data": {"uri": uri, "name": name, "artist": artist, "type": "album"}
                }
        # Check for specific episode number pattern (e.g., "Joe Rogan #2425", "episode 2425")
        elif _has_episode_number(query_lower):
            show_name, episode_num = _parse_episode_request(query_lower)
            if episode_num:
                # 1) Global episode search (JRE titles are often "#NNNN - Guest" without podcast name)
                global_ep = _try_play_episode_via_global_episode_search(
                    sp, query, episode_num, device_id, guest_hint=show_name
                )
                if global_ep:
                    return global_ep

                # 2) Show-based lookup when the query includes a podcast name
                if show_name:
                    results = sp.search(q=show_name, type='show', limit=5)
                    shows = [s for s in results.get('shows', {}).get('items', []) if s]
                    # Do not use shows[0] unless substring match (avoids wrong podcast)
                    show = next((s for s in shows if show_name.lower() in s['name'].lower()), None)
                    if show:
                        episodes = sp.show_episodes(show['id'], limit=50)
                        episode_items = [e for e in episodes.get('items', []) if e]
                        target_ep = None
                        for ep in episode_items:
                            ep_name = ep.get('name', '')
                            if f"#{episode_num}" in ep_name or f"#{episode_num} " in ep_name or f"#{episode_num}:" in ep_name:
                                target_ep = ep
                                break
                            if f" {episode_num} " in ep_name or ep_name.startswith(f"{episode_num} ") or f"#{episode_num}" in ep_name:
                                target_ep = ep
                                break
                        if target_ep:
                            sp.start_playback(uris=[target_ep['uri']], device_id=device_id)
                            return {
                                "ok": True,
                                "speech": f"Playing {target_ep['name']}",
                                "data": {"uri": target_ep['uri'], "name": target_ep['name'], "show": show['name'], "type": "episode"}
                            }
                        fallback = _try_play_episode_via_global_episode_search(
                            sp, query, episode_num, device_id, guest_hint=None
                        )
                        if fallback:
                            return fallback
                        return {"ok": False, "speech": f"Couldn't find episode {episode_num} of {show['name']}", "error": "Episode not found"}
                    # No confident show match — unfiltered episode search already tried above; fail clearly
                    last = _try_play_episode_via_global_episode_search(
                        sp, query, episode_num, device_id, guest_hint=None
                    )
                    if last:
                        return last
                    return {"ok": False, "speech": f"Couldn't find episode {episode_num} on Spotify.", "error": "Episode not found"}
                return {"ok": False, "speech": f"Couldn't find episode {episode_num} on Spotify.", "error": "Episode not found"}

        elif 'podcast' in query_lower or 'latest episode' in query_lower or 'latest from' in query_lower or 'newest episode' in query_lower:
            # Search for podcast/show and play LATEST episode
            # Remove keywords to get the podcast name
            search_query = query_lower
            for keyword in ['podcast', 'latest episode of', 'latest episode from', 'latest from', 'newest episode of', 'newest episode from', 'play the', 'play']:
                search_query = search_query.replace(keyword, '')
            search_query = search_query.strip()
            
            if not search_query:
                return {"ok": False, "speech": "Which podcast?", "error": "No podcast name"}
            
            results = sp.search(q=search_query, type='show', limit=5)
            items = [i for i in results.get('shows', {}).get('items', []) if i]
            if items:
                show = items[0]
                show_id = show['id']
                show_name = show['name']
                publisher = show.get('publisher', 'Unknown')
                
                # Get latest episodes (returns newest first by default)
                episodes = sp.show_episodes(show_id, limit=5)
                episode_items = [i for i in episodes.get('items', []) if i]
                
                if episode_items:
                    latest_ep = episode_items[0]
                    ep_uri = latest_ep['uri']
                    ep_name = latest_ep['name']
                    
                    # Play the specific latest episode
                    sp.start_playback(uris=[ep_uri], device_id=device_id)
                    return {
                        "ok": True,
                        "speech": f"Playing latest episode of {show_name}: {ep_name}",
                        "data": {
                            "uri": ep_uri, 
                            "name": ep_name, 
                            "show": show_name,
                            "publisher": publisher, 
                            "type": "episode"
                        }
                    }
                else:
                    # Fallback: play the show (starts from beginning)
                    sp.start_playback(context_uri=show['uri'], device_id=device_id)
                    return {
                        "ok": True,
                        "speech": f"Playing podcast {show_name}",
                        "data": {"uri": show['uri'], "name": show_name, "publisher": publisher, "type": "show"}
                    }
        else:
            # Detect genre/mood queries - prefer playlists for these
            genre_mood_keywords = ['songs', 'music', 'hits', 'pop', 'rock', 'jazz', 'classical', 
                                   'hip hop', 'rap', 'country', 'r&b', 'indie', 'electronic', 
                                   'upbeat', 'chill', 'relaxing', 'workout', 'party', 'focus',
                                   '80s', '90s', '2000s', '2010s', '70s', '60s',
                                   # Seasonal/holiday keywords
                                   'christmas', 'holiday', 'xmas', 'halloween', 'thanksgiving',
                                   'summer', 'winter', 'spring', 'fall', 'autumn',
                                   'new year', 'valentines', 'love songs']
            is_genre_query = any(kw in query_lower for kw in genre_mood_keywords)
            
            # For genre/mood queries, search playlists FIRST
            if is_genre_query:
                results = sp.search(q=query, type='playlist', limit=5)
                playlists = [i for i in results.get('playlists', {}).get('items', []) if i]
                if playlists:
                    uri = playlists[0]['uri']
                    name = playlists[0]['name']
                    sp.start_playback(context_uri=uri, device_id=device_id)
                    sp.shuffle(True, device_id=device_id)  # Shuffle for variety
                    return {
                        "ok": True,
                        "speech": f"Playing {name} on shuffle",
                        "data": {"uri": uri, "name": name, "type": "playlist", "shuffle": True}
                    }
            
            # Try artist if query looks like an artist name (no genre keywords)
            results = sp.search(q=query, type='artist', limit=5)
            artists = [i for i in results.get('artists', {}).get('items', []) if i]
            if artists and query_lower in artists[0]['name'].lower():
                uri = artists[0]['uri']
                name = artists[0]['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing {name}",
                    "data": {"uri": uri, "name": name, "type": "artist"}
                }
            
            # Try track as last resort
            results = sp.search(q=query, type='track', limit=5)
            tracks = [i for i in results.get('tracks', {}).get('items', []) if i]
            if tracks:
                uri = tracks[0]['uri']
                name = tracks[0]['name']
                track_artists = tracks[0].get('artists', [])
                artist = track_artists[0]['name'] if track_artists else 'Unknown'
                sp.start_playback(uris=[uri], device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing {name} by {artist}",
                    "data": {"uri": uri, "name": name, "artist": artist, "type": "track"}
                }
        
        return {
            "ok": False,
            "speech": f"Couldn't find anything for {query}",
            "error": "No results found"
        }
    else:
        # Just resume playback
        sp.start_playback(device_id=device_id)
        return {
            "ok": True,
            "speech": "Resuming playback",
            "data": {"action": "resume"}
        }


def action_pause(args: dict) -> dict:
    """Pause playback."""
    sp = get_spotify_client()
    sp.pause_playback()
    return {
        "ok": True,
        "speech": "Paused",
        "data": {"action": "pause"}
    }


def action_next(args: dict) -> dict:
    """Skip to next track."""
    sp = get_spotify_client()
    sp.next_track()
    
    # Get new track info after a moment
    import time
    time.sleep(0.5)
    current = sp.current_playback()
    
    if current and current.get('item'):
        track = current['item']
        name = track['name']
        artist = track['artists'][0]['name']
        return {
            "ok": True,
            "speech": f"Now playing {name} by {artist}",
            "data": {"name": name, "artist": artist}
        }
    
    return {
        "ok": True,
        "speech": "Skipped to next track",
        "data": {"action": "next"}
    }


def action_previous(args: dict) -> dict:
    """Go to previous track."""
    sp = get_spotify_client()
    sp.previous_track()
    return {
        "ok": True,
        "speech": "Previous track",
        "data": {"action": "previous"}
    }


def action_current(args: dict) -> dict:
    """Get currently playing track."""
    sp = get_spotify_client()
    current = sp.current_playback()
    
    if not current or not current.get('item'):
        return {
            "ok": True,
            "speech": "Nothing is playing right now",
            "data": {"playing": False}
        }
    
    track = current['item']
    name = track['name']
    artist = track['artists'][0]['name']
    album = track['album']['name']
    is_playing = current.get('is_playing', False)
    progress_ms = current.get('progress_ms', 0)
    duration_ms = track.get('duration_ms', 0)
    
    # Format time
    progress = f"{progress_ms // 60000}:{(progress_ms // 1000) % 60:02d}"
    duration = f"{duration_ms // 60000}:{(duration_ms // 1000) % 60:02d}"
    
    status = "Playing" if is_playing else "Paused"
    device = current.get('device', {}).get('name', 'Unknown')
    
    return {
        "ok": True,
        "speech": f"{status}: {name} by {artist}",
        "data": {
            "playing": is_playing,
            "name": name,
            "artist": artist,
            "album": album,
            "progress": progress,
            "duration": duration,
            "device": device
        }
    }


def action_search(args: dict) -> dict:
    """Search for tracks, artists, albums, playlists, podcasts (shows), or episodes."""
    sp = get_spotify_client()
    
    query = args.get('query', '')
    search_type = args.get('type', 'track')  # track, artist, album, playlist, show, episode
    limit = args.get('limit', 5)
    
    if not query:
        return {"ok": False, "speech": "What should I search for?", "error": "No query"}
    
    # Map type to Spotify API type key
    type_key_map = {
        'track': 'tracks',
        'artist': 'artists', 
        'album': 'albums',
        'playlist': 'playlists',
        'show': 'shows',      # Podcasts
        'episode': 'episodes', # Podcast episodes
        'podcast': 'shows',   # Alias for show
    }
    
    # Normalize type
    if search_type == 'podcast':
        search_type = 'show'
    
    api_type = search_type
    type_key = type_key_map.get(search_type, f"{search_type}s")
    
    results = sp.search(q=query, type=api_type, limit=limit)
    
    items = []
    
    for item in results.get(type_key, {}).get('items', []):
        if not item:
            continue
            
        if search_type == 'track':
            artists = item.get('artists', [])
            items.append({
                "name": item.get('name', 'Unknown'),
                "artist": artists[0]['name'] if artists else 'Unknown',
                "uri": item.get('uri')
            })
        elif search_type == 'artist':
            items.append({
                "name": item.get('name', 'Unknown'),
                "uri": item.get('uri')
            })
        elif search_type == 'album':
            artists = item.get('artists', [])
            items.append({
                "name": item.get('name', 'Unknown'),
                "artist": artists[0]['name'] if artists else 'Unknown',
                "uri": item.get('uri')
            })
        elif search_type == 'playlist':
            owner = item.get('owner', {})
            items.append({
                "name": item.get('name', 'Unknown'),
                "owner": owner.get('display_name', 'Unknown') if owner else 'Unknown',
                "uri": item.get('uri')
            })
        elif search_type == 'show':
            # Podcasts
            items.append({
                "name": item.get('name', 'Unknown'),
                "publisher": item.get('publisher', 'Unknown'),
                "uri": item.get('uri'),
                "total_episodes": item.get('total_episodes', 0)
            })
        elif search_type == 'episode':
            # Podcast episodes
            show = item.get('show', {})
            items.append({
                "name": item.get('name', 'Unknown'),
                "show": show.get('name', 'Unknown') if show else 'Unknown',
                "uri": item.get('uri'),
                "duration_ms": item.get('duration_ms', 0),
                "release_date": item.get('release_date', '')
            })
    
    if items:
        first = items[0]
        if search_type == 'track':
            speech = f"Found {first['name']} by {first['artist']}"
        elif search_type == 'playlist':
            speech = f"Found playlist {first['name']}"
        elif search_type == 'show':
            speech = f"Found podcast {first['name']} by {first['publisher']}"
        elif search_type == 'episode':
            speech = f"Found episode {first['name']} from {first['show']}"
        else:
            speech = f"Found {first['name']}"
        
        return {
            "ok": True,
            "speech": speech,
            "data": {"results": items, "count": len(items)}
        }
    
    return {
        "ok": True,
        "speech": f"No results for {query}",
        "data": {"results": [], "count": 0}
    }


def action_volume(args: dict) -> dict:
    """Set playback volume (0-100)."""
    sp = get_spotify_client()
    
    level = args.get('level', 50)
    level = max(0, min(100, int(level)))
    
    sp.volume(level)
    
    return {
        "ok": True,
        "speech": f"Volume set to {level}%",
        "data": {"volume": level}
    }


def action_devices(args: dict) -> dict:
    """List available playback devices."""
    sp = get_spotify_client()
    
    result = sp.devices()
    devices = result.get('devices', [])
    
    if not devices:
        return {
            "ok": True,
            "speech": "No Spotify devices found. Open Spotify on a device.",
            "data": {"devices": []}
        }
    
    device_list = []
    active_device = None
    
    for dev in devices:
        device_list.append({
            "id": dev['id'],
            "name": dev['name'],
            "type": dev['type'],
            "active": dev['is_active'],
            "volume": dev.get('volume_percent', 0)
        })
        if dev['is_active']:
            active_device = dev['name']
    
    if active_device:
        speech = f"Currently playing on {active_device}. {len(devices)} devices available."
    else:
        speech = f"Found {len(devices)} devices: {', '.join(d['name'] for d in device_list)}"
    
    return {
        "ok": True,
        "speech": speech,
        "data": {"devices": device_list, "count": len(devices)}
    }


def action_transfer(args: dict) -> dict:
    """Transfer playback to a specific device."""
    sp = get_spotify_client()
    
    device_name = args.get('device', '')
    device_id = args.get('device_id', '')
    
    if not device_name and not device_id:
        return {"ok": False, "speech": "Which device?", "error": "No device specified"}
    
    # If name given, find device ID
    if device_name and not device_id:
        result = sp.devices()
        for dev in result.get('devices', []):
            if device_name.lower() in dev['name'].lower():
                device_id = dev['id']
                device_name = dev['name']
                break
    
    if not device_id:
        return {
            "ok": False,
            "speech": f"Couldn't find device {device_name}",
            "error": "Device not found"
        }
    
    sp.transfer_playback(device_id, force_play=True)
    
    return {
        "ok": True,
        "speech": f"Playing on {device_name}",
        "data": {"device_id": device_id, "device_name": device_name}
    }


def action_shuffle(args: dict) -> dict:
    """Toggle or set shuffle mode."""
    sp = get_spotify_client()
    
    state = args.get('state')  # True, False, or None (toggle)
    
    if state is None:
        # Toggle - check current state first
        current = sp.current_playback()
        if current:
            state = not current.get('shuffle_state', False)
        else:
            state = True
    
    sp.shuffle(state)
    
    status = "on" if state else "off"
    return {
        "ok": True,
        "speech": f"Shuffle {status}",
        "data": {"shuffle": state}
    }


def action_queue(args: dict) -> dict:
    """Add a track to the queue."""
    sp = get_spotify_client()
    
    query = args.get('query', '')
    uri = args.get('uri', '')
    
    if not query and not uri:
        return {"ok": False, "speech": "What should I add to the queue?", "error": "No query"}
    
    if query and not uri:
        # Search for track
        results = sp.search(q=query, type='track', limit=5)
        tracks = [i for i in results.get('tracks', {}).get('items', []) if i]
        if tracks:
            uri = tracks[0]['uri']
            name = tracks[0]['name']
            track_artists = tracks[0].get('artists', [])
            artist = track_artists[0]['name'] if track_artists else 'Unknown'
        else:
            return {
                "ok": False,
                "speech": f"Couldn't find track {query}",
                "error": "Track not found"
            }
    
    sp.add_to_queue(uri)
    
    # Fix: name/artist may not be defined if uri was passed directly
    if 'name' not in locals():
        name = "that track"
        artist = ""
    
    speech = f"Added {name} by {artist} to queue".strip()
    if speech.endswith(" by  to queue"):
        speech = "Added to queue"
    
    return {
        "ok": True,
        "speech": speech,
        "data": {"uri": uri}
    }


def action_share(args: dict) -> dict:
    """Get shareable info for current track (URL, album art, details)."""
    sp = get_spotify_client()
    current = sp.current_playback()
    
    if not current or not current.get('item'):
        return {
            "ok": False,
            "speech": "Nothing is playing to share",
            "error": "No current track"
        }
    
    track = current['item']
    name = track['name']
    artist = track['artists'][0]['name']
    all_artists = ", ".join(a['name'] for a in track['artists'])
    album = track['album']['name']
    
    # Get Spotify URL (shareable link)
    spotify_url = track.get('external_urls', {}).get('spotify', '')
    
    # Get album art (prefer medium size ~300px, fall back to largest)
    images = track.get('album', {}).get('images', [])
    album_art = None
    album_art_large = None
    if images:
        # Images are sorted by size descending (largest first)
        album_art_large = images[0]['url'] if images else None
        # Try to get medium size (~300px)
        for img in images:
            if img.get('width', 0) <= 300:
                album_art = img['url']
                break
        if not album_art:
            album_art = album_art_large
    
    # Get release year
    release_date = track.get('album', {}).get('release_date', '')
    release_year = release_date[:4] if release_date else ''
    
    # Duration
    duration_ms = track.get('duration_ms', 0)
    duration = f"{duration_ms // 60000}:{(duration_ms // 1000) % 60:02d}"
    
    return {
        "ok": True,
        "speech": f"Here's the share info for {name} by {artist}",
        "data": {
            "name": name,
            "artist": artist,
            "all_artists": all_artists,
            "album": album,
            "release_year": release_year,
            "duration": duration,
            "spotify_url": spotify_url,
            "album_art": album_art,
            "album_art_large": album_art_large,
            # Pre-formatted for email
            "share_text": f"🎵 {name} by {all_artists}\n📀 Album: {album} ({release_year})\n⏱️ Duration: {duration}\n\n🔗 Listen on Spotify: {spotify_url}",
            "share_html": f'<div style="font-family: sans-serif;"><h3>🎵 {name}</h3><p><strong>Artist:</strong> {all_artists}<br><strong>Album:</strong> {album} ({release_year})<br><strong>Duration:</strong> {duration}</p><p><a href="{spotify_url}">Listen on Spotify</a></p><img src="{album_art}" alt="Album art" style="max-width: 300px; border-radius: 8px;"></div>'
        }
    }


# Action dispatcher
def action_recent(args: dict) -> dict:
    """Get recently played playlists/contexts. Uses user-read-recently-played scope."""
    sp = get_spotify_client()
    
    limit = args.get('limit', 10)
    play_first = args.get('play', False)
    
    recent = sp.current_user_recently_played(limit=50)
    
    # Extract unique playlist contexts
    seen_uris = set()
    playlists = []
    
    for item in recent.get('items', []):
        context = item.get('context')
        if context and context.get('type') == 'playlist':
            uri = context.get('uri', '')
            if uri and uri not in seen_uris:
                seen_uris.add(uri)
                playlists.append({
                    'uri': uri,
                    'type': 'playlist'
                })
                if len(playlists) >= limit:
                    break
    
    if play_first and playlists:
        # Play the most recently played playlist
        uri = playlists[0]['uri']
        device_id, _ = get_active_device(sp)
        sp.start_playback(context_uri=uri, device_id=device_id)
        return {
            "ok": True,
            "speech": "Resuming your most recent playlist",
            "data": {"uri": uri, "action": "play"}
        }
    
    return {
        "ok": True,
        "speech": f"Found {len(playlists)} recently played playlists",
        "data": {"playlists": playlists, "count": len(playlists)}
    }


def action_recommend(args: dict) -> dict:
    """Get personalized recommendations based on listening history. Uses user-top-read scope."""
    sp = get_spotify_client()
    
    limit = args.get('limit', 20)
    play = args.get('play', True)
    mood = args.get('mood', '')  # Optional: energetic, chill, etc.
    
    # Get seed tracks from user's top tracks
    top = sp.current_user_top_tracks(limit=5, time_range='short_term')
    seed_tracks = [t['id'] for t in top.get('items', []) if t][:5]
    
    if not seed_tracks:
        # Fallback to liked songs
        liked = sp.current_user_saved_tracks(limit=5)
        seed_tracks = [item['track']['id'] for item in liked.get('items', []) if item.get('track')][:5]
    
    if not seed_tracks:
        return {"ok": False, "speech": "Need some listening history for recommendations", "error": "No seeds"}
    
    # Try recommendations API, fall back to top tracks if it fails
    try:
        # Optional: adjust for mood
        kwargs = {'seed_tracks': seed_tracks, 'limit': limit}
        if mood:
            mood_lower = mood.lower()
            if 'energy' in mood_lower or 'upbeat' in mood_lower or 'workout' in mood_lower:
                kwargs['target_energy'] = 0.8
                kwargs['target_valence'] = 0.7
            elif 'chill' in mood_lower or 'relax' in mood_lower or 'calm' in mood_lower:
                kwargs['target_energy'] = 0.3
                kwargs['target_valence'] = 0.5
            elif 'focus' in mood_lower or 'work' in mood_lower:
                kwargs['target_energy'] = 0.5
                kwargs['target_instrumentalness'] = 0.7
        
        recs = sp.recommendations(**kwargs)
        tracks = recs.get('tracks', [])
    except Exception:
        # Recommendations API failed - use top tracks as fallback
        top_extended = sp.current_user_top_tracks(limit=limit, time_range='medium_term')
        tracks = top_extended.get('items', [])
    
    if not tracks:
        return {"ok": False, "speech": "Couldn't generate recommendations", "error": "Empty recs"}
    
    if play:
        device_id, _ = get_active_device(sp)
        uris = [t['uri'] for t in tracks]
        sp.start_playback(uris=uris, device_id=device_id)
        sp.shuffle(True, device_id=device_id)
        
        artists = list(set([t['artists'][0]['name'] for t in tracks[:5] if t.get('artists')]))
        artist_sample = ', '.join(artists[:3])
        
        return {
            "ok": True,
            "speech": f"Playing {len(tracks)} recommended tracks based on your taste. Artists like {artist_sample}",
            "data": {"count": len(tracks), "artists": artists}
        }
    
    return {
        "ok": True,
        "speech": f"Generated {len(tracks)} recommendations",
        "data": {"tracks": [{"name": t['name'], "artist": t['artists'][0]['name'], "uri": t['uri']} for t in tracks[:10]]}
    }


def action_top(args: dict) -> dict:
    """Get user's top tracks or artists. Uses user-top-read scope."""
    sp = get_spotify_client()
    
    item_type = args.get('type', 'tracks')  # tracks or artists
    time_range = args.get('time_range', 'medium_term')  # short_term, medium_term, long_term
    limit = args.get('limit', 10)
    
    if item_type == 'artists':
        result = sp.current_user_top_artists(limit=limit, time_range=time_range)
        items = [{'name': a['name'], 'uri': a['uri']} for a in result.get('items', []) if a]
        speech = f"Your top artists: {', '.join([i['name'] for i in items[:5]])}"
    else:
        result = sp.current_user_top_tracks(limit=limit, time_range=time_range)
        items = [{'name': t['name'], 'artist': t['artists'][0]['name'], 'uri': t['uri']} 
                 for t in result.get('items', []) if t and t.get('artists')]
        speech = f"Your top tracks include {items[0]['name']} by {items[0]['artist']}" if items else "No top tracks found"
    
    return {
        "ok": True,
        "speech": speech,
        "data": {"items": items, "type": item_type, "time_range": time_range}
    }


def _compact_followed_artist(artist: dict) -> dict:
    """Keep stable identifiers and useful browsing metadata for one artist."""
    return {
        "id": artist.get("id"),
        "name": artist.get("name"),
        "uri": artist.get("uri"),
        "spotify_url": (artist.get("external_urls") or {}).get("spotify"),
        "genres": (artist.get("genres") or [])[:5],
        "followers": (artist.get("followers") or {}).get("total", 0),
        "popularity": artist.get("popularity", 0),
    }


def action_followed(args: dict) -> dict:
    """List followed artists, optionally filtering across cursor pages."""
    sp = get_spotify_client()

    try:
        limit = max(1, min(50, int(args.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20

    query = str(args.get("query") or "").strip()
    query_folded = query.casefold()
    matches = []
    after = None
    seen_cursors = set()
    total_followed = 0
    has_more = False

    while True:
        page_limit = 50 if query else limit
        response = sp.current_user_followed_artists(limit=page_limit, after=after)
        page = response.get("artists") or {}
        total_followed = int(page.get("total") or total_followed)

        for artist in page.get("items") or []:
            name = str(artist.get("name") or "")
            if query_folded and query_folded not in name.casefold():
                continue
            matches.append(_compact_followed_artist(artist))
            if len(matches) >= limit:
                break

        next_cursor = (page.get("cursors") or {}).get("after") if page.get("next") else None
        if len(matches) >= limit:
            has_more = bool(next_cursor)
            break
        if not query or not next_cursor or next_cursor in seen_cursors:
            break

        seen_cursors.add(next_cursor)
        after = next_cursor

    data = {
        "artists": matches,
        "count": len(matches),
        "total_followed": total_followed,
        "query": query,
        "has_more": has_more,
    }
    if not matches:
        if query:
            return {
                "ok": True,
                "speech": f"No followed artists matched '{query}'.",
                "data": data,
            }
        return {
            "ok": True,
            "speech": "You are not following any artists on Spotify.",
            "data": data,
        }

    names = ", ".join(artist["name"] for artist in matches[:5] if artist.get("name"))
    if query:
        count_label = "artist" if len(matches) == 1 else "artists"
        speech = f"Found {len(matches)} followed {count_label} matching '{query}': {names}."
    else:
        speech = f"Your followed artists include {names}."
    return {"ok": True, "speech": speech, "data": data}


def action_episodes(args: dict) -> dict:
    """List recent episodes of a podcast/show. Great for browsing before playing."""
    sp = get_spotify_client()
    
    query = args.get('query', '')
    limit = args.get('limit', 5)
    
    if not query:
        return {"ok": False, "speech": "Which podcast?", "error": "No query"}
    
    # Search for the show
    results = sp.search(q=query, type='show', limit=5)
    shows = [s for s in results.get('shows', {}).get('items', []) if s]
    
    if not shows:
        return {"ok": False, "speech": f"Couldn't find podcast '{query}'", "error": "Not found"}
    
    # Find best match (prefer exact name match)
    query_lower = query.lower()
    show = next((s for s in shows if query_lower in s['name'].lower()), shows[0])
    
    # Get episodes
    episodes = sp.show_episodes(show['id'], limit=limit)
    episode_list = []
    
    for i, ep in enumerate(episodes.get('items', []), 1):
        if ep:
            episode_list.append({
                "number": i,
                "name": ep.get('name', 'Unknown'),
                "date": ep.get('release_date', '?'),
                "duration_min": round(ep.get('duration_ms', 0) / 60000),
                "uri": ep.get('uri', ''),
                "description": ep.get('description', '')[:100] + '...' if ep.get('description') else ''
            })
    
    # Build speech output
    speech_parts = [f"Recent episodes of {show['name']}:"]
    for ep in episode_list[:3]:
        speech_parts.append(f"{ep['number']}. {ep['name'][:40]}")
    
    return {
        "ok": True,
        "speech": ' '.join(speech_parts),
        "data": {
            "show": show['name'],
            "show_uri": show['uri'],
            "episodes": episode_list
        }
    }


def action_suggest(args: dict) -> dict:
    """Get music suggestions for browsing (doesn't auto-play). For conversational discovery."""
    sp = get_spotify_client()
    
    mood = args.get('mood', '')
    genre = args.get('genre', '')
    limit = args.get('limit', 5)
    
    suggestions = []
    
    # If mood/genre specified, search for playlists
    if mood or genre:
        search_term = f"{mood} {genre}".strip() or "good vibes"
        results = sp.search(q=search_term, type='playlist', limit=limit)
        playlists = [p for p in results.get('playlists', {}).get('items', []) if p]
        
        for i, p in enumerate(playlists, 1):
            suggestions.append({
                "number": i,
                "name": p.get('name', 'Unknown'),
                "type": "playlist",
                "uri": p.get('uri', ''),
                "owner": p.get('owner', {}).get('display_name', '?')
            })
    else:
        # No mood - suggest based on top artists + some discovery
        top = sp.current_user_top_artists(limit=3, time_range='short_term')
        top_artists = [a['name'] for a in top.get('items', []) if a]
        basis = ""

        if top_artists:
            basis = top_artists[0]
        else:
            followed = sp.current_user_followed_artists(limit=3)
            top_artists = [
                artist['name']
                for artist in (followed.get('artists') or {}).get('items', [])
                if artist and artist.get('name')
            ]
            if top_artists:
                basis = f"followed artist {top_artists[0]}"
        
        # Get related playlists
        if top_artists:
            search_term = f"{top_artists[0]} radio"
            results = sp.search(q=search_term, type='playlist', limit=3)
            playlists = [p for p in results.get('playlists', {}).get('items', []) if p]
            
            for i, p in enumerate(playlists, 1):
                suggestions.append({
                    "number": i,
                    "name": p.get('name', 'Unknown'),
                    "type": "playlist",
                    "uri": p.get('uri', ''),
                    "why": f"Based on {basis}"
                })
    
    if not suggestions:
        return {"ok": False, "speech": "Couldn't generate suggestions", "error": "Empty"}
    
    # Build speech
    speech_parts = ["Here are some suggestions:"]
    for s in suggestions[:3]:
        speech_parts.append(f"{s['number']}. {s['name'][:30]}")
    speech_parts.append("Say 'play number X' to start one.")
    
    return {
        "ok": True,
        "speech": ' '.join(speech_parts),
        "data": {"suggestions": suggestions}
    }


def action_made_for_you(args: dict) -> dict:
    """List Spotify's 'Made For You' personalized playlists (Discover Weekly, Daily Mix, etc.)."""
    sp = get_spotify_client()
    
    personalized = _get_personalized_playlists(sp)
    
    if not personalized:
        return {
            "ok": False,
            "speech": "No Made For You playlists found. Try following Discover Weekly or Daily Mix in Spotify.",
            "error": "No personalized playlists"
        }
    
    # Build list with play instructions
    playlist_info = []
    for p in personalized:
        playlist_info.append({
            "name": p['name'],
            "uri": p['uri'],
            "description": p.get('description', '')[:50] if p.get('description') else '',
            "tracks": p.get('tracks', {}).get('total', 0)
        })
    
    # Speech: list first few
    speech_items = [f"{p['name']}" for p in playlist_info[:5]]
    speech = f"Your Made For You playlists: {', '.join(speech_items)}. Say 'play' followed by any name."
    
    return {
        "ok": True,
        "speech": speech,
        "data": {"playlists": playlist_info, "count": len(playlist_info)}
    }


ACTIONS = {
    'play': action_play,
    'pause': action_pause,
    'next': action_next,
    'previous': action_previous,
    'current': action_current,
    'search': action_search,
    'volume': action_volume,
    'devices': action_devices,
    'transfer': action_transfer,
    'shuffle': action_shuffle,
    'queue': action_queue,
    'share': action_share,
    'recent': action_recent,
    'recommend': action_recommend,
    'top': action_top,
    'followed': action_followed,
    'episodes': action_episodes,
    'suggest': action_suggest,
    'made_for_you': action_made_for_you,  # Personalized playlists (Discover Weekly, etc.)
}


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        action = args.get('action', 'current')
        
        if action not in ACTIONS:
            print(json.dumps({
                "ok": False,
                "speech": f"Unknown action: {action}",
                "error": f"Valid actions: {', '.join(ACTIONS.keys())}"
            }))
            sys.exit(1)
        
        result = ACTIONS[action](args)
        print(json.dumps(result))
        
        if not result.get('ok'):
            sys.exit(1)
            
    except spotipy.exceptions.SpotifyException as e:
        error_msg = str(e)
        if 'NO_ACTIVE_DEVICE' in error_msg or 'No active device' in error_msg:
            speech = "No active Spotify device. Open Spotify on a device first."
        elif 'PREMIUM_REQUIRED' in error_msg:
            speech = "This feature requires Spotify Premium."
        else:
            speech = f"Spotify error: {error_msg[:100]}"
        
        print(json.dumps({
            "ok": False,
            "speech": speech,
            "error": error_msg
        }))
        sys.exit(1)
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "speech": f"Spotify error: {str(e)}",
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == '__main__':
    main()
