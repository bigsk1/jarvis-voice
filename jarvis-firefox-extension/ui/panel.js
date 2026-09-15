import { normalizeServerUrl, originPermission } from '../core/connection.js';
import { DEFAULT_SCREENSHOT_PROMPT, DraftBuffer, canSend, displayTime, imageContextHint, isBusy, isRunActive, noticeText, notificationPreferences, safePreviewUrl } from './view-model.js';
import { renderMessage } from './render.js';

const $ = id => document.getElementById(id);
const draft = new DraftBuffer();
let state = null;
let port = null;
let draftTimer = null;
let reconnectTimer = null;
let keepAliveTimer = null;
let busyCount = 0;
let localError = '';
let messagesKey = '';
let historyKey = '';
let settingsDirty = false;
let initialized = false;
let sending = false;
let configurationBusy = false;
let closing = false;
let preferencesBusy = false;
let preferencesNotice = '';
let lastViewStatusKey = '';

const notificationHelp = 'Notifications use a generic message unless you enable previews. Previews may appear on your lock screen.';

const labels = {
  unconfigured: 'Set up', disconnected: 'Offline', connecting: 'Connecting',
  connected: 'Connected', auth_required: 'Sign in', error: 'Offline', recovering: 'Restoring',
};

function openDrawer(name, open = true) {
  for (const drawer of ['settings', 'history']) {
    const visible = drawer === name && open;
    $(`${drawer}-panel`).hidden = !visible;
    $(`${drawer}-button`).setAttribute('aria-expanded', String(visible));
  }
  if (name === 'settings' && open) {
    if (state?.connection?.status === 'auth_required') $('password').focus();
    else $('server-url').focus();
  }
}

function resizeInput() {
  const input = $('message-input');
  input.style.height = 'auto';
  input.style.height = `${Math.min(150, Math.max(48, input.scrollHeight))}px`;
}

function updateDraftInput() {
  if ($('message-input').value !== draft.value) {
    $('message-input').value = draft.value;
    resizeInput();
  }
}

function renderControls() {
  const active = isRunActive(state);
  const busy = isBusy(state);
  $('send-button').disabled = sending || configurationBusy || !canSend(state, draft.value);
  $('send-button').title = state?.pendingMode ? 'Waiting for Jarvis to confirm the mode change.' : active ? 'Wait for this reply or stop the current request.' : state?.connection?.status !== 'connected' ? 'Connect to Jarvis to send a message.' : 'Send message';
  $('analyze-button').disabled = sending || configurationBusy || !canSend(state, DEFAULT_SCREENSHOT_PROMPT) || !state?.draft?.attachment;
  for (const id of ['capture-button', 'recapture-button', 'empty-capture', 'remove-attachment', 'remove-context']) $(id).disabled = busyCount > 0 || sending || busy;
  $('mode-select').disabled = busy || configurationBusy || sending;
  $('new-conversation').disabled = busy || sending;
  $('history-button').disabled = Boolean(state?.pendingMode);
  $('cancel-button').disabled = !active || !state?.run?.conversationId || state?.connection?.status !== 'connected' || ['stopping', 'cancelling', 'cancel_requested'].includes(state?.run?.status);
  $('cancel-button').textContent = ['stopping', 'cancelling', 'cancel_requested'].includes(state?.run?.status) ? 'Stopping…' : 'Stop';
  $('save-settings').disabled = configurationBusy || busy;
  $('login-button').disabled = configurationBusy;
  $('logout-button').disabled = configurationBusy || busy;
  $('reconnect-button').disabled = configurationBusy || ['connecting', 'recovering'].includes(state?.connection?.status);
  $('refresh-history').disabled = state?.connection?.status !== 'connected' || Boolean(state?.pendingMode);
  $('message-input').placeholder = state?.draft?.attachment ? 'Ask about this screenshot…' : state?.draft?.context?.kind === 'image' ? 'Ask about this image…' : state?.draft?.context ? 'Ask about this page or selection…' : 'Ask Jarvis anything…';
}

function renderPreferences() {
  const preferences = notificationPreferences(state?.settings?.preferences);
  if (!preferencesBusy) {
    $('show-badge').checked = preferences.showBadge;
    $('desktop-notifications').checked = preferences.desktopNotifications;
    $('notification-preview').checked = preferences.notificationPreview;
  }
  $('show-badge').disabled = preferencesBusy;
  $('desktop-notifications').disabled = preferencesBusy;
  $('notification-preview').disabled = preferencesBusy || !preferences.desktopNotifications;
  $('notification-help').textContent = preferencesBusy ? 'Saving notification preferences…' : preferencesNotice || notificationHelp;
  $('notification-help').dataset.error = String(Boolean(preferencesNotice));
}

