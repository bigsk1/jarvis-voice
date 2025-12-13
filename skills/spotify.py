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
import os
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


def action_play(args: dict) -> dict:
    """Resume playback or play specific content."""
    sp = get_spotify_client()
    
    query = args.get('query', '')
    device_id = args.get('device_id')
    
    if query:
        # Search and play
        query_lower = query.lower()
        
        # Determine search type
        if 'playlist' in query_lower:
            search_query = query_lower.replace('playlist', '').strip()
            results = sp.search(q=search_query, type='playlist', limit=1)
            items = results.get('playlists', {}).get('items', [])
            if items:
                uri = items[0]['uri']
                name = items[0]['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing playlist {name}",
                    "data": {"uri": uri, "name": name, "type": "playlist"}
                }
        elif 'album' in query_lower:
            search_query = query_lower.replace('album', '').strip()
            results = sp.search(q=search_query, type='album', limit=1)
            items = results.get('albums', {}).get('items', [])
            if items:
                uri = items[0]['uri']
                name = items[0]['name']
                artist = items[0]['artists'][0]['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing album {name} by {artist}",
                    "data": {"uri": uri, "name": name, "artist": artist, "type": "album"}
                }
        else:
            # Default: search for track or artist
            # First try artist
            results = sp.search(q=query, type='artist', limit=1)
            artists = results.get('artists', {}).get('items', [])
            if artists and query_lower in artists[0]['name'].lower():
                uri = artists[0]['uri']
                name = artists[0]['name']
                sp.start_playback(context_uri=uri, device_id=device_id)
                return {
                    "ok": True,
                    "speech": f"Playing {name}",
                    "data": {"uri": uri, "name": name, "type": "artist"}
                }
            
            # Try track
            results = sp.search(q=query, type='track', limit=1)
            tracks = results.get('tracks', {}).get('items', [])
            if tracks:
                uri = tracks[0]['uri']
                name = tracks[0]['name']
                artist = tracks[0]['artists'][0]['name']
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
    """Search for tracks, artists, albums, or playlists."""
    sp = get_spotify_client()
    
    query = args.get('query', '')
    search_type = args.get('type', 'track')  # track, artist, album, playlist
    limit = args.get('limit', 5)
    
    if not query:
        return {"ok": False, "speech": "What should I search for?", "error": "No query"}
    
    results = sp.search(q=query, type=search_type, limit=limit)
    
    items = []
    type_key = f"{search_type}s"  # tracks, artists, albums, playlists
    
    for item in results.get(type_key, {}).get('items', []):
        if search_type == 'track':
            items.append({
                "name": item['name'],
                "artist": item['artists'][0]['name'],
                "uri": item['uri']
            })
        elif search_type == 'artist':
            items.append({
                "name": item['name'],
                "uri": item['uri']
            })
        elif search_type == 'album':
            items.append({
                "name": item['name'],
                "artist": item['artists'][0]['name'],
                "uri": item['uri']
            })
        elif search_type == 'playlist':
            items.append({
                "name": item['name'],
                "owner": item['owner']['display_name'],
                "uri": item['uri']
            })
    
    if items:
        first = items[0]
        if search_type == 'track':
            speech = f"Found {first['name']} by {first['artist']}"
        elif search_type == 'playlist':
            speech = f"Found playlist {first['name']}"
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
        results = sp.search(q=query, type='track', limit=1)
        tracks = results.get('tracks', {}).get('items', [])
        if tracks:
            uri = tracks[0]['uri']
            name = tracks[0]['name']
            artist = tracks[0]['artists'][0]['name']
        else:
            return {
                "ok": False,
                "speech": f"Couldn't find track {query}",
                "error": "Track not found"
            }
    
    sp.add_to_queue(uri)
    
    return {
        "ok": True,
        "speech": f"Added {name} by {artist} to queue" if 'name' in dir() else "Added to queue",
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

