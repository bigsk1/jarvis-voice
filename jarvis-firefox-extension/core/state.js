export const ACTIVE_STATUSES = new Set(['sending', 'running', 'stopping', 'recovering']);
export const DEFAULT_PREFERENCES = Object.freeze({showBadge: true, desktopNotifications: false, notificationPreview: false});

export function normalizePreferences(preferences = {}) {
  return Object.fromEntries(Object.entries(DEFAULT_PREFERENCES).map(([key, fallback]) =>
    [key, typeof preferences?.[key] === 'boolean' ? preferences[key] : fallback]));
}

export function mergeImageStageText(text, context) {
  const draft = String(text || '');
  const merged = draft.includes(context.url) ? draft :
    `${draft}${draft.trim() ? '\n\n' : ''}Analyze this image:\n${context.url}`;
  if (merged.length > 32000) throw new Error('The draft is too long to add this image URL. Shorten it and try again.');
  return merged;
}

export function submittedRequests(requests) {
  return (Array.isArray(requests) ? requests : []).slice(-64).filter(request =>
    typeof request?.requestId === 'string' && request.requestId.length <= 150).map(request => ({
    requestId: request.requestId,
    conversationId: typeof request.conversationId === 'string' ? request.conversationId.slice(0, 150) : null,
    mode: request.mode === 'local' ? 'local' : 'cloud',
    startedAt: typeof request.startedAt === 'string' ? request.startedAt.slice(0, 40) : '',
    status: typeof request.status === 'string' ? request.status.slice(0, 30) : 'sending',
  }));
}

export function initialState(settings = {}) {
  return {
    settings: {serverUrl: '', allowInsecureLocal: false, ...settings, preferences: normalizePreferences(settings.preferences)},
    connection: {status: 'unconfigured', authRequired: false, error: null},
    source: null, conversationId: null, conversations: [], messages: [],
    draft: {text: '', attachment: null, context: null, page: null}, run: null, progress: [],
    mode: 'cloud', notice: null, submittedRequests: [], capabilities: {text: null, profile: false}, profile: null,
  };
}

export function publicRun(run) {
  if (!run || !run.message_id && !run.messageId) return null;
  return {
    requestId: run.requestId || run.message_id || run.messageId,
    messageId: run.message_id || run.messageId,
    conversationId: run.conversation_id || run.conversationId,
    status: run.status,
    text: run.status_text || run.error || '',
  };
}

export function savedMessages(messages) {
  return (Array.isArray(messages) ? messages : []).slice(-100).map((message, index) => ({
    id: String(message.role === 'assistant' && message.data?._web_message_id ? `assistant-${message.data._web_message_id}` :
      message.role === 'user' && message.data?._request_id ? `user-${message.data._request_id}` : message.id || `saved-${index}`),
    role: message.role === 'user' ? 'user' : 'assistant',
    content: String(message.content ?? message.text ?? '').slice(0, 80000),
    createdAt: message.timestamp || message.created_at || '',
    attachments: [
      ...(message.data?.image_url || message.data?.image_urls?.length ? [{label: 'Screenshot / image'}] : []),
      ...((Array.isArray(message.data?.attachments) ? message.data.attachments : [])
        .filter(item => item?.kind === 'text')
        .slice(0, 4)
        .map(item => ({label: String(item.filename || 'Page text').slice(0, 80)}))),
    ],
  }));
}

export function checkpointState(state) {
  // Conversations are authoritative on the server. Keep bounded text for an
  // offline view and only the one unsent screenshot, below storage.session's cap.
  return {
    ...state,
    // Reload private appearance from the authenticated server after reconnect.
    profile: null,
    submittedRequests: submittedRequests(state.submittedRequests),
    conversations: state.conversations.slice(0, 100),
    messages: state.messages.slice(-50).map(message => ({
      ...message, content: String(message.content).slice(0, 12000),
      attachments: (message.attachments || []).map(item => ({
        label: String(item?.label || 'Screenshot / image').slice(0, 80),
      })),
    })),
    progress: state.progress.slice(-20),
  };
}
