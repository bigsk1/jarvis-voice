"""Project NOMAD opt-in tool, response bounds, and chat/UI contracts."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import project_nomad  # noqa: E402
from project_nomad_context import project_nomad_data  # noqa: E402
from tool_child_environment import restrict_child_environment  # noqa: E402
from tool_schema import ToolSchema  # noqa: E402


class Response:
    def __init__(self, payload, *, status=200, headers=None):
        self.content = json.dumps(payload).encode()
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def close(self):
        pass


def _setup(monkeypatch, responses, config=None):
    values = {"PROJECT_NOMAD_BASE_URL": "http://nomad.example.test:8080/api/",
              "PROJECT_NOMAD_MODEL": "gemma4:12b"}
    values.update(config or {})
    monkeypatch.setattr(project_nomad, "get_config_value", lambda name, default="": values.get(name, default))
    session = Session(responses)
    monkeypatch.setattr(project_nomad.requests, "Session", lambda: session)
    return session


def test_ask_uses_only_nomad_chat_route_and_does_not_save_session(monkeypatch):
    session = _setup(monkeypatch, [Response({"message": {"content": "Use stored water safely."}})])
    result = project_nomad.run({"action": "ask", "question": "Water?"})
    assert result["ok"] is True
    assert result["data"]["answer"] == "Use stored water safely."
    assert result["data"]["grounding_status"] == "unverified"
    assert "no verifiable source passages" in result["data"]["evidence_note"]
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", "http://nomad.example.test:8080/api/ollama/chat")
    assert kwargs["params"] is None
    assert kwargs["json"] == {
        "model": "gemma4:12b", "messages": [{"role": "user", "content": "Water?"}],
        "stream": False, "think": False,
    }
    assert "sessionId" not in kwargs["json"]
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert session.trust_env is False


def test_ask_requires_a_real_named_collection_when_scoped(monkeypatch):
    session = _setup(monkeypatch, [
        Response({"collections": []}),
    ])
    with pytest.raises(project_nomad.NomadError, match="Leave collection unset"):
        project_nomad.run({"action": "ask", "question": "Recipes?", "collection": "cookbook"})
    assert [call[1].rsplit("/", 1)[-1] for call in session.calls] == ["collections"]

    session = _setup(monkeypatch, [
        Response({"collections": [{"name": "Field Notes"}]}),
        Response({"message": {"content": "Verified only as a model answer."}}),
    ])
    result = project_nomad.run({"action": "ask", "question": "Water?", "collection": "Field Notes"})
    assert result["data"]["collection"] == "Field Notes"
    assert session.calls[1][2]["params"] == {"collection": "Field Notes"}


def test_file_inventory_is_bounded_and_reports_full_count(monkeypatch):
    files = [{"source": f"archive/{i}.md", "fileName": f"{i}.md", "state": "completed",
              "collection": "Field", "chunksEmbedded": i, "size": 100 + i,
              "isUserUpload": True}
             for i in range(45)]
    session = _setup(monkeypatch, [Response({"files": files})])
    result = project_nomad.run({"action": "files", "offset": 20, "limit": 5})
    data = result["data"]
    assert data["total"] == 45
    assert data["has_more"] is True
    assert data["inventory"]["total_files"] == 45
    assert data["inventory"]["files_with_chunks"] == 44
    assert data["inventory"]["reported_embedded_chunks"] == sum(range(45))
    assert data["inventory"]["unassigned_files"] == 0
    assert data["inventory"]["states"]["other"] == 45
    assert "Do not infer the full inventory from this page" in result["speech"]
    assert [row["source"] for row in data["files"]] == [f"archive/{i}.md" for i in range(20, 25)]
    assert all(row["viewable_text"] for row in data["files"])
    assert len(session.calls) == 1
    assert session.calls[0][1].endswith("/api/rag/files")


def test_file_name_query_keeps_whole_inventory_counts(monkeypatch):
    files = [
        {"source": "/zim/based.cooking.zim", "fileName": "based.cooking.zim",
         "state": "indexed", "chunksEmbedded": 1389, "collection": None},
        {"source": "/zim/cooking.stackexchange.zim", "fileName": "cooking.stackexchange.zim",
         "state": "pending_decision", "chunksEmbedded": 0, "collection": None},
        {"source": "/zim/woodworking.zim", "fileName": "woodworking.zim",
         "state": "indexed", "chunksEmbedded": 26123, "collection": None},
    ]
    _setup(monkeypatch, [Response({"files": files})])
    data = project_nomad.run({"action": "files", "query": "COOKING"})["data"]
    assert data["total"] == 2
    assert [row["file_name"] for row in data["files"]] == [
        "based.cooking.zim", "cooking.stackexchange.zim",
    ]
    assert data["inventory"]["total_files"] == 3
    assert data["inventory"]["files_with_chunks"] == 2
    assert data["inventory"]["states"]["pending_decision"] == 1
    assert data["inventory"]["unassigned_files"] == 3
    assert data["inventory"]["reported_embedded_chunks"] == 27512


def test_read_file_accepts_only_exact_listed_source_and_pages_text(monkeypatch):
    session = _setup(monkeypatch, [
        Response({"files": [{"source": "archive/field.md", "fileName": "field.md", "isUserUpload": True}]}),
        Response({"content": "abcdef"}),
    ])
    result = project_nomad.run({"action": "read_file", "source": "archive/field.md", "start_char": 2})
    assert result["data"]["text"] == "cdef"
    assert result["data"]["next_start_char"] is None
    assert session.calls[1][1].endswith("/api/rag/files/content")
    assert session.calls[1][2]["params"] == {"source": "archive/field.md"}

    session = _setup(monkeypatch, [Response({"files": [{"source": "archive/field.md"}]})])
    with pytest.raises(project_nomad.NomadError, match="not in Nomad"):
        project_nomad.run({"action": "read_file", "source": "../../private.env"})
    assert len(session.calls) == 1

    session = _setup(monkeypatch, [Response({"files": [{
        "source": "archive/manual.pdf", "fileName": "manual.pdf", "isUserUpload": True,
    }]})])
    with pytest.raises(project_nomad.NomadError, match="only views uploaded text"):
        project_nomad.run({"action": "read_file", "source": "archive/manual.pdf"})
    assert len(session.calls) == 1


def test_zims_are_inventory_not_claimed_search_evidence(monkeypatch):
    _setup(monkeypatch, [Response({"files": [{"key": "medical_en", "title": "Medical reference",
                                                  "size_bytes": 4000, "type": "zim"}]})])
    data = project_nomad.run({"action": "zims"})["data"]
    assert data["total"] == 1
    assert data["zim_inventory_only"] is True
    assert data["zims"][0]["title"] == "Medical reference"


def test_zero_named_collections_does_not_claim_empty_knowledge(monkeypatch):
    _setup(monkeypatch, [Response({"collections": []})])
    result = project_nomad.run({"action": "collections"})
    assert result["data"]["total"] == 0
    assert "Unassigned files can still be indexed" in result["speech"]
    assert "does not mean an empty knowledge base" in result["data"]["note"]


def test_models_and_status_use_read_only_routes(monkeypatch):
    session = _setup(monkeypatch, [
        Response([{"name": "gemma4:12b", "thinking": True}, {"name": "glm:cloud"}]),
        Response({"status": "ok"}), Response({"online": True}),
    ])
    models = project_nomad.run({"action": "models"})["data"]
    assert models["models"][1]["cloud"] is True
    status_result = project_nomad.run({"action": "status"})
    status = status_result["data"]
    assert status["action"] == "status" and status["status"] == "ok" and status["rag_online"] is True
    assert "not a test of document indexing" in status["note"]
    assert "does not verify" in status_result["speech"]
    assert [call[0] for call in session.calls] == ["GET", "GET", "GET"]


def test_bad_arguments_and_bad_base_url_do_not_send_requests(monkeypatch):
    session = _setup(monkeypatch, [], {"PROJECT_NOMAD_BASE_URL": "http://user:secret@nomad.test/"})
    with pytest.raises(project_nomad.NomadError) as exc:
        project_nomad.run({"action": "status"})
    assert "secret" not in str(exc.value)
    assert session.calls == []
    with pytest.raises(ValueError):
        project_nomad.run({"action": "ask", "question": ""})
    with pytest.raises(ValueError):
        project_nomad.run({"action": "files", "limit": True})


def test_redirect_and_oversized_responses_fail_closed_without_echoing_body(monkeypatch):
    session = _setup(monkeypatch, [Response({"secret": "DO_NOT_ECHO"}, status=302)])
    with pytest.raises(project_nomad.NomadError, match="HTTP 302") as exc:
        project_nomad.run({"action": "files"})
    assert "DO_NOT_ECHO" not in str(exc.value)
    assert session.calls[0][2]["allow_redirects"] is False
    _setup(monkeypatch, [Response({}, headers={"Content-Length": str(project_nomad.MAX_RESPONSE_BYTES + 1)})])
    with pytest.raises(project_nomad.NomadError, match="too large"):
        project_nomad.run({"action": "files"})


def test_manifest_is_opt_in_and_restricts_child_environment():
    manifest_path = ROOT / "skills/project_nomad.tool.json"
    manifest = json.loads(manifest_path.read_text())
    schema = ToolSchema.from_json_file(str(manifest_path))
    assert manifest["availability"]["all_of_env"] == ["PROJECT_NOMAD_BASE_URL"]
    assert schema.child_environment_names == frozenset({"PROJECT_NOMAD_BASE_URL", "PROJECT_NOMAD_MODEL"})
    assert manifest["parameters"]["additionalProperties"] is False
    assert "ask my Project NOMAD knowledge base" in manifest["description"]
    child = restrict_child_environment({
        "PATH": "/usr/bin", "JARVIS_MODE": "local",
        "PROJECT_NOMAD_BASE_URL": "http://nomad.test",
        "PROJECT_NOMAD_MODEL": "gemma4:12b", "OPENAI_API_KEY": "SECRET",
        "LOCAL_PROXY": "http://proxy.test",
    }, schema.child_environment_names, home="/tmp/empty-home", proxy_policy="off")
    assert child["PROJECT_NOMAD_MODEL"] == "gemma4:12b"
    assert "OPENAI_API_KEY" not in child and "LOCAL_PROXY" not in child


def test_setup_links_point_to_the_dedicated_guide():
    guide = ROOT / "docs/tools/project-nomad/README.md"
    assert guide.is_file()
    for example in ("local.env.example", "cloud.env.example"):
        text = (ROOT / "config" / example).read_text()
        assert "docs/tools/project-nomad/README.md" in text
        assert "docs/PROJECT_NOMAD.md" not in text
    assert "docs/tools/project-nomad/README.md" in (
        ROOT / "skills/project_nomad.tool.json"
    ).read_text()


def test_followup_preserves_pagination_and_exact_source_without_full_text():
    load_server_package("nomad_followup_server", ROOT / "jarvis-web/server")
    path = ROOT / "jarvis-web/server/services/followup_extractor.py"
    spec = importlib.util.spec_from_file_location("nomad_followup_server.services.followup_extractor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.extract_followup_data({"project_nomad": {"data": {
        "action": "files", "total": 50, "offset": 0, "limit": 10, "has_more": True,
        "inventory": {"total_files": 50, "files_with_chunks": 20,
                      "reported_embedded_chunks": 30000,
                      "states": {"pending_decision": 8, "failed": 2}},
        "files": [{"source": f"archive/{i}.md", "file_name": f"{i}.md"} for i in range(10)],
    }}})
    data = result["project_nomad"]
    assert data["total"] == 50 and data["has_more"] is True
    assert data["files"][0]["source"] == "archive/0.md"
    assert data["inventory"]["files_with_chunks"] == 20
    assert len(data["files"]) == 3
    assert project_nomad_data({"action": "ask", "answer": "A" * 2000}, text_budget=100)["answer_context_truncated"]


def test_web_card_escapes_nomad_text_and_shows_total():
    from test_structured_results_adapters import _run_renderer_assertions

    _run_renderer_assertions(r"""