async function updatePreference(name, value) {
  if (preferencesBusy) return;
  preferencesBusy = true;
  preferencesNotice = '';
  renderPreferences();
  try {
    // Firefox requires this request to remain in the checkbox's user gesture.
    if (name === 'desktopNotifications' && value) {
      const granted = await browser.permissions.request({permissions: ['notifications']});
      if (!granted) throw new Error('Notifications were not allowed. Enable them again to grant Firefox permission.');
    }
    const result = await command('updatePreferences', {[name]: value});
    if (!result.ok) preferencesNotice = result.error || 'Notification preferences could not be saved.';
  } catch (error) {
    preferencesNotice = error?.message || 'Notification preferences could not be saved.';
  } finally {
    preferencesBusy = false;
    renderPreferences();
  }
}

function renderNotice() {
  const text = localError || state?.connection?.error || noticeText(state?.notice);
  $('notice').hidden = !text;
  $('notice').textContent = text || '';
  $('notice').dataset.error = String(Boolean(localError || state?.connection?.error));
}

function renderConnection() {
  const status = state?.connection?.status || 'unconfigured';
  $('connection-badge').dataset.status = status;
  $('connection-label').textContent = status === 'recovering' && sending ? 'Sending' : labels[status] || status;
  $('connection-badge').title = state?.settings?.serverUrl || 'Set up your Jarvis connection';
  if (!settingsDirty) {
    $('server-url').value = state?.settings?.serverUrl || '';
    $('allow-insecure').checked = Boolean(state?.settings?.allowInsecureLocal);
  }
  $('insecure-warning').hidden = !$('allow-insecure').checked;
  $('login-form').hidden = status !== 'auth_required';
  $('logout-button').hidden = status !== 'connected' || !state?.connection?.authRequired;
  $('reconnect-button').hidden = !state?.settings?.serverUrl || !['disconnected', 'error'].includes(status);
  const statusText = {
    unconfigured: 'Set a server address to get started.',
    disconnected: 'Saved. Connect when you are ready.',
    connecting: 'Checking the server…',
    connected: 'Connected to your Jarvis Web server.',
    auth_required: 'Your server requires the Jarvis Web password.',
    error: state?.connection?.error || 'Could not connect. Check the server address.',
    recovering: sending ? 'Preparing your message…' : 'Restoring your conversation and checking the previous request…',
  };
  $('settings-status').textContent = statusText[status] || '';
}

function renderMessages() {
  const list = Array.isArray(state?.messages) ? state.messages : [];
  // Progress updates must not rebuild selectable reply text or steal focus.
  const key = JSON.stringify([state?.conversationId, list]);
  if (key !== messagesKey) {
    const thread = $('thread');
    const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 100;
    const wasEmpty = $('messages').childElementCount === 0;
    messagesKey = key;
    $('messages').replaceChildren(...list.map(message => renderMessage(document, message)));
    $('empty-state').hidden = list.length > 0;
    if (nearBottom || wasEmpty) thread.scrollTop = thread.scrollHeight;
  }
  const conversation = state?.conversations?.find(item => item.id === state?.conversationId);
  $('thread-title').textContent = conversation?.title || (state?.conversationId ? 'Conversation with Jarvis' : 'New conversation');
}

function renderHistory() {
  const list = state?.conversations || [];
  const active = isBusy(state);
  const key = JSON.stringify([list, state?.conversationId, active, state?.connection?.status]);
  if (key === historyKey) return;
  historyKey = key;
  const container = $('conversation-list');
  const children = list.map(conversation => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'conversation-item';
    button.setAttribute('aria-current', String(conversation.id === state?.conversationId));
    button.disabled = active || state?.connection?.status !== 'connected';
    const title = document.createElement('strong');
    title.textContent = conversation.title || 'Untitled conversation';
    const heading = document.createElement('div');
    heading.className = 'conversation-item-heading';
    heading.append(title);
    if (conversation.pinned === true) {
      const pin = document.createElement('span');
      pin.className = 'conversation-pin';
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('viewBox', '0 0 24 24');
      icon.setAttribute('aria-hidden', 'true');
      icon.setAttribute('focusable', 'false');
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'm15 4 5 5-3 1-4 4v4l-2-2-5 5m5-5-3-3H4l4-4 4-1z');
      icon.append(path);
      const label = document.createElement('span');
      label.textContent = 'Pinned';
      pin.append(icon, label);
      heading.append(pin);
    }
    const time = document.createElement('time');
    time.textContent = displayTime(conversation.updated_at || conversation.created_at, true);
    button.append(heading, time);
    button.addEventListener('click', () => changeConversation('loadConversation', { conversationId: conversation.id }));
    return button;
  });
  if (!children.length) {
    const empty = document.createElement('p');
    empty.className = 'helper';
    empty.textContent = state?.connection?.status === 'connected' ? 'No conversations yet. Your next message starts one.' : 'Connect to load your conversations.';
    children.push(empty);
  }
  container.replaceChildren(...children);
}

