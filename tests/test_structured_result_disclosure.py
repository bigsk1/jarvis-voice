"""Disclosure defaults follow presentation and exact per-response tool usage."""

import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from test_web_assistant_message_rendering import HARNESS
from test_web_continuation_rendering import DOM

ROOT = Path(__file__).resolve().parents[1]

SETUP = r"""
const renderer=sandbox.window.structuredResultsRenderer;
const local=name=>({query:name,results:[{title:name,address:'Example address',website:'https://example.test/place'}]});
const yelp=name=>({find_desc:name,results:[{title:name,url:'https://example.test/review'}]});
const workspace=tool=>({source:'google_workspace',tool,response_text:'A useful response <script>inert</script>',
  request:{user_google_email:'fixture@example.test'},references:[]});
const external=(result,extra={})=>({contract:'external_result_v1',
  source:{provider:'apify',tool:'apify_read_result',mode:'local'},
  execution:{run_id:'NativeRun123',status:'SUCCEEDED'},result,
  raw_ref:'stash://space_disclosure/f_page',...extra});
const property=()=>external({kind:'dataset',dataset_id:'NativeDataset123',
  sample_items:[{kind:'property_listing',source:'zillow',address:'A useful property',
    price:400000,currency:'USD',listing_status:'for_sale',url:'https://www.zillow.com/homedetails/1_zpid/'}],
  presentation:{kind:'property_listings',source:'zillow'},offset:0,returned_count:1,total_items:1,complete:true});
const output=value=>process.stdout.write('__DISCLOSURE__'+JSON.stringify(value)+'\n');
"""


