# Spotify Integration for Jarvis

Control Spotify playback with voice commands. Jarvis can play music, search, control playback, and switch between devices.

## Quick Start

Spotify is registered as an available Jarvis tool only when both
`SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are set in the active mode env
file and `data/.spotify_cache` exists. Complete OAuth setup with:

```bash
./bin/spotify-auth
```

Restart Jarvis or run `./bin/sync-tools.py <mode>` afterward. Missing credentials
or an absent token cache show Spotify as needing configuration instead of allowing
a tool call that is guaranteed to fail.

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
| "Play my liked songs" | Plays your saved/liked tracks |
| "Play my favorites" | Same as liked songs |
| "Play my saved songs" | Same as liked songs |

**Tips:**
- **Your library is searched first** - Jarvis checks your saved playlists before public Spotify
- Include "playlist" in your request to search playlists specifically
- Include "album" to search albums
- Just say an artist name to play their music
- Vague requests like "play something good" work via Spotify's search
- Fuzzy matching works: "rock" finds "dad rock🤘", "grunge" finds "90's grunge🎸"

### 🎄 Holiday & Seasonal Music (NEW!)

| What You Say | What Happens |
|--------------|--------------|
| **"Play my Christmas playlist"** | Plays YOUR saved Christmas playlist from memory |
| **"Play Christmas music"** | Searches Spotify's entire catalog (millions of options!) |
| **"Play traditional Christmas music"** | Searches public playlists |
| **"Play holiday music"** | Genre-based holiday search |

**How it works:**
- "**My** Christmas playlist" → Checks your library/memory first
- "Christmas music" (generic) → Searches Spotify's vast catalog
- Supports: christmas, holiday, xmas, halloween, thanksgiving, summer, winter, etc.

### 🎯 Personalized Features

| What You Say | What Happens |
|--------------|--------------|
| "What are my top songs?" | Shows your most played tracks |
| "Who are my top artists?" | Shows your most played artists |
| "Play my recommendations" | Plays personalized mix based on your taste |
| "Recommend something energetic" | Upbeat recommendations for workouts |
| "Recommend chill music" | Relaxed recommendations |
| "What playlists have I played recently?" | Shows recently played playlists |
| **"Play my Discover Weekly"** | Plays your personalized weekly playlist |
| **"Play Release Radar"** | Plays new releases from artists you follow |
| **"Play Daily Mix 1"** | Plays your Daily Mix playlists |
| **"List my Made For You playlists"** | Shows all personalized Spotify playlists |

### 🎙️ Podcast Conversations

| What You Say | What Happens |
|--------------|--------------|
| **"What are the latest Joe Rogan episodes?"** | Lists recent episodes with dates |
| **"Play Joe Rogan episode 2425"** | Plays specific episode by number |
| **"Play JRE #2424"** | Plays by episode number |
| "Play latest Joe Rogan podcast" | Plays most recent episode |
| "What's new on This Past Weekend?" | Lists Theo Von episodes |

**Conversational Flow:**
```
You: "What are the latest Joe Rogan episodes?"
Jarvis: "#2425 Ethan Hawke (Dec 11), #2424 Jelly Roll (Dec 10)..."

