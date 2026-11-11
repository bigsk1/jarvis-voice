"""Canvas property blocks remain safe, searchable, sortable saved snapshots."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.events={};this.className='';this.value='';this._text='';}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set innerHTML(value){throw new Error('Property report reached HTML parser: '+value);}
  append(...children){for(const child of children){this.children.push(child);child.parentElement=this;}}
  replaceChildren(...children){this.children=[];this._text='';this.append(...children);}
  replaceWith(node){this.replacement=node;}
  setAttribute(key,value){this.attributes[key]=String(value);}
  addEventListener(name,handler){this.events[name]=handler;}
}
const mounted=[],windowEvents={};
const document={createElement:tag=>new Element(tag),createTextNode:value=>{const node=new Element('#text');node.textContent=value;return node;},
  querySelectorAll:selector=>selector==='.canvas-property-report'?mounted:[]};
const sandbox={window:{addEventListener:(name,handler)=>{windowEvents[name]=handler;}},document,URL,console};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-canvas/client/static/js/property-report.js','utf8'),sandbox);
const report=sandbox.window.CanvasPropertyReport;
const all=node=>node.children.flatMap(child=>[child,...all(child)]);
const byClass=(node,name)=>all(node).filter(el=>el.className.split(' ').includes(name));
const control=(node,label)=>all(node).find(el=>el.attributes['aria-label']===label);
const row=index=>({kind:'property_listing',source:'zillow',listing_id:'BackendID'+index,
 address:`${index} Example Street`,city:index<=84?'Albany':'Lebanon',state:'OR',postal_code:index<=84?'97321':'97355',
 price:300000+index*1000,currency:'USD',listing_status:'for_sale',property_type:'single_family',
 bedrooms:3,bathrooms:2,area:1000+index,area_unit:'sqft',days_on_zillow:index,
 url:`https://www.zillow.com/homedetails/${index}_zpid/`});
const snapshot=()=>({version:1,source:'zillow',snapshot_at:'2026-11-10T20:46:00Z',
 criteria_text:'Requested: homes for sale in the selected cities. Source filters require verification.',
 coverage:{returned_count:116,total_items:116,offset:0,complete:true},
 items:Array.from({length:116},(_,index)=>row(index+1))});
"""


def run_report(body):
    script = "const ROOT=" + json.dumps(str(ROOT)) + ";\n" + HARNESS + body
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, cwd=ROOT, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_property_snapshot_keeps_all_embedded_rows_city_counts_and_unknown_evidence():
    run_report(r"""
const data=snapshot(),before=JSON.stringify(data);
data.items[115].days_on_zillow=null;
const element=report.buildReport(data),content=element.textContent;
for(const value of ['Zillow property snapshot','Snapshot:','Requested criteria','Unofficial listing snapshot',
 '116 saved listing rows','116 fetched','116 items in the source dataset','Saved listing rows',
 '84Albany','32Lebanon','1 listing without listing age','Duplicate listings have not been independently checked',
 'Showing 1–24 of 116 matching listing rows','1 Example Street','$301,000','3 beds','2 baths','1,001 sqft']) assert.ok(content.includes(value),value);
assert.ok(!content.includes('BackendID'));
assert.equal(byClass(element,'property-report-card').length,24);
const next=all(element).find(el=>el.tag==='button'&&el.textContent==='Next listings');
for(let page=0;page<4;page++)next.events.click();
assert.ok(element.textContent.includes('116 Example Street'));
assert.ok(element.textContent.includes('Listing age not provided'));
assert.ok(element.textContent.includes('Showing 97–116 of 116 matching listing rows'));
assert.ok(!element.textContent.includes('116 days on Zillow'));
assert.equal(data.items.length,116);
assert.equal(JSON.stringify(data.items[0]),JSON.stringify(JSON.parse(before).items[0]));
""")


def test_property_controls_filter_search_sort_and_switch_to_table_locally():
    run_report(r"""
const data=snapshot(),element=report.buildReport(data);
const city=control(element,'Filter listings by city'),sort=control(element,'Sort listings'),
 search=control(element,'Search property listings'),view=control(element,'Listings view');
city.value='Lebanon';city.events.change();
assert.ok(element.textContent.includes('of 32 matching listing rows'));
assert.ok(byClass(element,'property-report-card')[0].textContent.includes('85 Example Street'));
sort.value='price_down';sort.events.change();
assert.ok(byClass(element,'property-report-card')[0].textContent.includes('116 Example Street'));
search.value='97321';search.events.input();
assert.ok(element.textContent.includes('No listings match these local filters'));
city.value='';city.events.change();
assert.ok(element.textContent.includes('of 84 matching listing rows'));
assert.ok(byClass(element,'property-report-card')[0].textContent.includes('84 Example Street'));
search.value='5 Example';search.events.input();
view.value='table';view.events.change();
assert.equal(byClass(element,'property-report-card').length,0);
assert.equal(byClass(element,'property-report-table').length,1);
assert.ok(element.textContent.includes('Beds / baths'));
assert.ok(element.textContent.includes('5 Example Street'));
assert.ok(!element.textContent.includes('6 Example Street'));
assert.ok(all(element).some(el=>el.tag==='a'&&el.href==='https://www.zillow.com/homedetails/5_zpid/'));
""")


