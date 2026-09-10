"""Execute video source journeys through the real browser composer methods."""

import pytest
from test_web_attachment_bundle_ui import run_browser


def test_video_classification_precedes_audio_container_detection():
    run_browser(r"""
const ui = chat();
for (const name of ['screen.mp4', 'SCREEN.WEBM', 'clip.mov', 'clip.mkv', 'clip.avi', 'clip.m4v', 'clip.mpeg', 'clip.mpg']) {
  assert.equal(ui._attachmentKind(file(name)), 'video', name);
}
assert.equal(ui._attachmentKind(file('capture', 'video/mp4')), 'video');
assert.equal(ui._attachmentKind(file('recording.mp4', 'audio/mp4')), 'video');
for (const name of ['memo.m4a', 'recording.wav', 'meeting.mp3']) {
  assert.equal(ui._attachmentKind(file(name)), 'audio', name);
}
const html = fs.readFileSync(ROOT + '/jarvis-web/client/index.html', 'utf8');
const input = html.match(/<input[^>]+id="fileInput"[^>]*>/)[0];
for (const format of ['video/*', '.mov', '.mkv', '.avi', '.m4v', '.mpeg', '.mpg']) assert.ok(input.includes(format));
""")


def test_mpeg_audio_bitstream_retains_audio_upload_and_playback():
    run_browser(r"""
const ui = chat();
ui.inputField.value = '';
await ui.attachFile(file('recording.mpeg', 'audio/mpeg; codecs=mp3'));
assert.equal(ui.attachedDocuments[0].kind, 'audio');
assert.equal(ui.filePreviewContainer.querySelectorAll('audio').length, 1);
assert.equal(ui.filePreviewContainer.querySelectorAll('video').length, 0);
await ui.sendMessage();
assert.deepEqual(requests.map(item => item.url), ['/api/upload-audio']);
assert.equal(sent[0][5][0].kind, 'audio');
assert.match(ui.messagesContainer.children[0].innerHTML, /Transcribe this audio recording/);
assert.doesNotMatch(ui.messagesContainer.children[0].innerHTML, /<video/);
""")


def test_video_mixed_bundle_uploads_once_in_source_order_with_preview_cleanup():
    run_browser(r"""
const ui = chat();
await ui._attachMultipleFiles([file('notes.txt'), file('silent.mp4', 'video/mp4'), file('report.pdf')]);
assert.equal(requests.length, 0);
const video = ui.attachedDocuments[1];
const preview = ui.filePreviewContainer.querySelectorAll('video')[0];
assert.equal(preview.controls, true);
assert.equal(preview.playsInline, true);
assert.equal(preview.preload, 'metadata');
assert.equal(preview.src, video.previewUrl);
const uploadId = video.uploadId;
await ui.sendMessage();
assert.deepEqual(requests.map(item => item.url), ['/api/upload-text', '/api/upload-video', '/api/upload-pdf']);
assert.equal(requests[1].body.entries.upload_id, uploadId);
assert.equal(requests[1].body.entries.mode, 'cloud');
assert.deepEqual(Array.from(sent[0][5], item => item.kind), ['text', 'video', 'pdf']);
assert.equal(ui.attachedDocuments.length, 0);
assert.equal(preview.paused, true);
assert.deepEqual(revoked, [video.previewUrl]);
const html = ui.messagesContainer.children[0].innerHTML;
assert.match(html, /Source 2: silent.mp4/);
assert.match(html, /<video controls playsinline/);
assert.match(html, /Open original/);
assert.doesNotMatch(html, /Transcribe this/);
""")


