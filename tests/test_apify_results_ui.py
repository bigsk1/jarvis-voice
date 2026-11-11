"""Apify's shipped Web adapter keeps real listing fields usable and pages saved evidence."""

from test_web_assistant_message_rendering import run_message_browser
from test_web_continuation_rendering import DOM

FIXTURES = r"""
const renderer = sandbox.window.structuredResultsRenderer;
const nativeListing = index => ({
  availabilityDate: null, bathrooms: 2, bedrooms: 3, cardType:'property',
  coordinates:{latitude:1,longitude:2}, daysOnZillow:0, factsAndFeatures:{hasPool:false},
  homeType:'SINGLE_FAMILY', listingAddress:{full:`${index} Example Street`,city:'Example',state:'CA',zipCode:'90000'},
  listingPrice:{amount:410000,currency:'USD',formatted:'$410,000'}, listingStatus:'forSale',
  livingArea:1400,livingAreaUnit:'sqft',mainImage:'https://photos.zillowstatic.com/example.jpg',
  propertyUrl:`https://www.zillow.com/homedetails/${index}_zpid/`,zpid:String(index),
});
const canonicalListing = index => ({kind:'property_listing',source:'zillow',listing_id:String(index),
  address:`${index} Canonical Street`,price:410000,currency:'USD',listing_status:'for_sale',
  property_type:'single_family',bedrooms:3,bathrooms:2,area:1400,area_unit:'sqft',
  days_on_zillow:0,url:`https://www.zillow.com/homedetails/${index}_zpid/`,
});
const envelope = (rows, overrides={}) => ({contract:'external_result_v1',
  source:{provider:'apify',tool:'apify_read_result',mode:'cloud'},
  execution:{run_id:'NativeRun123',actor_id:'NativeActor123',status:'SUCCEEDED'},
  result:{kind:'dataset',dataset_id:'NativeDataset123',sample_items:rows,offset:0,
    returned_count:100,total_items:150,complete:false,
    presentation:{kind:'property_listings',source:'zillow'},
    pagination:{has_more:true,next_offset:100}},
  raw_ref:'stash://space_apify/f_page',limits:{sample_truncated:true},...overrides,
});
"""


def test_native_zillow_and_canonical_property_cards_expose_useful_fields_safely():
    run_message_browser(FIXTURES + r"""
const native=nativeListing(1), before=JSON.stringify(native);
const legacy=envelope([native]); delete legacy.result.presentation;
const html=renderer.render({apify_read_result:legacy});
for(const value of ['Zillow property listings','1 Example Street','$410,000','For sale',
  '3 beds','2 baths','1,400 sqft','0 days on Zillow','View on Zillow',
  'https://photos.zillowstatic.com/example.jpg','100 fetched','150 items in dataset',
  'Showing 1 listing','Dataset coverage is partial','Browse saved page','offset 100',
  'Search filters and availability are not independently verified',
  '/api/stash/space_apify/f_page?mode=cloud']) assert.ok(html.includes(value),value);
assert.equal(JSON.stringify(native),before);
assert.ok(!html.includes('external-result-table'));
assert.ok(!html.includes('{5 fields}'));
assert.ok(html.includes('loading="lazy"'));
assert.ok(html.includes('referrerpolicy="no-referrer"'));
assert.ok(!html.includes('Inspect preview JSON'));

const malicious=canonicalListing(2);
Object.assign(malicious,{address:'<img src=x onerror=alert(1)>',price_text:'<script>alert(2)</script>',
  url:'javascript:alert(3)',image_url:'https://evil.invalid/tracker.jpg'});
const safe=renderer.render({apify_read_result:envelope([malicious])});
assert.ok(safe.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert.ok(safe.includes('&lt;script&gt;alert(2)&lt;/script&gt;'));
for(const value of ['<script>','<img src=x','href="javascript:','src="https://evil.invalid']) assert.ok(!safe.includes(value),value);

const redfin={...canonicalListing(3),source:'redfin',address:'A Redfin property',bedrooms:0,
  bathrooms:0,area:null,price:0,days_on_zillow:null,url:'https://www.redfin.com/CA/Example/home/3'};
const redfinPayload=envelope([redfin]); redfinPayload.result.presentation.source='redfin';
const redfinHtml=renderer.render({apify_read_result:redfinPayload});
for(const value of ['Redfin property listings','A Redfin property','0 beds','0 baths','$0','View on Redfin']) assert.ok(redfinHtml.includes(value),value);
assert.ok(!redfinHtml.includes('days on Zillow'));
assert.ok(!redfinHtml.includes('0 sqft'));
const noPrice=nativeListing(4); delete noPrice.listingPrice;
assert.ok(renderer.render({apify_read_result:envelope([noPrice])}).includes('Price not provided'));
""")