def test_property_blocks_hydrate_after_markdown_without_interpreting_untrusted_html():
    run_report(r"""
const data=snapshot();data.items=data.items.slice(0,1);
data.criteria_text='<img src=x onerror=alert(1)> Criteria';
Object.assign(data.items[0],{address:'<script>untrusted address</script>',url:'javascript:alert(2)',
 image_url:'https://evil.invalid/picture.jpg',price_text:'<svg onload=alert(3)>'});
const code=new Element('code'),pre=new Element('pre');pre.append(code);code.textContent=JSON.stringify(data);
report.hydrate({querySelectorAll:selector=>{assert.equal(selector,'pre > code.language-property-listings');return [code];}});
const rendered=pre.replacement;
assert.ok(rendered.textContent.includes('<img src=x onerror=alert(1)> Criteria'));
assert.ok(rendered.textContent.includes('<script>untrusted address</script>'));
assert.ok(rendered.textContent.includes('<svg onload=alert(3)>'));
assert.ok(!all(rendered).some(el=>['script','img','svg','iframe'].includes(el.tag)));
assert.ok(!all(rendered).some(el=>el.href?.startsWith('javascript:')));
assert.ok(!rendered.textContent.includes('BackendID'));
""")


def test_property_photos_and_geography_credit_use_only_known_https_origins():
    run_report(r"""
const data=snapshot();data.items=data.items.slice(0,1);
data.items[0].image_url='https://photos.zillowstatic.com/photo.jpg';
data.geography_attribution={provider:'openstreetmap'};
const element=report.buildReport(data),image=all(element).find(el=>el.tag==='img');
assert.equal(image.loading,'lazy');assert.equal(image.referrerPolicy,'no-referrer');
assert.equal(image.src,'https://photos.zillowstatic.com/photo.jpg');
const fallback=byClass(element,'property-report-photo-fallback')[0];
assert.equal(fallback.hidden,true);image.events.error();assert.equal(image.hidden,true);assert.equal(fallback.hidden,false);
assert.ok(element.textContent.includes('City-to-area lookup: © OpenStreetMap contributors'));
assert.ok(element.textContent.includes('Search map rectangles can include nearby places'));
assert.ok(all(element).some(el=>el.href==='https://www.openstreetmap.org/copyright'));
for(const unsafe of ['http://photos.zillowstatic.com/photo.jpg','https://photos.zillowstatic.com/file.svg',
 'https://photos.zillowstatic.com.evil.invalid/photo.jpg','data:image/svg+xml,<svg/>']){
 data.items[0].image_url=unsafe;
 assert.ok(!all(report.buildReport(data)).some(el=>el.tag==='img'));
}
""")


def test_mixed_provider_reports_and_invalid_or_oversized_blocks_are_bounded():
    run_report(r"""
const data=snapshot();data.source='mixed';data.items=data.items.slice(0,2);
Object.assign(data.items[1],{source:'redfin',url:'https://www.redfin.com/OR/Example/home/2',days_on_zillow:null});
const element=report.buildReport(data);
assert.ok(element.textContent.includes('Zillow and Redfin property snapshot'));
assert.ok(all(element).some(el=>el.href==='https://www.redfin.com/OR/Example/home/2'));
for(const invalid of [{...data,version:2},{...data,items:Array(2001).fill(row(1))},{...data,source:'zillow'}]){
 assert.throws(()=>report.buildReport(invalid));
}
for(const content of ['not JSON','x'.repeat(4*1024*1024+1)]){
 const code=new Element('code'),pre=new Element('pre');pre.append(code);code.textContent=content;
 report.hydrate({querySelectorAll:()=>[code]});
 assert.ok(pre.replacement.textContent.includes('saved data is invalid or exceeds'));
 assert.equal(pre.replacement.tag,'p');
}
""")


def test_canvas_mounts_property_renderer_before_code_highlighting():
    template = (ROOT / "jarvis-canvas/client/templates/canvas.html").read_text()
    code = (ROOT / "jarvis-canvas/client/static/js/canvas.js").read_text()
    assert template.index('/static/js/property-report.js') < template.index('/static/js/canvas.js')
    assert '/static/css/property-report.css' in template
    assert code.index('window.CanvasPropertyReport?.hydrate(pageView);') < code.index("pageView.querySelectorAll('pre code')")