const payload={action:'files',total:50,offset:0,limit:10,has_more:true,
 inventory:{total_files:50,files_with_chunks:16,states:{pending_decision:9,failed:12}},
 files:[{source:'archive/note.md',file_name:'<img src=x onerror=alert(1)>',state:'completed'}]};
const html=renderer.render({project_nomad:{data:payload}});
assert.ok(html.includes('🗿 Project NOMAD'));
assert.ok(html.includes('50 stored'));
assert.ok(html.includes('16 report embedded chunks'));
assert.ok(html.includes('9 pending'));
assert.ok(html.includes('more available'));
assert.ok(html.includes('&lt;img'));
assert.ok(!html.includes('<img src=x'));
assert.ok(!html.includes('href="javascript:'));
""")


def test_web_answer_card_opens_saved_full_text_in_reader():
    from test_structured_results_adapters import _run_renderer_assertions

    _run_renderer_assertions(r"""
const answer='**Hello** <img src=x onerror=alert(1)>\nSecond paragraph.';
const note='Nomad answer has no verifiable passage citations.';
const html=renderer.render({project_nomad:{data:{
  action:'ask',question:'What is in my NOMAD archive?',model:'local-model',
  answer,evidence_note:note,
}}});
assert.ok(html.includes('structured-results-layout-list'));
assert.ok(html.includes('Project NOMAD · answer'));
assert.ok(html.includes('Unverified answer'));
assert.ok(html.includes('Read full answer'));
assert.ok(html.includes('structured-result-card-expandable'));
assert.ok(html.includes('structured-result-full-text" hidden'));
assert.ok(html.includes('&lt;img src=x'));
assert.ok(!html.includes('<img src=x'));
const fields={};
const dialog={open:false,querySelector(selector){
  return fields[selector] ??= {textContent:'',hidden:false};
},showModal(){this.open=true;}};
renderer._ensureReaderDialog=()=>dialog;
const card={querySelector(selector){return {
  '.structured-result-full-text':{textContent:answer},
  '.structured-result-full-note':{textContent:note},
  '.structured-result-title':{textContent:'Nomad answer'},
  '.structured-result-primary':{textContent:'local-model'},
  '.structured-result-expand-button':{focus(){},isConnected:true},
}[selector] || null;}};
renderer._openExpandedResult(card);
assert.equal(dialog.open,true);
assert.equal(fields['[data-reader-title]'].textContent,'Nomad answer');
assert.equal(fields['[data-reader-meta]'].textContent,'local-model · Plain text');
assert.equal(fields['[data-reader-text]'].textContent,answer);
assert.equal(fields['[data-reader-note]'].textContent,note);
const listeners={};
sandbox.document={addEventListener(name,fn){listeners[name]=fn;}};
renderer._bindScrollControls();
let opened=false;
renderer._openExpandedResult=clicked=>{opened=clicked===card;};
listeners.click({target:{closest(selector){return selector==='.structured-result-card-expandable' ? card : null;}}});
assert.equal(opened,true);
const file=renderer.render({project_nomad:{data:{
  action:'read_file',source:'notes/field guide.md',text:'First line\nSecond line',
  next_start_char:12000,
}}});
assert.ok(file.includes('Read file text'));
assert.ok(file.includes('structured-results-layout-list'));
const status=renderer.render({project_nomad:{data:{action:'status',status:'ok',rag_online:true}}});
assert.ok(status.includes('Project NOMAD · connection'));
assert.ok(status.includes('structured-results-layout-list'));
assert.ok(!status.includes('structured-result-expand-button'));
""")


def test_web_reader_explicitly_centers_despite_global_margin_reset():
    css = (ROOT / "jarvis-web/client/css/main.css").read_text()
    reader_rule = css.split(".structured-result-reader {", 1)[1].split("}", 1)[0]
    for declaration in (
        "position: fixed;", "top: 50%;", "left: 50%;",
        "transform: translate(-50%, -50%);",
    ):
        assert declaration in reader_rule


def test_web_tool_picker_uses_nomad_relic_emoji():
    app_js = (ROOT / "jarvis-web/client/js/app.js").read_text(encoding="utf-8")
    assert "project_nomad: '🗿'" in app_js