You: "Play episode 2425"
Jarvis: "Playing #2425 - Ethan Hawke"
```

### 🎵 Music Suggestions

| What You Say | What Happens |
|--------------|--------------|
| **"What music do you recommend tonight?"** | Plays personalized recommendations |
| **"Suggest some chill music"** | Lists suggestions (doesn't auto-play) |
| **"Give me music suggestions"** | Browse before playing |

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

### 🎙️ Podcasts

Jarvis can play podcasts and automatically gets the **latest episode**:

| What You Say | What Happens |
|--------------|--------------|
| "Play the latest Joe Rogan podcast" | Plays most recent JRE episode |
| "Latest episode of This Past Weekend" | Plays newest Theo Von episode |
| "Play latest from Tim Dillon" | Finds show, plays newest |
| "Newest episode of Lex Fridman" | Latest Lex Fridman episode |
| "Play Kill Tony podcast" | Plays latest Kill Tony |
| "Search podcast Joe Rogan" | Shows podcast results |
| **"Play Joe Rogan #2425"** | Plays specific episode by number |
| **"Play JRE episode 2424"** | Plays by episode number |

**Tips:**
- Use "latest", "newest", or "podcast" to trigger podcast mode
- Works with ANY podcast name - just search naturally
- Gets the actual latest episode, not episode #1
- Use "#" or "episode" followed by number for specific episodes

### 🔍 Search

| What You Say | What Happens |
|--------------|--------------|
| "Search for Beatles" | Searches and shows results |
| "Find playlist workout" | Searches playlists |
| "Look up album Thriller" | Searches albums |
| "Search podcast comedy" | Searches podcasts/shows |

### 📝 Queue

| What You Say | What Happens |
|--------------|--------------|
| "Add this to queue" | Queues current context |
| "Queue Bohemian Rhapsody" | Adds song to queue |
| "Add Purple Rain to queue" | Queues specific track |

### 📧 Share

Share the current song via email with album art:

| What You Say | What Happens |
|--------------|--------------|
| "Share this song with [contact]" | Emails song info + album art |
| "Email this track to boss" | Sends song details to boss |
| "Share what's playing with Andrew" | Rich email with Spotify link |

The email includes:
- 🎵 Song title, artist, album
- 🖼️ Album art image
- ▶️ "Listen on Spotify" button

---

## 📚 Library Export & Memory Integration (NEW!)

Jarvis can learn your personal Spotify library to play your music more accurately.

### Export Your Library

```bash
# Export playlists, podcasts, top artists/tracks to intel file
./bin/spotify-export-library

# Ingest into Jarvis memory
python3 skills/ingest_intel.py
```

This creates `jarvis-intel/spotify-library.md` with:
- All your playlists (with Spotify URIs)
- Subscribed podcasts
- Top artists and tracks
- Genre tags

### How Memory Integration Works

| Request Type | Behavior |
|--------------|----------|
| "Play **my** Christmas playlist" | Checks memory first → uses saved URI |
| "Play Christmas music" | Searches Spotify catalog (generic) |
| "Play **my** rock playlist" | Memory lookup → your specific playlist |
| "Play some rock" | Searches Spotify's massive library |

**The key word is "my"** - it triggers personal library lookup.

### Re-export Periodically

When you save new playlists or follow new podcasts:

```bash
./bin/spotify-export-library
python3 skills/ingest_intel.py
```

---

## Your Devices

Based on your setup:

| Device | Type | Best For |
|--------|------|----------|
| **Office fire TV** | TV | Office listening |
| **Living Room Fire TV** | TV | Living room |
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
"Play Christmas music"
"Play holiday classics"
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
"Play my Christmas playlist"
```

### Control Flow
```
"Pause for a minute"
"Skip this one"
"Go back to the last song"
"Play that on the bedroom speaker"
"Turn shuffle on and play some rock"
```

