"""Interrupted paid workflow steps expose existing job handles without replay."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from config_loader import config_scope
from test_web_attachment_bundle_ui import run_browser

import orchestrator.pipeline_executor as pipeline_module
from orchestrator.pipeline_executor import PipelineExecutor

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "stash://space_heygen_receipt/f_existing_request"
HANDLES = {"provider_video_id": "native_video_7", "kind": "model", "request_id": "jarvis-heygen-request_7", "receipt_stash_ref": RECEIPT}


@pytest.fixture
def execute_intro(monkeypatch):
    monkeypatch.setattr(pipeline_module, "ToolLogger", MagicMock())
    monkeypatch.setattr(pipeline_module, "LLMLogger", MagicMock())
    workflow = json.loads((ROOT / "data/workflows/heygen_jarvis_intro.json").read_text())

    def execute(failure, *, tool="generate_video"):
        calls = []
        recipe = deepcopy(workflow)
        recipe["steps"][4]["tool"] = tool

        def run(name, args):
            calls.append(name)
            if name == "heygen" and args.get("action") == "account":
                return {"ok": True, "data": {"wallet": {"remaining_balance": 15}}}
            if name == "stash" and args["action"] == "save":
                return {"ok": True, "data": {"ref": "stash://space_readme/f_readme", "space_id": "space_readme", "file_id": "f_readme"}}
            if name == "stash":
                return {"ok": True, "data": {"content": "Jarvis Voice provides voice, chat, tools and workflows."}}
            if name == "generate_image":
                assert args["image_size"] == "1K"
                assert "resolution" not in args
                return {"ok": True, "data": {"saved": {"stash_ref": "stash://space_art/f_first_frame"}}}
            assert name == tool
            return deepcopy(failure)

        provider = SimpleNamespace(chat_with_tools=lambda **_: (
            "JARVIS VOICE. " + "Charcoal-and-jade artwork with a waveform and readable title. " * 5,
            None, None, None,
        ))
        with config_scope("cloud", {"VIDEO_TOOL_PROVIDER": "xai"}):
            result = PipelineExecutor("cloud", SimpleNamespace(execute=run), provider).execute(recipe, "/heygen_intro")
        assert result["ok"] is False
        assert result["data"]["aborted_at_step"] == 5
        assert calls == ["heygen", "stash", "stash", "generate_image", tool]
        return result

    return execute


@pytest.mark.parametrize("completion", ["unknown", "completed"])
def test_actual_intro_abort_exposes_native_recovery_without_replaying_paid_step(execute_intro, completion):
    result = execute_intro({"ok": False, "completion": completion,
                            "error": "Still processing" if completion == "unknown" else "Remote work finished; local saving failed",
                            "data": {**HANDLES, "api_key": "PRIVATE_SENTINEL"}})
    for value in HANDLES.values():
        assert value in result["speech"]
    assert "heygen status or collect" in result["speech"]
    assert "Do not rerun" in result["speech"]
    failed = result["data"]["results"][-1]
    assert failed["completion"] == completion
    assert failed["recovery"] == {**HANDLES, "provider": "heygen", "completion": completion}
    assert "PRIVATE_SENTINEL" not in result["speech"]


def test_lost_submission_response_exposes_request_receipt_without_inventing_video_id(execute_intro):
    result = execute_intro({"ok": False, "completion": "unknown", "error": "Submission response was interrupted",
                            "data": {"provider": "heygen", "kind": "model", "request_id": "jarvis-heygen-request_7", "receipt_stash_ref": RECEIPT}})
    assert RECEIPT in result["speech"]
    assert "jarvis-heygen-request_7" in result["speech"]
    assert "No provider video ID was confirmed" in result["speech"]
    assert "provider_video_id" not in result["data"]["results"][-1]["recovery"]
    assert "Use heygen status" not in result["speech"]


def test_invalid_recovery_fields_never_enter_abort_speech_or_safe_projection(execute_intro):
    result = execute_intro({"ok": False, "completion": "unknown", "error": "Safe failure",
                            "data": {"provider": "heygen", "provider_video_id": "<img src=x onerror=alert(1)>",
                                     "kind": ["model"], "request_id": "x" * 161,
                                     "receipt_stash_ref": "stash://space/f_id?api_key=PRIVATE_SENTINEL", "api_key": "PRIVATE_SENTINEL"}})
    assert "recovery" not in result["data"]["results"][-1]
    assert "HeyGen recovery:" not in result["speech"]
    assert "PRIVATE_SENTINEL" not in result["speech"]
    assert "<img" not in result["speech"]


def test_other_provider_failure_is_not_branded_as_heygen(execute_intro):
    # A different tool cannot opt into the recovery projection merely by
    # returning similarly named fields.
    result = execute_intro({"ok": False, "error": "Safe failure", "data": HANDLES}, tool="unrelated_tool")
    assert "recovery" not in result["data"]["results"][-1]
    assert "HeyGen recovery:" not in result["speech"]


@pytest.fixture
def execute_loop(monkeypatch):
    monkeypatch.setattr(pipeline_module, "ToolLogger", MagicMock())
    monkeypatch.setattr(pipeline_module, "LLMLogger", MagicMock())

    def execute(outputs):
        calls = []
        workflow = {
            "id": "looped_heygen", "name": "Looped HeyGen recovery",
            "variables": {"jobs": {"from": "static", "value": [{"prompt": f"Clip {index}"} for index in range(len(outputs))]}},
            "steps": [{"step": 1, "tool": "generate_video", "for_each": "${jobs}",
                       "process_all": True, "params": {"provider": "heygen"},
                       "abort_speech": "The video workflow stopped."},
                      {"step": 2, "tool": "canvas", "params": {"action": "create"}}],
        }

        def run(tool, args):
            assert tool == "generate_video", "Aborted workflow continued to a later step"
            calls.append(args)
            return deepcopy(outputs[len(calls) - 1])

        with config_scope("cloud", {"VIDEO_TOOL_PROVIDER": "xai"}):
            result = PipelineExecutor("cloud", SimpleNamespace(execute=run), SimpleNamespace()).execute(workflow, "/looped_heygen")
        assert len(calls) == len(outputs)  # Each supplied item runs once; recovery never replays it.
        assert result["ok"] is False
        return result

    return execute


@pytest.mark.parametrize("completion,request_only", [("unknown", False), ("completed", False), ("unknown", True)])
def test_loop_abort_exposes_failed_item_handles_without_repeating_successes(execute_loop, completion, request_only):
    handles = {key: value for key, value in HANDLES.items() if not request_only or key != "provider_video_id"}
    result = execute_loop([
        {"ok": True, "data": {"provider": "heygen", "provider_video_id": "successful-video"}},
        {"ok": False, "completion": completion, "error": "Safe failure",
         "data": {**handles, "api_key": "PRIVATE_SENTINEL", "raw_html": "<script>unsafe()</script>"}},
    ])
    assert "Item 2" in result["speech"]
    assert "successful-video" not in result["speech"]
    assert "PRIVATE_SENTINEL" not in result["speech"] and "<script>" not in result["speech"]
    for value in handles.values():
        assert value in result["speech"]
    failed = result["data"]["results"][0]["outputs"][1]
    assert failed["recovery"] == {**handles, "provider": "heygen", "completion": completion}
    if request_only:
        assert "No provider video ID was confirmed" in result["speech"]
    run_browser("const pipeline = " + json.dumps(result["data"]) + r""";