def test_lifecycle_and_generic_actor_output_keep_distinct_truthful_surfaces():
    run_message_browser(FIXTURES + r"""
const running=envelope(undefined);
running.result={kind:'object',complete:false,value:{status_message:'Actor is still working',started_at:'2026-11-10T12:00:00Z'}};
running.execution.status='RUNNING';
const html=renderer.render({apify_read_result:running});
for(const value of ['Apify run','RUNNING','output is not complete','Actor is still working',
  'Run details','NativeRun123','2026-11-10T12:00:00Z']) assert.ok(html.includes(value),value);
assert.ok(!html.includes('No result preview available'));
assert.ok(!html.includes('Browse saved page'));
const arbitrary=envelope([{product:'An arbitrary actor result',nested:{score:0}}]);
delete arbitrary.result.presentation;
const generic=renderer.render({apify_read_result:arbitrary});
assert.ok(generic.includes('external-result-table'));
assert.ok(generic.includes('An arbitrary actor result'));
assert.ok(!generic.includes('property-grid'));
const noMode=envelope([canonicalListing(1)]); delete noMode.source.mode;
const noModeHtml=renderer.render({apify_read_result:noMode});
assert.ok(!noModeHtml.includes('Browse saved page'));
assert.ok(!noModeHtml.includes('/api/stash/'));
""")


def test_property_results_preserve_foreground_call_occurrences_and_exact_row_positions():
    run_message_browser(FIXTURES + r"""
const first=envelope([canonicalListing(1)]), next=envelope([canonicalListing(2)]);
next.result.offset='9007199254740993';
const html=renderer.render({apify_read_result:[first,next],_tool_trace:[
  {tool:'apify_read_result',ok:true},{tool:'apify_read_result',ok:false},{tool:'apify_read_result',ok:true}
]});
assert.ok(html.includes('data-orchestration-call="3"'));
assert.ok(html.includes('data-orchestration-occurrence="2"'));
assert.ok(html.includes('#9007199254740994'));
assert.ok(!html.includes('#9007199254740992'));
assert.ok(html.indexOf('1 Canonical Street')<html.indexOf('2 Canonical Street'));
""")


def test_property_continuations_use_safe_dom_and_original_saved_mode():
    run_message_browser(DOM + FIXTURES + r"""
const ui=chat(), row=canonicalListing(1);
row.address='<script>untrusted address</script>';
row.url='https://www.zillow.com/homedetails/1_zpid/?x=1&y=2';
const payload=envelope([row]); payload.source.mode='local';
sandbox.window.jarvisSocket.mode='cloud';
ui.addAssistantMessage('Saved result',[],{_kind:'continuation',_background_mode:'local',apify_read_result:payload});
const rendered=message(ui), all=descendants(rendered), content=visible(rendered);
assert.equal(rendered.querySelectorAll('.structured-results-apify').length,1);
assert.ok(content.includes('<script>untrusted address</script>'));
assert.ok(!all.some(el=>el.tag==='script'));
assert.ok(all.some(el=>el.tag==='a'&&el.href==='/api/stash/space_apify/f_page?mode=local'));
assert.ok(all.some(el=>el.tag==='a'&&el.href===row.url));
assert.ok(all.some(el=>el.tag==='button'&&el.textContent==='Browse saved page'));
assert.ok(!effects.some(e=>e==='clear-actions'||e==='hydrate'));
""")