def test_audio_only_container_uses_server_inspection_and_retains_upload_identity():
    run_browser(r"""
const ui = chat();
ui.inputField.value = '';
await ui.attachFile(file('voice.mp4', 'video/mp4'));
const item = ui.attachedDocuments[0];
sandbox.fetch = async (url, options) => {
  requests.push({url, ...options});
  return {ok:true, json:async()=>({ok:true, attachment:{kind:'audio', filename:'voice.mp4', stash_ref:'stash://clips/voice', mime_type:'audio/mp4'}})};
};
// Leave the upload in the composer, as a stopped send can do, then retry.
await ui._uploadAttachedDocument(item, ui._attachmentContext());
ui._renderDocumentPreviews();
assert.equal(item.kind, 'video');
assert.equal(item.attachment.kind, 'audio');
assert.equal(ui.filePreviewContainer.querySelectorAll('audio').length, 1);
assert.equal(ui.filePreviewContainer.querySelectorAll('video').length, 0);
await ui.sendMessage();
assert.equal(requests.length, 1);
assert.equal(requests[0].url, '/api/upload-video');
assert.equal(sent[0][5][0].kind, 'audio');
assert.match(ui.messagesContainer.children[0].innerHTML, /Transcribe this audio recording/);
assert.doesNotMatch(ui.messagesContainer.children[0].innerHTML, /<video/);
""")


def test_video_upload_rejects_unrelated_kind_and_failed_retry_keeps_draft():
    run_browser(r"""
const ui = chat();
await ui.attachFile(file('screen.mp4'));
const id = ui.attachedDocuments[0].uploadId;
sandbox.fetch = async (url, options) => {requests.push({url, ...options}); return response('text', 'screen.mp4');};
await ui.sendMessage();
assert.equal(sent.length, 0);
assert.equal(ui.inputField.value, 'Compare these sources');
assert.equal(ui.attachedDocuments.length, 1);
assert.equal(ui.attachedDocuments[0].attachment, null);
sandbox.fetch = async (url, options) => {requests.push({url, ...options}); return response('video', 'screen.mp4');};
await ui.sendMessage();
assert.equal(sent.length, 1);
assert.deepEqual(requests.map(item => item.body.entries.upload_id), [id, id]);
""")


@pytest.mark.parametrize("interruption", ["cancel", "conversation", "mode"])
def test_interrupted_video_upload_cannot_send_a_stale_request(interruption):
    run_browser(r"""
const ui = chat();
await ui.attachFile(file('screen.mp4'));
const original = ui.attachedDocuments[0];
const pending = deferred();
sandbox.fetch = async (url, options) => {requests.push({url, ...options}); return pending.promise;};
const sending = ui.sendMessage();
await Promise.resolve();
""" + {
        "cancel": "ui.cancelProcessing(); assert.equal(requests[0].signal.aborted, true);",
        "conversation": "socket.conversationId = 'another';",
        "mode": "socket.mode = 'local'; ui.cancelAttachmentPreparation();",
    }[interruption] + r"""
pending.resolve(response('video', 'screen.mp4'));
await sending;
assert.equal(sent.length, 0);
assert.equal(ui.isProcessing, false);
assert.equal(ui._attachmentSend, null);
assert.equal(original.attachment.kind, 'video');
assert.equal(original.attachment.mode, 'cloud');
assert.equal(ui.attachedDocuments[0], original);
""")


def test_video_obeys_chat_only_and_shared_mode_source_limits():
    run_browser(r"""
socket.mode = 'local';
const ui = chat();
await ui._attachMultipleFiles([file('one.mp4'), file('two.mp4'), file('notes.txt')]);
assert.equal(ui.attachedDocuments.length, 0);
assert.equal(requests.length, 0);
assert.ok(notices.some(item => item[0].includes('Maximum 2 sources')));
await ui._attachMultipleFiles([file('one.mp4'), file('notes.txt')]);
ui.chatOnlyEnabled = true;
await ui.sendMessage();
assert.equal(requests.length, 0);
assert.equal(sent.length, 0);
assert.ok(notices.some(item => item[0].includes('Chat only') && item[0].includes('video')));
ui.chatOnlyEnabled = false;
await ui.sendMessage();
assert.equal(sent.length, 1);
assert.ok(requests.every(item => item.body.entries.mode === 'local'));
""")