const ui = chat();
sandbox.Utils.formatJson = value => JSON.stringify(value, null, 2);
sandbox.Utils.escapeHtmlAndLinkify = sandbox.Utils.escapeHtml;
const failed = ui._getToolTraceEntries(pipeline).find(entry => entry.workflow_step === '1_1');
assert.equal(failed.ok, false);
const failure = ui._getToolTraceFailureResult(failed);
assert.equal(failure.data.completion, pipeline.results[0].outputs[1].completion);
const html = ui._createToolCardHtml(failed.tool, 'error', failure, null, ui._getWorkflowStepLabel(failed));
assert.match(html, /jarvis-heygen-request_7/);
assert.match(html, /stash:\/\/space_heygen_receipt\/f_existing_request/);
assert.ok(!html.includes('PRIVATE_SENTINEL'));
assert.ok(!html.includes('<script>'));
assert.equal(requests.length, 0);
""")


def test_loop_abort_bounds_spoken_recovery_and_retains_remaining_item_handles(execute_loop):
    result = execute_loop([
        {"ok": False, "completion": "unknown", "error": "Safe failure",
         "data": {"provider": "heygen", "provider_video_id": f"failed-video-{index}"}}
        for index in range(7)
    ])
    assert result["speech"].count("HeyGen recovery:") == 5
    assert "2 additional failed items" in result["speech"]
    assert "failed-video-6" not in result["speech"]
    outputs = result["data"]["results"][0]["outputs"]
    assert outputs[6]["recovery"]["provider_video_id"] == "failed-video-6"


@pytest.mark.parametrize("request_only,completion", [(False, "unknown"), (False, "completed"), (True, "unknown")])
def test_actual_pipeline_failure_reaches_web_workflow_trace_card(execute_intro, request_only, completion):
    handles = {key: value for key, value in HANDLES.items() if not request_only or key != "provider_video_id"}
    result = execute_intro({"ok": False, "completion": completion, "error": "Safe failure", "data": {
        **handles, "api_key": "PRIVATE_SENTINEL", "arbitrary_html": "<script>unsafe()</script>",
    }})
    run_browser("const pipeline = " + json.dumps(result["data"]) + r""";
