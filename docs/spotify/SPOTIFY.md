# Spotify Integration for Jarvis

Control Spotify playback with voice commands. Jarvis can play music, search, control playback, and switch between devices.

## Quick Start

Just talk naturally! Jarvis understands context:

```
"Hey Jarvis, play some music"
"Hey Jarvis, what's playing?"
"Hey Jarvis, skip this song"
"Hey Jarvis, play on the SHIELD"
```

---

## What You Can Say

### 🎵 Play Music

Jarvis can play artists, songs, albums, playlists, or just vibe-based requests:

| What You Say | What Happens |
|--------------|--------------|
| "Play some jazz" | Searches for jazz and plays it |
| "Play Daft Punk" | Plays Daft Punk's top tracks |
| "Play Discovery by Daft Punk" | Plays the album |
| "Play the song Around the World" | Plays that specific track |
| "Play my workout playlist" | Searches your playlists |
| "Play something good" | Plays recommendations |
| "Play hard rock" | Genre-based playback |
| "Play some chill music" | Mood-based playback |
| "Resume music" / "Play" | Resumes paused playback |

**Tips:**
- Include "playlist" in your request to search playlists specifically
- Include "album" to search albums
- Just say an artist name to play their music
- Vague requests like "play something good" work via Spotify's search

### ⏸️ Playback Control

| What You Say | What Happens |
|--------------|--------------|
| "Pause" / "Pause the music" | Pauses playback |
| "Stop the music" | Pauses playback |
| "Next" / "Skip" / "Next song" | Skips to next track |
| "Previous" / "Go back" | Previous track |
| "Shuffle on" / "Turn on shuffle" | Enables shuffle |
| "Shuffle off" | Disables shuffle |

### 🔊 Volume

| What You Say | What Happens |
|--------------|--------------|
| "Volume 50" | Sets volume to 50% |
| "Set volume to 80" | Sets volume to 80% |
| "Turn it up" | Increase volume (say a number) |
| "Quieter" | Decrease volume (say a number) |

### ❓ What's Playing?

| What You Say | What Happens |
|--------------|--------------|
| "What's playing?" | Shows current track info |
| "What song is this?" | Current track name/artist |
| "What's on Spotify?" | Current playback status |

### 📱 Devices

| What You Say | What Happens |
|--------------|--------------|
| "List Spotify devices" | Shows all available devices |
| "What devices do I have?" | Lists devices with status |
| "Play on SHIELD" | Transfers playback to SHIELD |
| "Play on Fire TV" | Transfers to Fire TV |
| "Switch to Office Echo" | Moves playback to Echo |
| "Play on the TV" | Jarvis picks a TV device |

### 🔍 Search

| What You Say | What Happens |
|--------------|--------------|
| "Search for Beatles" | Searches and shows results |
| "Find playlist workout" | Searches playlists |
| "Look up album Thriller" | Searches albums |

### 📝 Queue

| What You Say | What Happens |
|--------------|--------------|
| "Add this to queue" | Queues current context |
| "Queue Bohemian Rhapsody" | Adds song to queue |
| "Add Purple Rain to queue" | Queues specific track |

---

## Your Devices

Based on your setup:

| Device | Type | Best For |
|--------|------|----------|
| **Office fire TV** | TV | Office listening |
| **Wayne's Fire TV** | TV | Living room |
| **SHIELD** | TV | Main TV (cameras displayed here) |
| **Office Echo** | Speaker | Office background music |
| **Echo Dot garage** | Speaker | Garage |
| **Echo garage** | Speaker | Garage |

**Note:** At least one device must have Spotify open/active for playback to work. The API controls existing players - it doesn't create new ones.

---

## Natural Language Examples

Jarvis is smart about understanding intent. These all work:

### Mood/Genre Based
```
"Play something relaxing"
"Play some upbeat music"
"Play classic rock"
"Play 80s hits"
"Play electronic music"
"Play some country"
```

### Activity Based
```
"Play workout music"
"Play music for cooking"
"Play focus music"
"Play party music"
"Play dinner music"
```

### Specific Requests
```
"Play Hotel California by the Eagles"
"Play anything by Queen"
"Play the album Rumours"
"Play my Liked Songs"
"Play my Discover Weekly"
```

### Control Flow
```
"Pause for a minute"
"Skip this one"
"Go back to the last song"
"Play that on the bedroom speaker"
"Turn shuffle on and play some rock"
```

---

## Troubleshooting

### "No active device"

Spotify needs an active player somewhere. Fix:
1. Open Spotify on any device (Fire TV, phone, Echo, etc.)
2. Start playing something manually (even for 1 second)
3. Then Jarvis can take over control

### "Can't find [playlist/song]"

- Check spelling
- Try being more specific: "Play playlist called Workout Mix"
- Try the artist: "Play something by [artist]"

### "Device not found"

- Say "List my Spotify devices" to see what's available
- Device names are case-insensitive but should be close
- The device must have Spotify running

### Token expired

If you get auth errors after a long time:
```bash
./bin/spotify-auth
```
Then re-authorize in browser.

---

## Technical Details

### Actions Available

| Action | Description | Required Params |
|--------|-------------|-----------------|
| `play` | Resume or play content | `query` (optional) |
| `pause` | Pause playback | - |
| `next` | Skip track | - |
| `previous` | Previous track | - |
| `current` | Get playing info | - |
| `search` | Search content | `query`, `type` |
| `volume` | Set volume | `level` (0-100) |
| `devices` | List devices | - |
| `transfer` | Switch device | `device` name |
| `shuffle` | Toggle shuffle | `state` (optional) |
| `queue` | Add to queue | `query` |

### Files

| File | Purpose |
|------|---------|
| `skills/spotify.py` | Main tool implementation |
| `skills/spotify.tool.json` | Tool definition for LLM |
| `bin/spotify-auth` | OAuth setup script |
| `data/.spotify_cache` | Token cache (gitignored) |

### Config Variables

In `config/cloud.env`:
```bash
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

### API Scopes

The tool requests these Spotify scopes:
- `user-read-playback-state` - See what's playing
- `user-modify-playback-state` - Control playback
- `user-read-currently-playing` - Current track info
- `playlist-read-private` - Access private playlists
- `playlist-read-collaborative` - Access collaborative playlists
- `user-library-read` - Access Liked Songs

---

## Setup (Already Done)

For reference, initial setup was:

1. Create app at https://developer.spotify.com/dashboard
2. Add credentials to `config/cloud.env`
3. Run `./bin/spotify-auth`
4. Authorize in browser
5. Sync tools: `./bin/sync_tools.py cloud`

---

## Ideas for Future

- [ ] "Play my Liked Songs" (requires different API call)
- [ ] "What's in my queue?"
- [ ] "Clear the queue"
- [ ] "Repeat this song"
- [ ] "Add to playlist [name]"
- [ ] Playlist management (create, add songs)
- [ ] "Play similar to this"
- [ ] Integration with calendar (morning playlist at 7am)

---

**Last Updated:** 2024-12-13