SAVED_BROWSER = DOM + FIXTURES + r"""
Element.prototype.replaceChildren=function(...children){this.children=[];this._text='';children.forEach(child=>this.appendChild(child));};
const section=renderer._externalNodeDom(renderer._externalCollectionModel(envelope([canonicalListing(1)])));
// The minimal DOM shim stores attributes literally rather than maintaining the
// browser's reflected dataset object.
Object.assign(section.dataset,{apifyRawRef:section['data-apify-raw-ref'],apifyMode:section['data-apify-mode'],
  apifySource:section['data-apify-source'],apifyRunId:section['data-apify-run-id'],apifyDatasetId:section['data-apify-dataset-id']});
const browse=section.querySelector('.apify-browse-saved');
const saved=section.querySelector('.apify-saved-page');
function press(button){button.closest=()=>section;return renderer._apifyAdapter.handleClick({target:{closest:()=>button}});}
const wait=()=>new Promise(resolve=>setImmediate(resolve));
const archivedRows=Array.from({length:100},(_,index)=>canonicalListing(index+1));
let fetches=0;
Utils.auth.fetch=async(href,options)=>{
  fetches++;
  assert.equal(href,'/api/stash/space_apify/f_page?mode=cloud');
  assert.equal(options.redirect,'error');
  return {ok:true,headers:{get:()=>null},text:async()=>JSON.stringify({
    run:{id:'NativeRun123'},dataset:{id:'NativeDataset123'},offset:0,
    items:archivedRows.map((_,index)=>nativeListing(index+1)),
    presentation:{kind:'property_listings',source:'zillow',items:archivedRows}
  })};
};
"""


def test_saved_page_browsing_uses_one_authenticated_local_read_for_all_fetched_rows():
    run_message_browser(SAVED_BROWSER + r"""
assert.equal(press(browse),true); await wait();
assert.equal(fetches,1);
assert.ok(visible(saved).includes('rows 1–12 of 100 fetched rows'));
assert.ok(visible(saved).includes('12 Canonical Street'));
assert.ok(!visible(saved).includes('13 Canonical Street'));
assert.ok(visible(saved).includes('No new Apify request'));
press(section.querySelector('.apify-saved-next'));
assert.ok(visible(saved).includes('rows 13–24 of 100 fetched rows'));
assert.ok(visible(saved).includes('13 Canonical Street'));
assert.ok(!visible(saved).includes('12 Canonical Street'));
for(let index=0;index<7;index++) press(section.querySelector('.apify-saved-next'));
assert.ok(visible(saved).includes('rows 97–100 of 100 fetched rows'));
assert.ok(visible(saved).includes('100 Canonical Street'));
assert.equal(section.querySelector('.apify-saved-next').disabled,'');
press(section.querySelector('.apify-saved-previous'));
assert.ok(visible(saved).includes('rows 85–96 of 100 fetched rows'));
press(browse); await wait();
assert.equal(fetches,1,'Saved navigation must never call Apify, the model, or refetch the archive');
""")


def test_saved_page_rejects_wrong_run_dataset_and_oversized_or_missing_archives():
    run_message_browser(SAVED_BROWSER + r"""
Utils.auth.fetch=async()=>({ok:true,headers:{get:()=>null},text:async()=>JSON.stringify({
  run:{id:'WrongRun'},dataset:{id:'NativeDataset123'},offset:0,items:[nativeListing(1)]})});
press(browse); await wait();
assert.ok(visible(saved).includes('does not match the saved run and dataset'));
assert.equal(saved.querySelectorAll('.apify-property-card').length,0);
Utils.auth.fetch=async()=>({ok:true,headers:{get:()=>String(9*1024*1024)},text:async()=>{throw new Error('Must not read oversized data');}});
press(browse); await wait();
assert.ok(visible(saved).includes('8 MiB browser limit'));
Utils.auth.fetch=async()=>({ok:false});
press(browse); await wait();
assert.ok(visible(saved).includes('unavailable or expired'));
assert.equal(browse.disabled,false);
""")


def test_legacy_saved_native_rows_browse_without_canonical_presentation():
    run_message_browser(SAVED_BROWSER + r"""
Utils.auth.fetch=async()=>({ok:true,headers:{get:()=>null},text:async()=>JSON.stringify({
  run:{id:'NativeRun123'},dataset:{id:'NativeDataset123'},offset:50,
  items:Array.from({length:20},(_,index)=>nativeListing(index+51))})});
press(browse); await wait();
assert.ok(visible(saved).includes('51 Example Street'));
assert.ok(visible(saved).includes('#51'));
assert.ok(visible(saved).includes('rows 1–12 of 20 fetched rows'));
press(section.querySelector('.apify-saved-next'));
assert.ok(visible(saved).includes('70 Example Street'));
assert.ok(visible(saved).includes('#70'));
""")


