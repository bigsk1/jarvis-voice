# Talk in the Firefox companion

The [Firefox companion](../jarvis-firefox-extension/README.md#hands-free-talk) supports the same hands-free conversation loop as [Web Talk](WEB_TALK.md), with microphone capture and playback in its sidebar or pop-out.

## Start a conversation

1. Install the [Firefox companion](../jarvis-firefox-extension/README.md) and
   connect it to your Jarvis Web server. Choose cloud or local mode; STT and TTS
   must be configured for that mode.
2. In the sidebar, open **Settings → Microphone setup**, click **Allow
   microphone**, and approve Firefox's prompt. Leave the setup tab open.
3. Finish or clear the current draft and attachments, click **Talk**, speak, and
   pause. Jarvis transcribes the utterance, runs the request, plays the answer,
   and returns to Listening in the same conversation.
4. Use **Pause/Resume**, **Interrupt**, **End**, or **Esc** to control the session.
   With **Speak to interrupt** off, capture stops during work/playback. Enable it
   to speak over a reply. Completed tool actions cannot be undone.

Only one extension view can own Talk. Closing or hiding the view ends its
session while accepted work can finish in chat. Reloading or reconnecting leaves
the microphone off. For browser/device checks after source changes, see the
[maintainer reference](development/firefox-talk-delivery.md).

Firefox's microphone permission is separate from add-on/data consent and server access. Existing grants are reused. **Microphone setup** is available in Settings and in preparing/paused Talk controls. Its **Allow microphone** check immediately releases capture and sends nothing. Accept and remember the grant, then return and Resume or start Talk again.

The setup tab must stay open during sidebar Talk: Firefox can leave direct sidebar capture pending even after approval. Start/Resume briefly selects the helper to open capture, then restores your previous tab. The sidebar retains your conversation and controls, and the helper stays in the background while talking. Closing the helper pauses Talk. Pop-outs and full extension tabs capture directly. Startup deadlines release resources and give an actionable message instead of leaving “Preparing microphone…” indefinitely.

The server advertises the optional `extension.features.talk` capability in `/api/status`. Older servers remain compatible for ordinary chat; Talk is disabled until the server is updated and restarted. Spoken requests set `input_mode: talk`, which selects the existing casual response formatter for that turn only. The selected mode's Web/environment word limits remain effective.

The extension packages its own controller and audio detector. Sidebar capture uses a same-extension helper tab; recording, detection, and playback stay in the sidebar. Its authenticated background transport reuses `/api/stt`, `/api/tts`, server-generated answer audio, and ordinary chat admission/cancellation/recovery. Recordings and playback buffers cross the extension's internal message port transiently and never enter recovery storage. Session ownership prevents duplicate capture/playback across windows; losing the owning view releases it. Playback finishes and an authoritative terminal run event arrives before listening restarts. A competing task, including a Completion Guard repair, pauses Talk until explicit Resume.

Talk has the same bounded recording, silence, idle, and speech-length behavior as Web Talk. **Speak to interrupt** defaults off and is saved in extension-local storage. It needs AudioWorklet and confirmed browser echo cancellation; failure leaves the manual **Interrupt to speak** button available. Detection uses sustained audio levels and a playback reference, without keywords or speaker identification. Nearby voices or sustained noise can trigger it, and short/quiet speech can be missed. Test with speakers and headphones before relying on it. Waiting for an unfinished task to stop prevents concurrent turns and cannot undo completed tool effects. Saved chat history is available after a disconnect, but speech is never replayed automatically. Reloading retains the preference without starting capture.

See the companion's [privacy information](../jarvis-firefox-extension/PRIVACY.md) for transmission and retention details.

An interruption that produces no transcript returns to Listening automatically,
without sending a new chat turn or replaying the stopped answer. Actual STT
service failures still pause Talk. Normal idle listening pauses after 30 seconds.
