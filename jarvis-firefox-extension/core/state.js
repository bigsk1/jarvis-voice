export const ACTIVE_STATUSES = new Set(['sending', 'running', 'stopping', 'recovering']);

export function initialState(settings = {}) {
  return {
    settings: {serverUrl: '', allowInsecureLocal: false, ...settings},
    connection: {status: 'unconfigured', authRequired: false, error: null},
    source: null, conversationId: null, conversations: [], messages: [],
    draft: {text: '', attachment: null, context: null}, run: null, progress: [],
    mode: 'cloud', notice: null,
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
    attachments: message.data?.image_url || message.data?.image_urls?.length ? [{label: 'Screenshot / image'}] : [],
  }));
}

export function checkpointState(state) {
  // Conversations are authoritative on the server. Keep bounded text for an
  // offline view and only the one unsent screenshot, below storage.session's cap.
  return {
    ...state,
    conversations: state.conversations.slice(0, 100),
    messages: state.messages.slice(-50).map(message => ({
      ...message, content: String(message.content).slice(0, 12000),
      attachments: (message.attachments || []).map(() => ({label: 'Screenshot / image'})),
    })),
    progress: state.progress.slice(-20),
  };
}