def test_unavailable_property_photos_have_inert_fallbacks():
    run_message_browser(DOM + FIXTURES + r"""
const row=canonicalListing(1); row.image_url='https://photos.zillowstatic.com/photo.jpg';
const model=renderer._externalCollectionModel(envelope([row]));
const section=renderer._externalNodeDom(model), image=section.querySelector('.apify-property-image');
const fallback=section.querySelector('.apify-property-image-fallback');
image.matches=selector=>selector==='.apify-property-image';
renderer._apifyAdapter.handleImageError({target:image});
assert.equal(image.hidden,true); assert.equal(fallback.hidden,false);
assert.equal(fallback.textContent,'Photo unavailable');
for(const unsafe of ['http://photos.zillowstatic.com/photo.jpg','https://photos.zillowstatic.com/file.svg',
  'https://zillowstatic.com.evil.invalid/photo.jpg','data:image/svg+xml,<svg/>']) {
  row.image_url=unsafe;
  const html=renderer.render({apify_read_result:envelope([row])});
  assert.ok(!html.includes('class="apify-property-image"'));
  assert.ok(html.includes('No photo provided'));
}
""")


def test_shorter_mixed_page_presentation_browses_valid_listings_with_explicit_exclusions():
    run_message_browser(SAVED_BROWSER + r"""
Utils.auth.fetch=async()=>({ok:true,headers:{get:()=>null},text:async()=>JSON.stringify({
  run:{id:'NativeRun123'},dataset:{id:'NativeDataset123'},offset:0,
  items:[nativeListing(1),{error:'unsupported record'},nativeListing(3)],
  presentation:{kind:'property_listings',source:'zillow',items:[canonicalListing(1),canonicalListing(3)],input_count:3,unrecognized_count:1}
})});
press(browse);await wait();
assert.equal(saved.querySelectorAll('.apify-property-card').length,2);
assert.ok(visible(saved).includes('2 recognized listings from 3 fetched records'));
assert.ok(visible(saved).includes('1 unsupported or error record is excluded'));
assert.ok(visible(saved).includes('3 Canonical Street'));
assert.ok(!visible(saved).includes('3 Example Street'));
assert.ok(!visible(saved).includes('presentation does not match'));
const payload=envelope([canonicalListing(1),canonicalListing(3)]);
Object.assign(payload.result,{returned_count:3,total_items:3,complete:true});
Object.assign(payload.result.presentation,{input_count:3,unrecognized_count:1});
const html=renderer.render({apify_read_result:payload});
for(const value of ['3 fetched','2 recognized listings','1 fetched record could not be recognized',
 'excluded from listing cards','Fetched page covers the complete dataset']) assert.ok(html.includes(value),value);
""")


def test_empty_recognized_page_and_inconsistent_new_counts_are_not_misrepresented():
    run_message_browser(SAVED_BROWSER + r"""
Utils.auth.fetch=async()=>({ok:true,headers:{get:()=>null},text:async()=>JSON.stringify({
  run:{id:'NativeRun123'},dataset:{id:'NativeDataset123'},offset:0,items:[{error:'unsupported record'}],
  presentation:{kind:'property_listings',source:'zillow',items:[],input_count:1,unrecognized_count:1}
})});
press(browse);await wait();
assert.ok(visible(saved).includes('0 recognized listings from 1 fetched record'));
assert.ok(visible(saved).includes('Page 1 of 1'));
assert.equal(saved.querySelectorAll('.apify-property-card').length,0);
const invalid={...envelope([canonicalListing(2)]),raw_ref:'stash://space_apify/f_other'};
const section2=renderer._externalNodeDom(renderer._externalCollectionModel(invalid));
Object.assign(section2.dataset,{apifyRawRef:section2['data-apify-raw-ref'],apifyMode:section2['data-apify-mode'],
 apifySource:section2['data-apify-source'],apifyRunId:section2['data-apify-run-id'],apifyDatasetId:section2['data-apify-dataset-id']});
Utils.auth.fetch=async()=>({ok:true,headers:{get:()=>null},text:async()=>JSON.stringify({
 run:{id:'NativeRun123'},dataset:{id:'NativeDataset123'},items:[nativeListing(1),{error:'unsupported'}],
 presentation:{kind:'property_listings',source:'zillow',items:[canonicalListing(1)],input_count:2,unrecognized_count:0}})});
const button=section2.querySelector('.apify-browse-saved');button.closest=()=>section2;
renderer._apifyAdapter.handleClick({target:{closest:()=>button}});await wait();
assert.ok(visible(section2.querySelector('.apify-saved-page')).includes('does not match its fetched record counts'));
""")