const ui = chat();
sandbox.Utils.formatJson = value => JSON.stringify(value, null, 2);
sandbox.Utils.escapeHtmlAndLinkify = sandbox.Utils.escapeHtml;
const entries = ui._getToolTraceEntries(pipeline);
const failed = entries.find(entry => entry.workflow_step === 5);
assert.equal(failed.ok, false);
const failure = ui._getToolTraceFailureResult(failed);
assert.equal(failure.data.receipt_stash_ref, 'stash://space_heygen_receipt/f_existing_request');
assert.equal(failure.data.completion, pipeline.results.at(-1).completion);
const html = ui._createToolCardHtml(failed.tool, 'error', failure, null, ui._getWorkflowStepLabel(failed));
assert.match(html, /Step 5/);
assert.match(html, /Failed/);
assert.match(html, /jarvis-heygen-request_7/);
assert.match(html, /stash:\/\/space_heygen_receipt\/f_existing_request/);
assert.ok(!html.includes('PRIVATE_SENTINEL'));
assert.ok(!html.includes('<script>'));
assert.ok(!Object.keys(failure.data).includes('api_key'));
ui.pendingTools={generate_video_step5:{toolName:'generate_video',status:'pending',result:null}};
ui._reconcilePendingToolsWithFinalList(['generate_video'],entries);
const live=ui._getPendingToolCardEntries(pipeline,Object.entries(ui.pendingTools),entries)
  .find(entry=>entry.displayName==='generate_video');
assert.equal(live.status,'error');
assert.equal(live.result.data.receipt_stash_ref,failure.data.receipt_stash_ref);
assert.ok(!JSON.stringify(live.result).includes('PRIVATE_SENTINEL'));
assert.equal(requests.length, 0);
""")


def test_saved_workflow_card_revalidates_handles_and_does_not_dump_raw_tool_data():
    run_browser(r"""
const ui = chat();
const payload = {workflow_id:'saved', results:[{step:5,tool:'generate_video',ok:false,error:'Safe error',
  data:{provider:'heygen',provider_video_id:'<img src=x onerror=alert(1)>',receipt_stash_ref:'stash://space/f_receipt',
    request_id:'x'.repeat(161),kind:'model',api_key:'PRIVATE_SENTINEL'}}]};
const trace = ui._getToolTraceEntries(payload);
const failure = ui._getToolTraceFailureResult(trace[0]);
assert.equal(failure.data.receipt_stash_ref,'stash://space/f_receipt');
assert.ok(!('provider_video_id' in failure.data));
assert.ok(!('request_id' in failure.data));
assert.ok(!JSON.stringify(failure).includes('PRIVATE_SENTINEL'));
assert.ok(!JSON.stringify(failure).includes('<img'));
assert.equal(requests.length,0);
""")


def test_modal_requires_explicit_available_provider_after_heygen_key_removal_and_restores_choice():
    run_browser(r"""
