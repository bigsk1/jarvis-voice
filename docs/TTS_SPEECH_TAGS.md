# TTS speech tags

`lib/tts_style_tags.py` owns the reviewed vocabularies, provider/model gates,
generation toggles, and final-speech prompt instructions. It uses only the
standard library and does not load configuration during import.

The router and response formatter both call `tts_style_tags_instruction()` with
their scoped configuration getter. Detailed router responses do not request cues.
The generation toggle controls what the LLM is asked to produce; it does not
reject explicit supported cues in speech requests.

Playback paths select a `SpeechTagPolicy` through `speech_tag_options()` using
the actual provider and effective final/status model. `lib/tts_normalizer.py`
protects that policy's inline, wrapping, and parameterized cues through ordinary text cleanup.
Unknown providers and unsupported models preserve no cues. Display cleanup
removes recognized cues from all providers in prose, regardless of the active provider.
Fenced and inline code examples remain literal in display, email, and saved
history. Speech reads examples as text without executing their delivery cues;
ordinary code brackets such as `items[0]` and `name[i]` remain content.
The legacy `preserve_xai_tags` and `preserve_elevenlabs_tags` flags still work.

## Kokoro-FastAPI

When `TTS_PROVIDER=kokoro`, the final-speech hint supports occasional short
`[pause:0.4s]` cues and English pronunciation overrides such as
`[Worcester](/wˈʊstər/)`. `KOKORO_TTS_STYLE_TAGS_ENABLED=false` disables automatic
cue guidance; explicitly supplied supported cues still work. The hint follows
the TTS provider, independently of the LLM provider and system-prompt version.

Jarvis protects these tokens from Markdown, path, and number cleanup and
preserves blank paragraph breaks for Kokoro's sentence segmentation. Display
text shows the ordinary word without IPA and hides delivery controls. Other
TTS providers receive the ordinary word without Kokoro controls.

Cue recognition is deliberately narrow. Bracketed facts such as
`[rate: 5 requests per minute]`, `[voice: front door]`, and `[pause: a beat]`
remain content. Numeric pause/rate controls and Kokoro voice identifiers are
recognized; a keyword followed by a colon alone does not make a speech cue.
IPA overrides require a distinctive IPA symbol or stress mark. Ambiguous
ASCII-only forms such as `[Docs](/docs/)` and `[word](/ti/)` stay Markdown links
in display and become their labels in reply speech. Use a known IPA spelling
with an IPA symbol or stress mark when requesting a pronunciation override.

The configured voice (including supported voice blends) and `KOKORO_TTS_SPEED`
continue to apply to the full request. Inline rate/voice switching and SSML are
not enabled: reply normalization removes recognized controls, while `generate_audio`
rejects unsupported controls before sending its exact script. Kokoro has no
emotion-tag support. Pauses are bounded to 60 seconds each and 300 seconds total,
matching the server; generated replies should use only short pauses because
existing speech timeouts still apply.

These controls require the corresponding Kokoro-FastAPI server support; they
were verified against [v0.9.2](https://github.com/remsky/Kokoro-FastAPI/tree/v0.9.2).
Ordinary URL, emoji, internal-ID, and visual-noise cleanup remains active. The
server's text normalization remains enabled; Jarvis adds no phonemization call
or network lookup to each reply.

Native reminders, alerts, follow-ups, greetings, and self-healing announcements
select their actual playback policy before normalization. Status speech uses
the status model override where applicable. Talk preserves complete pause/IPA
tokens when it divides a long spoken reply into requests.

After updating Jarvis, restart long-running processes that generate speech
(such as Web, FastAPI, and native voice) to load the new policy. Refresh Web
tabs to load the matching display cleanup. CLI requests pick it up on launch.

Status-audio caches include spoken text with its pause/IPA cues, provider,
voice, speed, and endpoint. Changing a cue changes the key. The generation-hint
toggle is excluded because it does not change synthesis of identical supplied
text; this integration adds no new Kokoro request flag. Final replies and
`generate_audio` synthesize fresh audio. Upgrading the backend at the same URL
can leave old status clips cached; use the existing `bin/status-cache` cleanup
when those clips need regeneration. No cache purge is needed for the hint toggle.

## Adding or expanding tag support

1. Update or register a `SpeechTagPolicy` in `TTS_TAG_POLICIES`. Supply reviewed
   inline/wrapping vocabularies and the generation toggle's configuration key.
   Parameterized controls also need exact parsing, bounds, fallback display,
   and generated-audio validation; listing a token name alone does not enable it.
2. For a model-specific provider, supply its model setting, supported playback
   models, and generation models. `None` allows all models; an empty set allows
   none. ElevenLabs v3 accepts explicit cues, while automatic generation remains
   limited to v4 and v4 Turbo.
3. Wire the provider's effective model into playback callers when adding a new
   provider transport. Prompts read the model setting from its registered policy.
   Payload settings, audio transport, and character limits remain provider code.
4. Update the browser vocabulary mirror in `jarvis-web/client/js/utils.js`.
   `test_web_assistant_message_rendering.py` checks it against the complete registry.
5. Run the policy, normalization, router, formatter, and affected playback tests.

Adding reviewed tags does not require copying prompt text into either
orchestrator component or adding a new preservation branch to the normalizer.