### Podcasts
```
"Play the latest Joe Rogan podcast"
"Latest episode of This Past Weekend"
"Play newest Lex Fridman"
"What's the latest Kill Tony?"
"Play Tim Dillon podcast"
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
- For personal playlists, use "my": "Play **my** rock playlist"

### "Playing wrong playlist"

If Jarvis plays something unexpected (e.g., classic rock when you asked for Christmas):
1. Re-export your library: `./bin/spotify-export-library`
2. Re-ingest: `python3 skills/ingest_intel.py`
3. Use explicit "my" for personal: "Play **my** Christmas playlist"

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

### Actions Available (18 total)

| Action | Description | Required Params |
|--------|-------------|-----------------|
| `play` | Resume or play content (music, podcasts, Discover Weekly, etc.) | `query` (optional) |
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
| `share` | Get shareable info | - |
| `recent` | Recently played playlists | - |
| `recommend` | Play personalized recommendations | `mood` (optional) |
| `top` | Show top tracks/artists | `type` (track/artist) |
| `episodes` | List podcast episodes | `query` (show name) |
| `suggest` | Get music suggestions (no auto-play) | `mood` (optional) |
| `made_for_you` | List personalized playlists (Discover Weekly, etc.) | - |

### Search Types

| Type | Description | Example |
|------|-------------|---------|
| `track` | Songs (default) | "Bohemian Rhapsody" |
| `artist` | Artists | "Queen" |
| `album` | Albums | "A Night at the Opera" |
| `playlist` | Playlists | "workout mix" |
| `show` / `podcast` | Podcasts | "Joe Rogan" |
| `episode` | Podcast episodes | "JRE #2425" |

### Genre/Mood Keywords

The tool recognizes these keywords to prefer playlist search:
- **Genres:** pop, rock, jazz, classical, hip hop, rap, country, r&b, indie, electronic
- **Moods:** upbeat, chill, relaxing, workout, party, focus
- **Eras:** 80s, 90s, 2000s, 2010s, 70s, 60s
- **Seasonal:** christmas, holiday, xmas, halloween, thanksgiving, summer, winter, spring, fall, valentines

### Files

| File | Purpose |
|------|---------|
| `skills/spotify.py` | Main tool implementation |
| `skills/spotify.tool.json` | Tool definition for LLM |
| `bin/spotify-auth` | OAuth setup script |
| `bin/spotify-export-library` | Export library to intel file |
| `data/.spotify_cache` | Token cache (gitignored) |
| `jarvis-intel/spotify-library.md` | Your library for memory ingestion |

### Config Variables

In `config/cloud.env`:
```bash
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIFY_DEFAULT_DEVICE=Office fire TV  # Optional default device
```

### API Scopes

The tool requests these Spotify scopes:
- `user-read-playback-state` - See what's playing
- `user-modify-playback-state` - Control playback
- `user-read-currently-playing` - Current track info
- `playlist-read-private` - Access private playlists
- `playlist-read-collaborative` - Access collaborative playlists
- `user-library-read` - Access Liked Songs
- `user-read-recently-played` - Recently played tracks/playlists
- `user-top-read` - Top tracks and artists
- `user-follow-read` - Followed playlists/artists

---

## Setup (Already Done)

For reference, initial setup was:

1. Create app at https://developer.spotify.com/dashboard
2. Add credentials to `config/cloud.env`
3. Run `./bin/spotify-auth`
4. Authorize in browser
5. Sync tools: `./bin/sync-tools.py cloud`
6. Export library: `./bin/spotify-export-library` (optional but recommended)
7. Ingest: `python3 skills/ingest_intel.py`

---

## Ideas for Future

### Completed
- [x] ~~"Play my Liked Songs"~~ ✅ Done!
- [x] ~~Play specific podcast episode by number~~ ✅ Done! ("Play JRE #2425")
- [x] ~~List podcast episodes~~ ✅ Done! ("What are latest Joe Rogan episodes?")
- [x] ~~Made For You playlists~~ ✅ Done! (Discover Weekly, Daily Mix, Release Radar)
- [x] ~~Library export & memory integration~~ ✅ Done! (Dec 2025)
- [x] ~~Holiday/seasonal keyword support~~ ✅ Done! (christmas, halloween, etc.)

### Queue & Playback
- [ ] "What's in my queue?" - Show upcoming tracks
- [ ] "Clear the queue" - Empty the queue
- [ ] "Repeat this song" - Toggle repeat mode
- [ ] "Play similar to this" - Radio from current track

### Playlist Management
- [ ] "Add to playlist [name]" - Add current song to a playlist
- [ ] "Create playlist called [name]" - Create new playlist
- [ ] "Add [song] to [playlist]" - Add specific song
- [ ] "Remove this from [playlist]" - Remove from playlist

### Smart Features
- [ ] Schedule playback: "Play jazz at 7am tomorrow"
- [ ] Smart home integration: "Play music when I get home"
- [ ] Context-aware suggestions: "What should I play for dinner?"
- [ ] Auto-DJ mode: Smooth transitions between genres

### Social
- [ ] "What are my friends listening to?" - Friend activity
- [ ] Collaborative playlist suggestions
- [ ] "Play what [friend] is playing"

### Analytics
- [ ] "What's my most played song this month?"
- [ ] "Show my listening stats"
- [ ] Genre breakdown visualization

---

## Known Limitations

### Volume Control
Some devices (Fire TV, Chromecast, Echo) don't allow volume control via the Spotify API. Error: `VOLUME_CONTROL_DISALLOW`. Use the device's remote instead.

### Device Must Be Active
At least one device must have Spotify running for the API to control it. If you get "No active device", open Spotify on any device first.

### Personal vs Public Search
- **"My [playlist]"** = searches your library/memory
- **Generic request** = searches Spotify's public catalog
- Memory search only triggers for explicit "my" or "saved" requests to prevent false matches

---

**Last Updated:** 2025-12-23
