# Talk in the Firefox companion

The [Firefox companion](../jarvis-firefox-extension/README.md#hands-free-talk) supports the same hands-free conversation loop as [Web Talk](WEB_TALK.md), with microphone capture and playback in its sidebar or pop-out.

1. For local iteration, temporarily load `jarvis-firefox-extension/manifest.json` in `about:debugging#/runtime/this-firefox`. Reload that temporary add-on after source edits. Load the updated Jarvis Web process through your usual workflow. No ZIP or version bump is needed for this test.
2. Connect the extension to that Web server and choose local/cloud mode. Both STT and TTS must already work in that mode.
3. In the sidebar, open **Settings → Microphone setup**, click **Allow microphone**, and approve Firefox's prompt. Leave the setup tab open. Finish or clear the current draft and attachments, then click **Talk**, speak, and pause. Check that transcription, tool progress, reply, playback, and the return to Listening happen in order.
4. Ask a follow-up. Both turns stay in the same conversation and use the configured response word limits.
5. Check Pause/Resume, Interrupt, End, and Esc. With **Speak to interrupt** off, capture stops during work/playback. Enable it and speak naturally over a longer reply: playback should stop, the complete utterance should become one next turn, and the conversation and tool routing should remain the same. The microphone indicator must clear on Pause/End. Closing or hiding the view ends Talk while accepted work can finish in chat.
6. Open a second sidebar/pop-out. Talk can only run in one view. Reloading or reconnecting must leave the microphone off.

Firefox's microphone permission is separate from add-on/data consent and server access. Existing grants are reused. **Microphone setup** is available in Settings and in preparing/paused Talk controls. Its **Allow microphone** check immediately releases capture and sends nothing. Accept and remember the grant, then return and Resume or start Talk again.

The setup tab must stay open during sidebar Talk: Firefox can leave direct sidebar capture pending even after approval. Start/Resume briefly selects the helper to open capture, then restores your previous tab. The sidebar retains your conversation and controls, and the helper stays in the background while talking. Closing the helper pauses Talk. Pop-outs and full extension tabs capture directly. Startup deadlines release resources and give an actionable message instead of leaving “Preparing microphone…” indefinitely.

The server advertises the optional `extension.features.talk` capability in `/api/status`. Older servers remain compatible for ordinary chat; Talk is disabled until the server is updated and restarted. Spoken requests set `input_mode: talk`, which selects the existing casual response formatter for that turn only. The selected mode's Web/environment word limits remain effective.

The extension packages its own controller and audio detector. Sidebar capture uses a same-extension helper tab; recording, detection, and playback stay in the sidebar. Its authenticated background transport reuses `/api/stt`, `/api/tts`, server-generated answer audio, and ordinary chat admission/cancellation/recovery. Recordings and playback buffers cross the extension's internal message port transiently and never enter recovery storage. Session ownership prevents duplicate capture/playback across windows; losing the owning view releases it. Playback finishes and an authoritative terminal run event arrives before listening restarts. A competing task, including a Completion Guard repair, pauses Talk until explicit Resume.

Talk has the same bounded recording, silence, idle, and speech-length behavior as Web Talk. **Speak to interrupt** defaults off and is saved in extension-local storage. It needs AudioWorklet and confirmed browser echo cancellation; failure leaves the manual **Interrupt to speak** button available. Detection uses sustained audio levels and a playback reference, without keywords or speaker identification. Nearby voices or sustained noise can trigger it, and short/quiet speech can be missed. Test with speakers and headphones before relying on it. Waiting for an unfinished task to stop prevents concurrent turns and cannot undo completed tool effects. Saved chat history is available after a disconnect, but speech is never replayed automatically. Reloading retains the preference without starting capture.

See the companion's [privacy information](../jarvis-firefox-extension/PRIVACY.md) for transmission and retention details.

An interruption that produces no transcript returns to Listening automatically,
without sending a new chat turn or replaying the stopped answer. Actual STT
service failures still pause Talk. Normal idle listening pauses after 30 seconds.