class Choice {
  constructor(text,value) { this.textContent=text; this.value=value; this.dataset={}; }
  remove() { this.parent.options=this.parent.options.filter(option=>option!==this); }
}
class Select {
  constructor(value='') { this.value=value; this.options=[]; }
  add(option) { option.parent=this; this.options.push(option); }
  appendChild(option) { this.add(option); }
  replaceChildren() { this.options=[]; }
  querySelector(selector) { return this.options.find(option=>selector===`option[value="${option.value}"]`)||null; }
}
sandbox.Option=Choice;
const elements={};
for (const id of ['imgActionVideoProvider','imgActionVideoModel','imgActionVideoResolution','imgActionVideoRatio',
                  'setting-video-provider']) elements[id]=new Select();
elements.imgActionVideoProvider.add(new Choice('xAI','xai'));
elements.imgActionVideoProvider.add(new Choice('Gemini','gemini'));
elements['setting-video-provider'].value='xai'; // Stale AI config must not bypass the explicit-choice flag.
for (const id of ['confirmImageAction','imgActionVideoModelDesc','imgActionVideoDuration','imgActionVideoDurationDesc']) elements[id]=new Element();
elements.imgActionVideoDuration.value='5';
sandbox.document.getElementById=id=>elements[id]||null;
const settings={video:{provider:{value:null,default:'xai',selection_required:true}},
  video_providers:{xai:{name:'xAI'},gemini:{name:'Gemini'}},
  provider_availability:{video:{xai:{status:'available'},gemini:{status:'unavailable'}}}};
sandbox.window.jarvisApp={_settingsData:settings};
const ui=chat();
let action='video';
ui.imageActionModal=new Element();
ui.imageActionModal.querySelector=()=>({value:action});
ui._updateImageProviderOptions=()=>{};
ui._renderImagePreviews=()=>{};
ui._resetImageActionOptions();
assert.equal(elements.imgActionVideoProvider.value,'');
assert.ok(elements.imgActionVideoProvider.options.some(option=>option.value===''&&option.textContent==='Choose video provider'));
assert.equal(elements.confirmImageAction.disabled,true);
assert.equal(elements.imgActionVideoModel.disabled,true);
assert.equal(ui._collectImageActionSettings().settings.provider,'');
ui.pendingImageBatch=[{url:'/uploads/reference.png',filename:'reference.png'}];
await ui._confirmImageAction();
assert.equal(ui.attachedImages.length,0);
assert.match(notices.at(-1)[0],/Choose an available video provider/);
elements.imgActionVideoProvider.value='gemini';
ui._updateVideoProviderOptions();
assert.equal(elements.confirmImageAction.disabled,true);
await ui._confirmImageAction();
assert.equal(ui.attachedImages.length,0);
action='analyze'; ui._updateImageActionOptions();
assert.equal(elements.confirmImageAction.disabled,false);
action='video'; elements.imgActionVideoProvider.value='xai'; ui._updateVideoProviderOptions();
assert.equal(elements.confirmImageAction.disabled,false);
assert.equal(elements.imgActionVideoModel.disabled,false);
await ui._confirmImageAction();
assert.equal(ui.attachedImages.length,1);
assert.equal(ui.imageAttachmentSettings.provider,'xai');
// The request-scoped choice must not rewrite the saved unresolved setting.
assert.equal(settings.video.provider.value,null);
settings.video.provider={value:'heygen'};
settings.video_providers.heygen={name:'HeyGen',model:'heygen-video-1',models:[{id:'heygen-video-1',resolutions:['480p'],aspect_ratios:['16:9'],duration_seconds:{min:5,max:15}}]};
elements['setting-video-provider'].value='';
ui._resetImageActionOptions();
assert.equal(elements.imgActionVideoProvider.value,'heygen');
assert.ok(!elements.imgActionVideoProvider.options.some(option=>option.value===''));
assert.equal(elements.imgActionVideoModel.value,'heygen-video-1');
assert.equal(requests.length,0);
""")