function renderAttachments() {
  const attachment = state?.draft?.attachment;
  const preview = safePreviewUrl(attachment?.previewUrl);
  $('attachment-panel').hidden = !attachment;
  $('preview-button').disabled = !preview;
  if (preview && $('attachment-preview').getAttribute('src') !== preview) $('attachment-preview').src = preview;
  if (!preview) $('attachment-preview').removeAttribute('src');
  $('attachment-title').textContent = attachment?.source?.title || 'Browser view';
  $('attachment-title').title = attachment?.source?.url || '';
  const dimensions = attachment?.width && attachment?.height ? `${attachment.width} × ${attachment.height}` : '';
  const captured = displayTime(attachment?.capturedAt);
  $('attachment-meta').textContent = [dimensions, captured ? `Captured ${captured}` : 'Ready to send'].filter(Boolean).join(' · ');
  const context = state?.draft?.context;
  $('context-panel').hidden = !context;
  $('context-panel').setAttribute('aria-label', context?.kind === 'image' ? 'Shared image URL' : 'Shared page context');
  $('context-title').textContent = context?.kind === 'image' ? 'Image URL' : context?.title || 'Shared from Firefox';
  $('context-text').textContent = context?.kind === 'image' ? context?.url || '' : context?.text || context?.url || '';
  $('context-title').title = context?.url || '';
  const hint = imageContextHint(context, draft.value);
  $('context-hint').textContent = hint;
  $('context-hint').hidden = !hint;
  $('source-caption').textContent = attachment ? 'Capture again when the page changes.' : 'Capture adds a preview to your next message.';
}

function renderProgress() {
  const active = isRunActive(state);
  $('progress-area').hidden = !active && !state?.pendingMode;
  $('cancel-button').hidden = !active;
  const latest = (state?.progress || []).at(-1);
  const defaultText = state?.connection?.status === 'recovering' ? 'Restoring the current request…' : 'Jarvis is working…';
  $('progress-text').textContent = state?.pendingMode ? `Switching to ${state.pendingMode === 'local' ? 'Local' : 'Cloud'}…` : sending ? noticeText(state?.notice) || 'Sending your message…' : latest?.text || state?.run?.text || latest?.tool || defaultText;
  $('progress-text').title = $('progress-text').textContent;
}

function renderState(next, forceDraft = false) {
  if (!next) return;
  const previousStatus = state?.connection?.status;
  const previousImageStage = state?.draft?.context?.stageId;
  state = next;
  const context = state.draft?.context;
  const newImageStage = context?.kind === 'image' && context.stageId && context.stageId !== previousImageStage;
  let syncImageDraft = false;
  if (newImageStage && draft.dirty && !forceDraft) {
    // A menu action may arrive before the previous typing debounce was saved.
    // Keep the local question and add the image that was explicitly staged.
    cancelDraftTimer();
    try { draft.mergeImage(context); syncImageDraft = true; }
    catch (error) { localError = error.message; }
  }
  draft.accept(state.draft?.text, forceDraft);
  if (syncImageDraft && draft.dirty) scheduleDraft();
  updateDraftInput();
  $('mode-select').value = state.pendingMode || state.mode || 'cloud';
  renderConnection();
  renderPreferences();
  renderMessages();
  renderHistory();
  renderAttachments();
  renderProgress();
  renderControls();
  renderNotice();
  if ((!initialized && ['unconfigured', 'auth_required'].includes(state.connection?.status))
      || (state.connection?.status === 'auth_required' && previousStatus !== 'auth_required')) openDrawer('settings');
  initialized = true;
  sendViewStatus();
}

function sendViewStatus() {
  if (closing || !port) return;
  const status = {
    type: 'viewStatus', visible: !document.hidden && document.hasFocus(),
    conversationId: state?.conversationId || null,
  };
  const key = JSON.stringify(status);
  if (key === lastViewStatusKey) return;
  try { port.postMessage(status); lastViewStatusKey = key; }
  catch { /* The port disconnect handler restores the bridge. */ }
}