def run_renderer(body, *, dom=False):
    source = "const ROOT=" + json.dumps(str(ROOT)) + ";\n" + HARNESS
    source += "\n(async()=>{\n" + (DOM if dom else "") + SETUP + body
    source += "\n})().catch(error=>{console.error(error);process.exit(1);});"
    result = subprocess.run(["node"], input=source, text=True, capture_output=True, timeout=15, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = [json.loads(line.removeprefix("__DISCLOSURE__"))
               for line in result.stdout.splitlines() if line.startswith("__DISCLOSURE__")]
    return outputs[-1] if outputs else None


class ResultPanels(HTMLParser):
    """Inspect native disclosure attributes without guessing from provider text."""

    def __init__(self, html):
        super().__init__()
        self.panels = []
        self.stack = []
        self.active = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if "structured-results-preview" in classes:
            panel = {"tag": tag, "attributes": attributes, "header_tag": None, "depth": len(self.stack)}
            self.panels.append(panel)
            self.active.append(panel)
        if "structured-results-header" in classes and self.active:
            self.active[-1]["header_tag"] = tag
        if tag not in {"img", "br", "hr", "input", "source", "meta", "link"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        depth = len(self.stack) - 1 - self.stack[::-1].index(tag)
        self.stack = self.stack[:depth]
        self.active = [panel for panel in self.active if panel["depth"] < depth]


def panels(html):
    result = ResultPanels(html).panels
    assert result, "Expected structured result panels"
    assert all(panel["tag"] == "details" and panel["header_tag"] == "summary" for panel in result)
    return result


def is_open(panel):
    return "open" in panel["attributes"]


@pytest.mark.parametrize("calls", [3, 4])
def test_exact_tool_threshold_preserves_other_visual_results(calls):
    html = run_renderer("const calls=" + str(calls) + ";\n" + r"""
const data={serpapi_google_local:Array.from({length:calls},(_,index)=>local(`Local result ${index+1}`)),
 serpapi_yelp_search:yelp('A separate useful result'),
 _tool_trace:[...Array.from({length:calls},()=>({tool:'serpapi_google_local',ok:true})),{tool:'serpapi_yelp_search',ok:true}]};
output(renderer.render(data));
""")
    results = panels(html)
    local_panels = [panel for panel in results if panel["attributes"].get("data-orchestration-tool") == "serpapi_google_local"]
    yelp_panel = next(panel for panel in results if panel["attributes"].get("data-orchestration-tool") == "serpapi_yelp_search")
    assert len(local_panels) == calls
    assert all(is_open(panel) == (calls <= 3) for panel in local_panels)
    assert is_open(yelp_panel)
    assert html.index('Local result 1') < html.index(f'Local result {calls}') < html.index('A separate useful result')


def test_failed_calls_count_toward_threshold_without_shifting_successful_payloads():
    html = run_renderer(r"""
output(renderer.render({serpapi_google_local:[local('First valid result'),local('Second valid result')],
 serpapi_yelp_search:yelp('Unrelated result'),_tool_trace:[
 {tool:'serpapi_google_local',ok:true},{tool:'serpapi_google_local',ok:false},
 {tool:'serpapi_google_local',ok:true},{tool:'serpapi_google_local',ok:false},
 {tool:'serpapi_yelp_search',ok:true}]}));
""")
    results = panels(html)
    assert [panel["attributes"]["data-orchestration-call"] for panel in results] == ["1", "3", "5"]
    assert [is_open(panel) for panel in results] == [False, False, True]
    assert "2 failed" in html
    assert html.index("First valid result") < html.index("Second valid result")
    one_visible = run_renderer(r"""
output(renderer.render({serpapi_google_local:local('Only visible success'),_tool_trace:[
 {tool:'serpapi_google_local',ok:false},{tool:'serpapi_google_local',ok:false},
 {tool:'serpapi_google_local',ok:false},{tool:'serpapi_google_local',ok:true}]}));
""")
    assert [is_open(panel) for panel in panels(one_visible)] == [False]


def test_legacy_tool_lists_count_exact_names_and_do_not_accumulate_between_messages():
    result = run_renderer(r"""
const older={serpapi_google_local:[local('Saved one'),local('Saved two'),local('Saved three'),local('Saved four')],
 serpapi_yelp_search:yelp('Other saved tool')};
const first=renderer.render(older,{},['serpapi_google_local','serpapi_google_local','serpapi_yelp_search','serpapi_google_local','serpapi_google_local']);
const next=renderer.render({serpapi_google_local:local('A new response')},{},['serpapi_google_local']);
output({first,next});
""")
    assert [is_open(panel) for panel in panels(result["first"])] == [False, False, True, False, False]
    assert [is_open(panel) for panel in panels(result["next"])] == [True]


def test_apps_script_is_technical_while_documents_calendar_and_local_cards_stay_open():
    html = run_renderer(r"""
const data={mcp_google_workspace_get_script_project:workspace('get_script_project'),
 mcp_google_workspace_run_script_function:workspace('run_script_function'),
 mcp_google_workspace_create_doc:workspace('create_doc'),mcp_google_workspace_list_calendars:workspace('list_calendars'),
 serpapi_google_local:local('A useful local result'),serpapi_yelp_search:yelp('A useful review result')};
data._tool_trace=Object.keys(data).map(tool=>({tool,ok:true}));
output(renderer.render(data));
""")
    results = panels(html)
    assert [is_open(panel) for panel in results] == [False, False, True, True, True, True]
    assert "structured-result-expand-button" in html
    assert "&lt;script&gt;inert&lt;/script&gt;" in html
    assert "<script>inert</script>" not in html
    distinct = run_renderer(r"""
const data={mcp_google_workspace_create_doc:[workspace('create_doc'),workspace('create_doc')],
 mcp_google_workspace_list_calendars:[workspace('list_calendars'),workspace('list_calendars')]};
data._tool_trace=[{tool:'mcp_google_workspace_create_doc',ok:true},{tool:'mcp_google_workspace_list_calendars',ok:true},
 {tool:'mcp_google_workspace_create_doc',ok:true},{tool:'mcp_google_workspace_list_calendars',ok:true}];
output(renderer.render(data));
""")
    assert all(is_open(panel) for panel in panels(distinct))


@pytest.mark.parametrize("executed,skipped,failed", [(3, 1, 0), (4, 0, 0), (3, 0, 1)])
def test_workflow_counts_actual_matching_steps_without_counting_skipped_tools(executed, skipped, failed):
    html = run_renderer("const executed=" + str(executed) + ",skipped=" + str(skipped)
                        + ",failed=" + str(failed) + ";\n" + r"""
const results=Array.from({length:executed},(_,index)=>({step:index+1,tool:'serpapi_google_local',ok:true,data:local(`Step ${index+1}`)}));
for(let index=0;index<skipped;index++)results.push({step:executed+index+1,tool:'serpapi_google_local',skipped:true});
for(let index=0;index<failed;index++)results.push({step:results.length+1,tool:'serpapi_google_local',ok:false,error:'Failed call'});
results.push({step:results.length+1,tool:'serpapi_yelp_search',ok:true,data:yelp('Independent workflow result')});
output(renderer.render({workflow:{workflow_id:'fixture',results}}));
""")
    results = panels(html)
    assert len(results) == executed + 1
    assert [is_open(panel) for panel in results] == [executed + failed <= 3] * executed + [True]
    assert all("data-workflow-step" in panel["attributes"] for panel in results)


def test_property_cards_are_visual_but_generic_external_and_lifecycle_receipts_are_technical():
    result = run_renderer(r"""
const properties=renderer.render({apify_read_result:property()});
const generic=renderer.render({apify_read_result:external({kind:'dataset',sample_items:[{id:'Kept native id',nested:{flag:false}}],
 returned_count:1,total_items:1,offset:0,complete:true})});
const lifecycle=renderer.render({apify_read_result:external({kind:'object',complete:false},
 {execution:{run_id:'NativeRun123',status:'RUNNING'}})});
const factory=sandbox.window.createApifyResultAdapter;delete sandbox.window.createApifyResultAdapter;
const fallback=new sandbox.window.StructuredResultsRenderer();
const helperAbsent=fallback.render({apify_read_result:property()});
sandbox.window.createApifyResultAdapter=factory;
output({properties,generic,lifecycle,helperAbsent});
""")
    assert [is_open(panel) for panel in panels(result["properties"])] == [True]
    assert 'class="apify-property-card"' in result["properties"]
    for key in ("generic", "lifecycle", "helperAbsent"):
        assert [is_open(panel) for panel in panels(result[key])] == [False]
    assert "Kept native id" in result["generic"]
    assert "/api/stash/space_disclosure/f_page?mode=local" in result["generic"]
    assert "NativeRun123" in result["lifecycle"]


def test_custom_adapter_explicit_technical_hint_does_not_classify_all_generic_cards_as_debug():
    result = run_renderer(r"""
renderer.register('custom_diagnostic',()=>({kind:'generic',disclosure:'technical',heading:'A diagnostic',items:[{title:'Preserved evidence'}]}));
renderer.register('custom_readable',()=>({kind:'generic',heading:'Readable search results',items:[{title:'Useful content'}]}));
output({technical:renderer.render({custom_diagnostic:{ok:true}}),visual:renderer.render({custom_readable:{ok:true}})});
""")
    assert [is_open(panel) for panel in panels(result["technical"])] == [False]
    assert [is_open(panel) for panel in panels(result["visual"])] == [True]


def test_a_plain_results_array_is_one_collection_and_trace_counts_override_array_estimates():
    result = run_renderer(r"""
const rows=Array.from({length:5},(_,index)=>({title:`Ordinary listing ${index+1}`,address:'Example address'}));
const withoutTrace=renderer.render({serpapi_google_local:rows});
const withTrace=renderer.render({serpapi_google_local:rows,_tool_trace:[{tool:'serpapi_google_local',ok:true}]});
const savedCalls=renderer.render({serpapi_google_local:Array.from({length:4},(_,index)=>local(`Saved call ${index+1}`))});
output({withoutTrace,withTrace,savedCalls});
""")
    assert [is_open(panel) for panel in panels(result["withoutTrace"])] == [True]
    assert [is_open(panel) for panel in panels(result["withTrace"])] == [True]
    assert "Ordinary listing 5" in result["withoutTrace"]
    assert [is_open(panel) for panel in panels(result["savedCalls"])] == [False]


@pytest.mark.parametrize("calls", [3, 4])
def test_external_continuations_use_safe_dom_and_the_same_default_collapse_policy(calls):
    run_renderer("const calls=" + str(calls) + ";\n" + r"""
const ui=chat(),results=Array.from({length:calls},()=>property());
const attack='<img src=x onerror=alert(1)>';
results[0].result.sample_items[0].address=attack;
ui.addAssistantMessage('Saved property results',[],{_kind:'continuation',_background_mode:'local',
 apify_read_result:results,other_external:external({kind:'object',value:{message:attack},complete:true},
 {source:{provider:'fixture',tool:'other_external',mode:'local'}})});
const rendered=message(ui),roots=rendered.querySelectorAll('.structured-results-preview');
assert.equal(roots.length,calls+1);
for(const root of roots){assert.equal(root.tag,'details');assert.ok(root.children.some(child=>child.tag==='summary'));}
for(const root of roots.slice(0,calls))assert.equal(Object.hasOwn(root,'open'),calls<=3);
assert.equal(Object.hasOwn(roots.at(-1),'open'),false);
assert.ok(visible(rendered).includes(attack));
assert.ok(!descendants(rendered).some(el=>['script','svg','iframe'].includes(el.tag)));
assert.ok(descendants(rendered).some(el=>el.tag==='a'&&el.href==='/api/stash/space_disclosure/f_page?mode=local'));
assert.ok(!effects.some(effect=>effect==='clear-actions'||effect==='hydrate'));
""", dom=True)


def test_saved_external_trace_counts_failed_calls_without_replaying_or_hiding_evidence():
    run_renderer(r"""
const ui=chat(),payload={_kind:'continuation',_background_mode:'local',
 apify_read_result:[property(),property()],_tool_trace:[
 {tool:'apify_read_result',ok:true},{tool:'apify_read_result',ok:false},
 {tool:'apify_read_result',ok:true},{tool:'apify_read_result',ok:false}]};
ui.addAssistantMessage('Saved results',[],payload);
const rendered=message(ui),roots=rendered.querySelectorAll('.structured-results-preview');
assert.equal(roots.length,2);
assert.ok(roots.every(root=>root.tag==='details'&&!Object.hasOwn(root,'open')));
assert.ok(visible(rendered).includes('A useful property'));
assert.ok(visible(rendered).includes('NativeRun123'));
assert.ok(!effects.some(effect=>effect==='clear-actions'||effect==='hydrate'));
""", dom=True)


def test_external_authoritative_trace_is_not_overridden_by_stored_payload_count():
    run_renderer(r"""
const ui=chat();
ui.addAssistantMessage('Saved results',[],{_kind:'continuation',_background_mode:'local',
 apify_read_result:Array.from({length:4},()=>property()),_tool_trace:[{tool:'apify_read_result',ok:true}]});
const roots=message(ui).querySelectorAll('.structured-results-preview');
assert.equal(roots.length,4);
assert.ok(roots.every(root=>root.tag==='details'&&Object.hasOwn(root,'open')));
""", dom=True)