def test_saved_silent_video_restores_playback_in_original_mode_and_escapes_labels():
    run_browser(r"""
socket.mode = 'local';
const ui = chat();
const app = Object.create(JarvisApp.prototype);
Object.assign(app, {chat:ui, socket, _updateActiveConversation(){}, _updateConvIdBadge(){}, _loadConversationHistory(){}});
const attachments = [{kind:'video', filename:'<screen>.mp4', stash_ref:'stash://clips/silent', mime_type:'video/mp4', has_audio:false, duration_seconds:65, mode:'cloud'}];
await app._displayLoadedConversation({id:'saved', messages:[{role:'user', content:'', data:{attachments}}]});
const html = ui.messagesContainer.children[0].innerHTML;
assert.match(html, /Analyze this video/);
assert.match(html, /Source 1: &lt;screen&gt;.mp4/);
assert.match(html, /<video controls playsinline/);
assert.match(html, /src="\/api\/stash\/clips\/silent\?mode=cloud"/);
assert.match(html, /1:05 · No audio track/);
assert.match(html, /download="&lt;screen&gt;.mp4"/);
assert.doesNotMatch(html, /<screen>/);
assert.equal(requests.length, 0);
""")


def test_invalid_saved_video_reference_is_not_rendered_as_active_media():
    run_browser(r"""
const ui = chat();
ui.addUserMessage('Inspect', null, '', [{kind:'video', filename:'clip.mp4', stash_ref:'javascript:alert(1)', url:'https://external.invalid/clip.mp4'}]);
const html = ui.messagesContainer.children[0].innerHTML;
assert.match(html, /Source 1: clip.mp4/);
assert.doesNotMatch(html, /<video|javascript:|external.invalid/);
""")


def test_mixed_audio_and_video_players_follow_the_selected_source_order():
    run_browser(r"""
const ui = chat();
ui.addUserMessage('Compare', null, '', [
  {kind:'video', filename:'one.mp4', stash_ref:'stash://clips/one'},
  {kind:'audio', filename:'voice.wav', stash_ref:'stash://clips/voice'},
  {kind:'video', filename:'two.mp4', stash_ref:'stash://clips/two'}
]);
const html = ui.messagesContainer.children[0].innerHTML;
assert.deepEqual(Array.from(html.matchAll(/<(video|audio) /g), match => match[1]), ['video', 'audio', 'video']);
""")


def test_removing_video_previews_stops_playback_and_revokes_each_blob_once():
    run_browser(r"""
const ui = chat();
await ui._attachMultipleFiles([file('one.mp4'), file('two.mov')]);
const [first, second] = ui.attachedDocuments;
const previews = ui.filePreviewContainer.querySelectorAll('video');
ui._removeAttachedDocument(first);
assert.ok(previews.every(item => item.paused));
assert.deepEqual(revoked, [first.previewUrl]);
const remainingPreview = ui.filePreviewContainer.querySelectorAll('video')[0];
const savedPlayer = new Element('video');
ui.messagesContainer.appendChild(savedPlayer);
ui.clearChat();
assert.equal(remainingPreview.paused, true);
assert.equal(savedPlayer.paused, true);
assert.deepEqual(revoked, [first.previewUrl, second.previewUrl]);
assert.equal(ui.attachedDocuments.length, 0);
""")


def test_video_result_card_exposes_sample_coverage_partial_evidence_and_original_source():
    run_browser(r"""
const ui = chat();
const data = {
  source_filename:'screen.mp4', source_stash_ref:'stash://clips/screen', mode:'cloud',
  start_seconds:0, end_seconds:12.5, duration_seconds:90,
  frame_timestamps:[0, 2.5, 5, 7.5, 10, 12.5],
  visual_status:'complete', audio_status:'unavailable', partial:true,
  analysis:'The screen shows <script>alert(1)</script> followed by a save dialog.',
  warnings:['<img src=x onerror=alert(1)> Audio service was unavailable.']
};
const html = ui._createToolCardHtml('analyze_video', 'success', {ok:true, data});
assert.match(html, /tool-card success expanded/);
assert.match(html, /Video analysis/);
assert.match(html, /Partial analysis/);
assert.match(html, /tool-card-status">⚠️ Partial analysis/);
assert.match(html, /Requested interval:<\/strong> 0:00–0:12.5/);
assert.match(html, /0:00, 0:02.5, 0:05, 0:07.5, 0:10, 0:12.5/);
assert.match(html, /Samples do not cover every frame/);
assert.match(html, /Sampled frames analyzed/);
assert.match(html, /Audio transcription unavailable/);
assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.doesNotMatch(html, /<script|<img|"frame_timestamps"/);
assert.match(html, /\/api\/stash\/clips\/screen\?mode=cloud/);
assert.equal((html.match(/<video /g)||[]).length, 1);
""")


