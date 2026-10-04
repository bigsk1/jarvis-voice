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
protects that policy's inline and wrapping cues through ordinary text cleanup.
Unknown providers and unsupported models preserve no cues. Display cleanup
removes the union of all registered cues regardless of the active provider.
The legacy `preserve_xai_tags` and `preserve_elevenlabs_tags` flags still work.

## Adding or expanding tag support

1. Update or register a `SpeechTagPolicy` in `TTS_TAG_POLICIES`. Supply reviewed
   inline/wrapping vocabularies and the generation toggle's configuration key.
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