function draftScopeKey() {
  return JSON.stringify([state?.settings?.serverUrl, state?.conversationId, state?.mode,
    state?.draft?.context?.stageId || null]);
}

async function command(action, payload = {}, options = {}) {
  const scope = draftScopeKey();
  if (action === 'setDraft') payload = {...payload, imageStageId: state?.draft?.context?.stageId || null};
  if (!options.quiet) { localError = ''; renderNotice(); }
  try {
    const result = await browser.runtime.sendMessage({ type: 'jarvis:command', action, payload });
    // The port may already have delivered a new stage or conversation while a
    // prior draft command's acknowledgment was still crossing the bridge.
    const staleDraft = action === 'setDraft' && scope !== draftScopeKey();
    if (!result?.ok) {
      if (result?.state && !staleDraft) renderState(result.state);
      throw new Error(result?.error || 'Jarvis could not complete this action.');
    }
    if (options.beforeRender) options.beforeRender(result.state);
    if (result.state && !staleDraft) renderState(result.state, options.forceDraft);
    return result;
  } catch (error) {
    localError = error?.message || String(error);
    renderNotice();
    return { ok: false, error: localError };
  }
}

function cancelDraftTimer() { clearTimeout(draftTimer); draftTimer = null; }

function scheduleDraft() {
  cancelDraftTimer();
  if (sending) return;
  draftTimer = setTimeout(() => { draftTimer = null; void command('setDraft', { text: draft.value }, { quiet: true }); }, 250);
}

async function send(text) {
  if (sending || !canSend(state, text)) return;
  cancelDraftTimer();
  sending = true;
  draft.dirty = true;
  renderControls();
  const submittedDraft = draft.value;
  await command('send', { text }, { beforeRender: next => draft.sent(submittedDraft, next?.draft?.text || '') });
  sending = false;
  if (draft.dirty) scheduleDraft();
  renderControls();
  updateDraftInput();
  $('message-input').focus();
}

async function capture() {
  busyCount += 1;
  renderControls();
  try {
    const viewWindow = await browser.windows.getCurrent();
    // A sidebar targets its own window. A pop-out targets the most recently
    // used normal browser window, never its own extension window.
    await command('capture', {windowId: viewWindow.type === 'normal' ? viewWindow.id : null});
  } catch (error) { localError = error.message; renderNotice(); }
  busyCount -= 1;
  renderControls();
  $('message-input').focus();
}

async function changeConversation(action, payload = {}) {
  if (isBusy(state) || sending) return;
  cancelDraftTimer();
  const result = await command(action, payload, { forceDraft: true });
  if (result.ok) { openDrawer('history', false); $('message-input').focus(); }
}

function subscribe() {
  clearTimeout(reconnectTimer);
  clearInterval(keepAliveTimer);
  try {
    port = browser.runtime.connect({ name: 'jarvis-ui' });
    lastViewStatusKey = '';
    const connectedPort = port;
    const ping = () => {
      if (closing || port !== connectedPort) return;
      try { connectedPort.postMessage({type: 'ping'}); }
      catch { connectedPort.disconnect(); }
    };
    port.onMessage.addListener(message => { if (message?.type === 'state') renderState(message.state); });
    port.onDisconnect.addListener(() => {
      if (closing || port !== connectedPort) return;
      clearInterval(keepAliveTimer);
      localError = 'Reconnecting to the extension…';
      // The last server snapshot is stale until the background bridge returns.
      if (state) renderState({...state, connection: {...state.connection, status: 'recovering'}});
      else renderNotice();
      reconnectTimer = setTimeout(subscribe, 1000);
    });
    keepAliveTimer = setInterval(ping, 10000);
    ping();
    sendViewStatus();
    const snapshotScope = draftScopeKey();
    void browser.runtime.sendMessage({ type: 'jarvis:state' }).then(response => {
      const next = response?.state || (response?.settings ? response : null);
      if (next && snapshotScope === draftScopeKey()) { localError = ''; renderState(next); }
    }).catch(error => { localError = error.message; renderNotice(); });
  } catch (error) {
    localError = error.message;
    if (state) renderState({...state, connection: {...state.connection, status: 'recovering'}});
    else renderNotice();
    reconnectTimer = setTimeout(subscribe, 1000);
  }
}

