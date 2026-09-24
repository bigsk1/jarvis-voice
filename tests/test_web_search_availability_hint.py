"""Web search availability is a prompt hint, not a routing preference."""

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from config_loader import config_scope  # noqa: E402
from router_v2 import LLMRouter, ProviderRouteInput, _web_search_availability_hint  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402


def _tool(name, *, web_search=False, enabled=True):
    return ToolSchema(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        script_path=f"{name}.py",
        permissions={"enabled": enabled},
        web_search=web_search,
    )


class _Registry:
    def __init__(self):
        self.tools = {
            tool.name: tool for tool in [
                _tool("tool_search"),
                _tool("tavily_search", web_search=True),
                _tool("mcp_brave_search_brave_web_search", web_search=True),
                _tool("blocked_search", web_search=True),
                _tool("disabled_search", web_search=True, enabled=False),
                _tool("crawl_url"),
            ]
        }
        self.last_tool_search_meta = {}

    def find_tools(self, *_args, **_kwargs):
        return [self.tools["tool_search"], self.tools["tavily_search"]]

    def get_tool(self, name):
        return self.tools.get(name)


class _Provider:
    def __init__(self):
        self.calls = []

    def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return "Answer", None, None, None


def test_manifest_boolean_is_read_and_absence_is_false():
    assert ToolSchema.from_json_file(str(ROOT / "skills/tavily_search.tool.json")).web_search
    assert not ToolSchema.from_json_file(str(ROOT / "skills/crawl_url.tool.json")).web_search


def test_hint_uses_only_callable_unblocked_search_tools():
    registry = _Registry()
    hint = _web_search_availability_hint(registry, {"blocked_search"})

    assert "mcp_brave_search_brave_web_search" in hint
    assert "tavily_search" in hint
    assert "blocked_search" not in hint
    assert "disabled_search" not in hint
    assert "crawl_url" not in hint
    assert "Local web search tools" in hint
    assert "separate from provider-native search" in hint
    assert "Use only if relevant" in hint
    assert _web_search_availability_hint(registry, {"tool_search"}) == ""


def test_router_sends_hint_without_adding_search_schemas_or_chat_only_tools():
    router = LLMRouter.__new__(LLMRouter)
    router.mode = "cloud"
    router.registry = _Registry()
    router.provider = _Provider()
    router.provider_type = "test"
    router.model_name = "test-model"
    router.system_prompt_version = "test"
    route_input = ProviderRouteInput(
        tool_retrieval_query="Research this",
        messages=[{"role": "user", "content": "Research this"}],
        system_prompt="Base policy",
    )

    with config_scope("cloud", overrides={"TOOL_RAG_TRACE_ENABLED": "false"}), \
         patch("router_v2._log_tool_rag_trace"), \
         patch("thinking.should_enable_thinking", return_value=False), \
         patch("llm_logger.get_logger"):
        result = router.route(route_input, excluded_tools=["blocked_search"])
        chat_only = router.route(route_input, tool_policy="none")

    assert result["intent"] == "qa"
    assert result["web_search_hint_tools"] == [
        "mcp_brave_search_brave_web_search", "tavily_search"
    ]
    call = router.provider.calls[0]
    assert "mcp_brave_search_brave_web_search" in call["system_prompt"]
    assert "mcp_brave_search_brave_web_search" not in [tool["function"]["name"] for tool in call["tools"]]
    assert "blocked_search" not in call["system_prompt"]
    assert chat_only["intent"] == "qa"
    assert chat_only["web_search_hint_tools"] == []
    assert "Local web search tools" not in router.provider.calls[1]["system_prompt"]
    assert router.provider.calls[1]["tools"] == []
