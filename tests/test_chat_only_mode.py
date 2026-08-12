#!/usr/bin/env python3
"""Regression coverage for the Web UI Chat only policy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))
sys.path.insert(0, str(ROOT / "jarvis-web"))

from config_loader import config_scope, get_bool  # noqa: E402
from llm_provider import AnthropicProvider, XAIProvider  # noqa: E402
from openai_responses_adapter import build_openai_builtin_responses_tools  # noqa: E402
from orchestrator_v2 import Orchestrator  # noqa: E402
from router_v2 import LLMRouter  # noqa: E402
from server_package_utils import load_server_package  # noqa: E402

load_server_package("jarvis_web_chat_only_test", ROOT / "jarvis-web" / "server")
from jarvis_web_chat_only_test.sockets.chat import ChatHandler  # noqa: E402


class _NoToolRagRegistry:
    tools = {"search_web": object()}

    def __init__(self):
        self.find_calls = 0

    def find_tools(self, *_args, **_kwargs):
        self.find_calls += 1
        raise AssertionError("Chat only must not query Tool RAG")

    def get_tool(self, _name):
        raise AssertionError("Chat only must not resolve ghost or signaled tools")


class _ChatOnlyRecordingProvider:
    def __init__(self):
        self.calls = []

    def chat_with_tools(self, **kwargs):
        self.calls.append({
            **kwargs,
            "server_tools_disabled": get_bool("DISABLE_SERVER_SIDE_TOOLS", False),
        })
        return "Direct answer", None, None, None


class _AnthropicMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Direct answer")],
        )


class _UnexpectedToolRouter:
    provider_type = "test"
    model_name = "test-model"
    system_prompt_version = "test"
    provider = None

    def __init__(self):
        self.calls = []

    def route(self, *_args, **kwargs):
        self.calls.append(kwargs)
        return {
            "intent": "tool",
            "tool_name": "search_web",
            "arguments": {"query": "hello"},
            "available_tools": [],
            "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


class _RejectingExecutor:
    def __init__(self):
        self.calls = 0

    def set_excluded_tools(self, _tools):
        pass

    def execute(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("Chat only must reject tool routes before execution")


class _StatusUpdater:
    def reset(self):
        pass

    def update(self, **_kwargs):
        pass

    def mark_complete(self):
        pass


def test_web_command_parser_exposes_virtual_chat_only_policy():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8')
  .split('// Global command system instance')[0];
global.fetch = async () => { throw new Error('registry loading disabled in test'); };
eval(source + '\nglobal.CommandSystem = CommandSystem;');

const commands = Object.create(global.CommandSystem.prototype);
Object.assign(commands, {
  prompts: {}, workflows: {}, maxToolHints: 5,
  tools: {search_web: {name: 'search_web', enabled: true, description: 'Search'}}
});

const suggestions = commands.getSuggestions('#chat');
if (!suggestions.some(item => item.type === 'policy' && item.name === 'chat_only')) {
  throw new Error(`Missing virtual chat-only selector: ${JSON.stringify(suggestions)}`);
}

const parsed = commands.parseInput('#chat_only Explain this #search_web');
if (parsed.toolPolicy !== 'none' || parsed.message !== 'Explain this'
    || JSON.stringify(parsed.toolHints) !== JSON.stringify(['search_web'])) {
  throw new Error(`Unexpected parsed policy: ${JSON.stringify(parsed)}`);
}

const badge = commands.getPersistedDisplay({tool_policy: 'none'});
if (badge !== '#chat_only ◌') {
  throw new Error(`Unexpected persisted policy badge: ${badge}`);
}
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_web_socket_transports_only_the_recognized_policy():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/socket.js', 'utf8')
  .split('// Create global instance')[0];
global.window = {};
eval(source + '\nglobal.JarvisSocket = JarvisSocket;');

const sent = [];
const socket = Object.create(global.JarvisSocket.prototype);
Object.assign(socket, {
  connected: true,
  mode: 'cloud',
  conversationId: 'conversation-1',
  socket: {emit: (event, payload) => sent.push({event, payload})}
});
socket.sendMessage('hello', null, {tool_policy: 'none'}, true);
socket.sendMessage('hello', null, {tool_policy: 'anything-else'}, true);

if (sent[0].payload.tool_policy !== 'none') {
  throw new Error(`Chat-only policy was dropped: ${JSON.stringify(sent[0])}`);
}
if ('request_feedback' in sent[0].payload) {
  throw new Error(`Chat only transported Feedback Analysis: ${JSON.stringify(sent[0])}`);
}
if ('tool_policy' in sent[1].payload) {
  throw new Error(`Unknown policy escaped the client: ${JSON.stringify(sent[1])}`);
}
if (sent[1].payload.request_feedback !== true) {
  throw new Error(`Auto mode feedback request was dropped: ${JSON.stringify(sent[1])}`);
}
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_rejected_chat_only_sends_are_transactional_and_canvas_is_blocked():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
const chatSource = source.slice(
  source.indexOf('class ChatUI'),
  source.indexOf('// Create global instance')
);
eval(chatSource + '\nglobal.ChatUI = ChatUI;');

const toasts = [];
global.Utils = {
  autoResize: () => {},
  toast: (message) => toasts.push(message)
};
global.window = {
  jarvisSocket: {
    connected: true,
    sendMessage: () => { throw new Error('Rejected action reached the socket'); }
  }
};

const makeChat = ({parsed, hasImage = false, selected = []}) => {
  let policyMutations = 0;
  window.commandSystem = {parseInput: () => parsed};
  const chat = Object.create(global.ChatUI.prototype);
  Object.assign(chat, {
    inputField: {value: '#chat_only request', focus: () => {}},
    attachedFile: null,
    attachedPdf: null,
    selectedToolHints: [...selected],
    chatOnlyEnabled: false,
    feedbackEnabled: false,
    isProcessing: false,
    _hasAttachedImages: () => hasImage,
    _getImageAttachmentPayload: () => hasImage ? {images: [{url: 'image'}]} : null,
    _hideAutocomplete: () => {},
    _expirePendingCompletionGuardCards: () => {},
    _combineToolHints: () => [...(parsed.toolHints || [])],
    _setChatOnlyEnabled: (enabled) => {
      policyMutations += 1;
      chat.chatOnlyEnabled = enabled;
      if (enabled) chat.selectedToolHints = [];
    }
  });
  return {chat, mutations: () => policyMutations};
};

(async () => {
  const toolConflict = makeChat({
    parsed: {toolPolicy: 'none', workflow: null, toolHints: ['search_web'], message: 'request'},
    selected: ['weather']
  });
  await toolConflict.chat.sendMessage();
  if (toolConflict.mutations() !== 0 || toolConflict.chat.chatOnlyEnabled
      || JSON.stringify(toolConflict.chat.selectedToolHints) !== JSON.stringify(['weather'])) {
    throw new Error('Rejected tool conflict mutated Chat only state or selected hints');
  }

  const imageConflict = makeChat({
    parsed: {toolPolicy: 'none', workflow: null, toolHints: [], message: 'request'},
    hasImage: true
  });
  await imageConflict.chat.sendMessage();
  if (imageConflict.mutations() !== 0 || imageConflict.chat.chatOnlyEnabled) {
    throw new Error('Rejected image conflict enabled Chat only');
  }

  const emptySelector = makeChat({
    parsed: {toolPolicy: 'none', workflow: null, toolHints: [], message: ''}
  });
  emptySelector.chat.inputField.value = '#chat_only';
  await emptySelector.chat.sendMessage();
  if (emptySelector.mutations() !== 1 || !emptySelector.chat.chatOnlyEnabled) {
    throw new Error('Standalone #chat_only did not intentionally arm the sticky mode');
  }

  const canvasChat = Object.create(global.ChatUI.prototype);
  Object.assign(canvasChat, {chatOnlyEnabled: true, isProcessing: false});
  canvasChat.sendResponseToCanvas('response');
  if (!toasts.some(message => message.includes('Canvas'))) {
    throw new Error(`Canvas bypass was not blocked: ${JSON.stringify(toasts)}`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_server_tool_policy_sanitizer_defaults_to_auto():
    assert ChatHandler._sanitize_tool_policy("none") == "none"
    assert ChatHandler._sanitize_tool_policy("off") == "auto"
    assert ChatHandler._sanitize_tool_policy(None) == "auto"
    assert ChatHandler._sanitize_feedback_request(True, "none") is False
    assert ChatHandler._sanitize_feedback_request(True, "auto") is True


def test_chat_only_disables_feedback_analysis_control():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
const chatSource = source.slice(
  source.indexOf('class ChatUI'),
  source.indexOf('// Create global instance')
);
eval(chatSource + '\nglobal.ChatUI = ChatUI;');

const classes = new Set(['active']);
const feedbackBtn = {
  disabled: false,
  title: '',
  attributes: {},
  classList: {
    toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name)
  },
  setAttribute: (name, value) => { feedbackBtn.attributes[name] = value; }
};
global.document = {
  getElementById: (id) => id === 'feedbackBtn' ? feedbackBtn : null
};
const toasts = [];
global.Utils = {toast: (message) => toasts.push(message)};

const chat = Object.create(global.ChatUI.prototype);
Object.assign(chat, {
  feedbackEnabled: true,
  chatOnlyEnabled: false,
  selectedToolHints: ['search_web'],
  toolHintsContainer: null,
  ambientToolSuggestionsEl: null,
  inputField: {focus: () => {}}
});

chat._setChatOnlyEnabled(true, {focus: false});
if (chat.feedbackEnabled || !chat.chatOnlyEnabled || !feedbackBtn.disabled
    || classes.has('active') || feedbackBtn.attributes['aria-disabled'] !== 'true') {
  throw new Error('Chat only did not disable and clear Feedback Analysis');
}

chat.toggleFeedback();
if (chat.feedbackEnabled || !toasts.some(message => message.includes('Chat only'))) {
  throw new Error('Disabled Feedback Analysis was re-enabled in Chat only');
}

chat._setChatOnlyEnabled(false, {focus: false});
if (feedbackBtn.disabled || chat.feedbackEnabled || feedbackBtn.attributes['aria-disabled'] !== 'false') {
  throw new Error('Leaving Chat only did not re-enable Feedback Analysis in the off state');
}

chat.toggleFeedback();
if (!chat.feedbackEnabled || !classes.has('active')) {
  throw new Error('Feedback Analysis could not be manually enabled after Chat only');
}
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_router_chat_only_skips_rag_and_scopes_hosted_tool_suppression():
    registry = _NoToolRagRegistry()
    provider = _ChatOnlyRecordingProvider()
    router = LLMRouter.__new__(LLMRouter)
    router.mode = "cloud"
    router.registry = registry
    router.provider = provider
    router.provider_type = "anthropic"
    router.model_name = "claude-test"
    router.timezone = ZoneInfo("America/Los_Angeles")
    router.prompt_override = None
    router._system_prompt_base = "Router system"
    router._provider_override = None
    router._model_override = None
    router.system_prompt_version = "test"

    with config_scope("cloud", overrides={"TOOL_RAG_TRACE_ENABLED": "false"}):
        with patch("router_v2._log_tool_rag_trace") as trace_log, \
             patch("thinking.should_enable_thinking", return_value=False), \
             patch("llm_logger.get_logger"):
            result = router.route("Let us discuss this", tool_policy="none")

        assert get_bool("DISABLE_SERVER_SIDE_TOOLS", False) is False

    assert result["intent"] == "qa"
    assert result["available_tools"] == []
    assert registry.find_calls == 0
    assert provider.calls[0]["tools"] == []
    assert provider.calls[0]["server_tools_disabled"] is True
    assert "CHAT ONLY MODE" in provider.calls[0]["system_prompt"]
    assert trace_log.call_args.kwargs["tool_rag_skipped"] is True
    assert trace_log.call_args.kwargs["retrieval_limit"] == 0
    assert trace_log.call_args.kwargs["tool_schema_est_tokens"] == 0


def test_orchestrator_chat_only_rejects_anomalous_tool_route_before_execution():
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.executor = _RejectingExecutor()
    orchestrator.router = _UnexpectedToolRouter()
    orchestrator.status_updater = _StatusUpdater()
    orchestrator.max_retries = 0
    orchestrator.timezone = ZoneInfo("America/Los_Angeles")
    orchestrator.auto_context_enabled = False
    orchestrator._last_experience_id = None
    orchestrator.session_id = "chat-only-test"
    orchestrator.web_conversation_id = "conversation-test"
    orchestrator.progress_callback = None
    orchestrator.cancel_check = None
    orchestrator.learning_enabled = False
    orchestrator._get_relevant_memories_bundle = lambda _transcript: {"context": "", "meta": {}}
    orchestrator._get_learning_insights = lambda *_args: (_ for _ in ()).throw(
        AssertionError("Chat only must skip tool-oriented learning insights")
    )
    orchestrator._log_conversation = lambda *_args, **_kwargs: None
    orchestrator._maybe_collect_feedback = lambda result, _transcript: result

    def config_value(key, default=None):
        if key == "JARVIS_RESPONSE_STYLE":
            return "detailed"
        return default

    with patch("orchestrator_v2.get_config_value", side_effect=config_value), \
         patch("orchestrator_v2.get_int", side_effect=lambda key, default=0: 2 if key == "MAX_TOOL_TURNS" else default):
        result = orchestrator.process("hello", tool_policy="none")

    assert result["ok"] is True
    assert "No tools were run" in result["speech"]
    assert result["tools_used"] == []
    assert orchestrator.executor.calls == 0
    assert orchestrator.router.calls[0]["tool_policy"] == "none"
    assert result["routing_provenance"]["chat_only_tool_call_blocked"] == "search_web"


def test_chat_only_skips_random_feedback_collection():
    orchestrator = Orchestrator.__new__(Orchestrator)
    result = {
        "ok": True,
        "routing_provenance": {"tool_policy": "none"},
    }

    with patch("config_loader.get_config_value") as get_config:
        returned = orchestrator._maybe_collect_feedback(result, "hello")

    assert returned is result
    get_config.assert_not_called()


def test_unified_hosted_tool_switch_covers_openai_xai_and_anthropic():
    overrides = {
        "DISABLE_SERVER_SIDE_TOOLS": "true",
        "OPENAI_RESPONSES_SERVER_SIDE_TOOLS": "true",
        "OPENAI_RESPONSES_WEB_SEARCH": "true",
    }
    with config_scope("cloud", overrides=overrides):
        assert build_openai_builtin_responses_tools() == []

        xai = XAIProvider.__new__(XAIProvider)
        assert xai._build_xai_server_tools() == []

        anthropic = AnthropicProvider.__new__(AnthropicProvider)
        anthropic.enable_search = True
        anthropic.model = "claude-test"
        messages_api = _AnthropicMessages()
        anthropic.client = SimpleNamespace(messages=messages_api)
        text, tool_call, _usage, _thinking = anthropic.chat_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            system_prompt="System",
        )

    assert text == "Direct answer"
    assert tool_call is None
    assert "tools" not in messages_api.calls[0]