$('settings-button').addEventListener('click', () => openDrawer('settings', $('settings-panel').hidden));
$('popout-button').addEventListener('click', () => command('openPopout'));
$('settings-close').addEventListener('click', () => openDrawer('settings', false));
$('history-button').addEventListener('click', async () => {
  const open = $('history-panel').hidden;
  openDrawer('history', open);
  if (open && state?.connection?.status === 'connected') await command('listConversations');
});
$('history-close').addEventListener('click', () => openDrawer('history', false));
$('refresh-history').addEventListener('click', () => command('listConversations'));
$('new-conversation').addEventListener('click', () => changeConversation('newConversation'));
$('server-url').addEventListener('input', () => { settingsDirty = true; });
$('allow-insecure').addEventListener('change', () => { settingsDirty = true; $('insecure-warning').hidden = !$('allow-insecure').checked; });
for (const [id, name] of [['show-badge', 'showBadge'], ['desktop-notifications', 'desktopNotifications'], ['notification-preview', 'notificationPreview']]) {
  $(id).addEventListener('change', () => updatePreference(name, $(id).checked));
}

$('settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (configurationBusy || isBusy(state)) return;
  configurationBusy = true;
  renderControls();
  try {
    const allowInsecureLocal = $('allow-insecure').checked;
    const serverUrl = normalizeServerUrl($('server-url').value, { allowInsecureLocal });
    // This must stay directly in the submit gesture for Firefox permissions.
    const granted = await browser.permissions.request({ origins: [originPermission(serverUrl)] });
    if (!granted) throw new Error('Server access was not granted. Connect again to allow access to this server.');
    const configured = await command('configure', { serverUrl, allowInsecureLocal }, { forceDraft: true });
    if (configured.ok) {
      settingsDirty = false;
      $('password').value = '';
      await command('connect');
      if (state?.connection?.status === 'connected') openDrawer('settings', false);
    }
  } catch (error) { localError = error.message; renderNotice(); }
  configurationBusy = false;
  renderConnection();
  renderControls();
});

$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (configurationBusy) return;
  const password = $('password').value;
  if (!password) { $('password').focus(); return; }
  configurationBusy = true;
  $('password').value = '';
  renderControls();
  const result = await command('login', { password });
  configurationBusy = false;
  renderControls();
  if (result.ok && state?.connection?.status === 'connected') { openDrawer('settings', false); $('message-input').focus(); }
});
$('logout-button').addEventListener('click', async () => { $('password').value = ''; await command('logout', {}, { forceDraft: true }); });
$('reconnect-button').addEventListener('click', () => command('connect'));
$('mode-select').addEventListener('change', async () => {
  if (isBusy(state)) return;
  const requestedMode = $('mode-select').value;
  cancelDraftTimer();
  if (draft.dirty) await command('setDraft', { text: draft.value }, { quiet: true });
  await command('setMode', { mode: requestedMode });
  $('mode-select').value = state?.pendingMode || state?.mode || 'cloud';
});
$('message-input').addEventListener('input', () => { draft.edit($('message-input').value); resizeInput(); renderControls(); renderAttachments(); scheduleDraft(); });
$('message-input').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void send(draft.value); }
});
$('composer-form').addEventListener('submit', event => { event.preventDefault(); void send(draft.value); });
for (const id of ['capture-button', 'recapture-button', 'empty-capture']) $(id).addEventListener('click', capture);
$('analyze-button').addEventListener('click', () => send(draft.value.trim() || DEFAULT_SCREENSHOT_PROMPT));
$('remove-attachment').addEventListener('click', () => command('removeAttachment'));
$('remove-context').addEventListener('click', () => command('removeAttachment'));
$('cancel-button').addEventListener('click', () => command('cancel'));
$('preview-button').addEventListener('click', () => {
  const preview = safePreviewUrl(state?.draft?.attachment?.previewUrl);
  if (!preview) return;
  $('large-preview').src = preview;
  $('preview-dialog').showModal();
});
$('close-preview').addEventListener('click', () => $('preview-dialog').close());
$('preview-dialog').addEventListener('close', () => $('large-preview').removeAttribute('src'));
window.addEventListener('focus', sendViewStatus);
window.addEventListener('blur', sendViewStatus);
document.addEventListener('visibilitychange', sendViewStatus);
window.addEventListener('pagehide', () => {
  closing = true;
  cancelDraftTimer();
  clearTimeout(reconnectTimer);
  clearInterval(keepAliveTimer);
  if (draft.dirty) void browser.runtime.sendMessage({ type: 'jarvis:command', action: 'setDraft', payload: {
    text: draft.value, imageStageId: state?.draft?.context?.stageId || null,
  } }).catch(() => {});
  port?.disconnect();
});

renderControls();
subscribe();