def test_live_tool_card_update_uses_same_readable_video_result_as_saved_cards():
    run_browser(r"""
const ui = chat();
ui.pendingTools = {};
const body = new Element(), status = new Element(), card = new Element();
const oldPlayer = new Element('video');
body.appendChild(oldPlayer);
card.querySelector = selector => selector === '.tool-card-body' ? body : selector === '.tool-card-status' ? status : null;
sandbox.document.getElementById = id => id === 'tool-card-analyze_video_2' ? card : null;
const result = {visual_status:'unavailable', audio_status:'transcribed', partial:true, start_seconds:10, end_seconds:20, frame_timestamps:[], transcript:'Turn the blue dial clockwise.'};
ui.updateToolCard('analyze_video_2', 'analyze_video', 'success', result);
assert.equal(body.innerHTML, ui._renderVideoAnalysisResult(result));
assert.equal(oldPlayer.paused, true);
assert.match(card.className, /expanded/);
assert.equal(status.innerHTML, '⚠️ Partial analysis');
assert.match(body.innerHTML, /Visual analysis unavailable/);
assert.match(body.innerHTML, /Frames sampled:<\/strong> None/);
assert.match(body.innerHTML, /<summary>Transcript<\/summary>/);
assert.match(body.innerHTML, /Turn the blue dial clockwise/);
assert.doesNotMatch(body.innerHTML, /<video|javascript:/);
""")


def test_finishing_tool_progress_pauses_temporary_source_playback():
    run_browser(r"""
const ui = chat();
const pending = new Element(), player = new Element('video');
pending.appendChild(player);
ui.messagesContainer.querySelector = selector => selector === '.thinking-message' ? pending : null;
ui._resetProcessingPhase = () => {};
ChatUI.prototype.hideThinking.call(ui);
assert.equal(player.paused, true);
""")


def test_video_analysis_excerpts_are_bounded_and_silent_audio_status_is_explicit():
    run_browser(r"""
const ui = chat();
const html = ui._renderVideoAnalysisResult({
  visual_status:'partial', audio_status:'no_audio', partial:true,
  start_seconds:60, end_seconds:65, frame_timestamps:[60.125, 62.555],
  analysis:'a'.repeat(30000), transcript:'t'.repeat(30000), warnings:['w'.repeat(3000)]
});
assert.match(html, /1:00–1:05/);
assert.match(html, /1:00.13, 1:02.56/);
assert.match(html, /No audio track/);
assert.match(html, /Some frames analyzed/);
assert.equal((html.match(/\[excerpt truncated\]/g)||[]).length, 3);
assert.ok(html.length < 20000);
assert.equal(ui._renderVideoAnalysisResult({question:'What happens?', video:'stash://clips/one'}), null);
""")


def test_video_result_distinguishes_decoded_frames_from_successfully_analyzed_frames():
    run_browser(r"""
const ui = chat();
const data = {visual_status:'partial', audio_status:'skipped', partial:true,
  frame_timestamps:[0, 2.5, 5, 7.5, 10, 12.5], analyzed_frame_timestamps:[0, 2.5]};
let html = ui._renderVideoAnalysisResult(data);
assert.match(html, /Frames sampled:<\/strong> 0:00, 0:02.5, 0:05, 0:07.5, 0:10, 0:12.5/);
assert.match(html, /Frames analyzed:<\/strong> 0:00, 0:02.5\.<\/p>/);
html = ui._renderVideoAnalysisResult({...data, analyzed_frame_timestamps:[], visual_status:'unavailable'});
assert.match(html, /Frames analyzed:<\/strong> None\./);
html = ui._renderVideoAnalysisResult({...data, analyzed_frame_timestamps:data.frame_timestamps, visual_status:'complete'});
assert.doesNotMatch(html, /Frames analyzed:/);
""")