@pytest.mark.parametrize("view", ["cards", "table"])
def test_browser_print_expands_all_filtered_sorted_rows_and_restores_exact_page_and_view(view):
    run_report("const chosenView=" + json.dumps(view) + ";\n" + r"""
const data=snapshot(),original=JSON.stringify(data),element=report.buildReport(data);mounted.push(element);
const city=control(element,'Filter listings by city'),sort=control(element,'Sort listings'),
 search=control(element,'Search property listings'),view=control(element,'Listings view');
city.value='Albany';city.events.change();search.value='97321';search.events.input();
sort.value='price_down';sort.events.change();view.value=chosenView;view.events.change();
const next=all(element).find(el=>el.tag==='button'&&el.textContent==='Next listings');next.events.click();
const before=element.textContent;
assert.ok(before.includes('Showing 25–48 of 84 matching listing rows'));
const displayed=()=>chosenView==='cards'?byClass(element,'property-report-card')
 :all(byClass(element,'property-report-table')[0]).find(el=>el.tag==='tbody').children;
assert.equal(displayed().length,24);
windowEvents.beforeprint();
assert.equal(displayed().length,84);
assert.ok(displayed()[0].textContent.includes('84 Example Street'));
assert.ok(displayed()[83].textContent.includes('1 Example Street'));
assert.ok(element.textContent.includes('Printing all 84 matching listing rows'));
assert.ok(element.textContent.includes('City: Albany. Search: 97321.'));
windowEvents.beforeprint(); // Duplicate browser notification must not replace the saved state.
city.value='Lebanon';sort.value='newest';search.value='';view.value=chosenView==='cards'?'table':'cards';
windowEvents.afterprint();
assert.equal(city.value,'Albany');assert.equal(sort.value,'price_down');
assert.equal(search.value,'97321');assert.equal(view.value,chosenView);
assert.equal(displayed().length,24);
assert.equal(element.textContent,before);
windowEvents.afterprint();assert.equal(element.textContent,before);
assert.equal(JSON.stringify(data),original);
""")


def test_print_bounds_and_empty_filtered_results_keep_saved_data_intact():
    run_report(r"""
const data=snapshot();data.items=Array.from({length:2000},(_,index)=>row(index+1));
const element=report.buildReport(data);mounted.push(element);
windowEvents.beforeprint();assert.equal(byClass(element,'property-report-card').length,2000);
windowEvents.afterprint();assert.equal(byClass(element,'property-report-card').length,24);
const search=control(element,'Search property listings');search.value='No matching address';search.events.input();
const before=element.textContent;
windowEvents.beforeprint();assert.equal(byClass(element,'property-report-card').length,0);
assert.ok(element.textContent.includes('No listings match these local filters'));
windowEvents.afterprint();assert.equal(element.textContent,before);assert.equal(data.items.length,2000);
""")


def test_reports_keep_native_fetched_counts_and_unsupported_rows_distinct_from_listings():
    run_report(r"""
const data=snapshot();
data.coverage={returned_count:116,fetched_count:119,unrecognized_count:3,total_items:140,offset:24,complete:false};
const element=report.buildReport(data),content=element.textContent;
for(const value of ['116 saved listing rows','119 fetched','140 items in the source dataset',
 'Saved source records start at offset 24 (counted from zero).',
 'Dataset coverage is partial or unknown','3 fetched records were not recognized as property listings',
 'excluded from this report','Original records remain in the retained source archive']) assert.ok(content.includes(value),value);
assert.ok(!content.includes('119 saved listing rows'));
const allUnsupported={...data,items:[],coverage:{returned_count:0,fetched_count:2,unrecognized_count:2,total_items:2,offset:0,complete:true}};
const empty=report.buildReport(allUnsupported);
assert.ok(empty.textContent.includes('0 saved listing rows'));
assert.ok(empty.textContent.includes('2 fetched records were not recognized'));
assert.ok(empty.textContent.includes('Fetched results cover the source dataset'));
assert.equal(byClass(empty,'property-report-card').length,0);
const aggregate={...data,coverage:{...data.coverage,offset:null}};
const aggregateContent=report.buildReport(aggregate).textContent;
assert.ok(aggregateContent.includes('119 fetched'));
assert.ok(aggregateContent.includes('No single starting offset: combined datasets or unknown position.'));
assert.ok(!aggregateContent.includes('start at offset 0'));
const unknownTotal={...data,coverage:{...data.coverage,total_items:null}};
assert.ok(report.buildReport(unknownTotal).textContent.includes('start at offset 24'));
for(const coverage of [{...data.coverage,fetched_count:116},{...data.coverage,unrecognized_count:-1},
 {...data.coverage,returned_count:3,fetched_count:6}]) assert.throws(()=>report.buildReport({...data,coverage}));
const legacy=snapshot(),legacyContent=report.buildReport(legacy).textContent;
assert.ok(legacyContent.includes('116 fetched'));
assert.ok(legacyContent.includes('Saved source records start at offset 0 (counted from zero).'));
delete legacy.coverage.offset;
assert.ok(report.buildReport(legacy).textContent.includes('No single starting offset'));
""")
