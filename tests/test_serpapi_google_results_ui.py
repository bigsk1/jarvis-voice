"""Google's retained panels remain readable in live, saved and late Web responses."""

from test_web_assistant_message_rendering import run_message_browser
from test_web_continuation_rendering import DOM

FIXTURES = r"""
const renderer=sandbox.window.structuredResultsRenderer;
const google=(panels, extra={})=>({contract:'external_result_v1',
  source:{provider:'serpapi',tool:'serpapi_google_search',mode:'local'},
  execution:{status:'Success',search_id:'private-search-id'},
  result:{kind:'google_search',query:'star wars watch online',searched_at:'2026-11-11 09:25:14 UTC',
    request:{country:'us',language:'en',location:'Portland, Oregon',device:'desktop'},
    search_url:'https://www.google.com/search?q=star+wars+watch+online',panels,...extra},
  raw_ref:'stash://space_google/f_search',artifacts:[],limits:{truncated:false}});
const panel=(key, preview, extra={})=>({key,path:'/'+key,
  type:Array.isArray(preview)?'array':preview!==null&&typeof preview==='object'?'object':'scalar',
  count:Array.isArray(preview)?preview.length:preview&&typeof preview==='object'?Object.keys(preview).length:1,
  preview,preview_count:Array.isArray(preview)?preview.length:1,truncated:false,...extra});
const watch=panel('available_on',[
  {name:'Disney+',link:'https://www.disneyplus.com/example',price:'Subscription'},
  {name:'Philo',link:'https://www.philo.com/example',price:'Subscription'},
  {name:'Sling TV',link:'https://watch.sling.com/example',price:'Subscription (Requires add-on)'},
  {name:'YouTube',link:'https://www.youtube.com/watch?v=example',price:'From $3.99'},
  {name:'Google Play Movies & TV',link:'https://play.google.com/example',price:'From $3.99'},
  {name:'Fandango',link:'https://www.fandango.com/example',price:'From $3.99'},
  {name:'Amazon Prime Video',link:'https://www.amazon.com/example',price:'From $3.99'},
  {name:'Apple TV',link:'https://tv.apple.com/example',price:'$19.99'},
]);
const entity=panel('knowledge_graph',{title:'Star Wars: Episode IV – A New Hope',
  type:'PG 1977 · Sci-fi/Action · 2h 1m',release_date:'May 25, 1977 (USA)',
  director:'George Lucas',kgmid:'/m/private-id',description:'An independently identified film.'});
const sources=panel('organic_results',Array.from({length:10},(_,i)=>({position:i+1,
  title:'Source '+(i+1),link:'https://example.org/source/'+(i+1),
  displayed_link:'example.org',snippet:'Evidence snippet '+(i+1)})));
"""

EPISODES = r"""
// SerpApi's documented episode_guide is a direct array. Mobile rows omit
// desktop link/snippet/duration fields; those missing values must remain absent.
const episodes=panel('episode_guide',[
  {position:1,title:'S1 E1 · Pilot',link:'https://www.google.com/search?q=first+episode',
    snippet:'An episode summary.',thumbnail:'https://encrypted-tbn0.gstatic.com/images?q=pilot',
    duration:'45 min',date:'Jan 20, 2008',available_on:[{name:'Netflix',link:'https://www.netflix.com/watch/example'}]},
  {position:2,title:'2. Cat\'s in the Bag...',thumbnail:'https://encrypted-tbn0.gstatic.com/images?q=second',date:'Jan 27, 2008'},
  {position:3,title:'A result without a photo',link:'https://example.org/third',snippet:'No thumbnail was provided.'},
]);
"""


def test_native_episode_rows_share_generic_cards_keep_extra_fields_and_google_closed():
    run_message_browser(FIXTURES + EPISODES + r"""
const payload=google([episodes,sources]), before=JSON.stringify(payload);
const html=renderer.render({serpapi_google_search:payload});
assert.equal((html.match(/class="google-serp-source google-serp-named-result"/g)||[]).length,3);
assert.equal((html.match(/class="google-serp-source"/g)||[]).length,10);
assert.equal((html.match(/class="google-serp-image"/g)||[]).length,2);
for(const value of ['Episode Guide','S1 E1 · Pilot','45 min','Jan 20, 2008','Jan 27, 2008',
  'An episode summary.','3 results shown of 3','Additional section details','available_on','Netflix'])
  assert.ok(html.includes(value),value);
assert.ok(!/<details[^>]*structured-results-google[^>]* open>/.test(html));
assert.ok(!/<details[^>]*google-serp-other-panel[^>]* open>/.test(html));
assert.ok(html.includes('loading="lazy"')&&html.includes('referrerpolicy="no-referrer"'));
assert.equal(JSON.stringify(payload),before);
""")


def test_future_named_result_shapes_are_bounded_and_unfamiliar_leftovers_remain_inspectable():
    run_message_browser(FIXTURES + r"""
const future=panel('future_discoveries',[
  {title:'A future result',link:'https://example.org/future',snippet:'Preserved snippet',
    thumbnail:'https://example.org/future.jpg',duration:'5 min',date:'Today',extra:{score:0}},
  {name:'A named source',url:'https://example.org/named',duration:500,other:{enabled:false}},
  {title:'Unfamiliar data',settings:{mode:'retained'}},42,
]);
const html=renderer.render({serpapi_google_search:google([future])});
assert.equal((html.match(/class="google-serp-source google-serp-named-result"/g)||[]).length,2);
for(const value of ['Future Discoveries','Preserved snippet','5 min','Today','2 results shown of 4',
  'Additional section details','additional_result_fields','unrecognized_items','Unfamiliar data','duration','500'])
  assert.ok(html.includes(value),value);
const wrapped=renderer.render({serpapi_google_search:google([panel('future_group',{
  results:[{title:'Wrapped result',url:'https://example.org/wrapped'}],category:'Native category',
})])});
assert.ok(wrapped.includes('1 results shown of 1'));
assert.ok(wrapped.includes('Native category'));
const arbitrary=renderer.render({serpapi_google_search:google([
  panel('configuration',[{title:'Configuration',settings:{private:false}}]),
  panel('deep_wrapper',{nested:{results:[{title:'Deep data',link:'https://example.org/deep'}]}}),
])});
assert.ok(!arbitrary.includes('class="google-serp-source google-serp-named-result"'));
const many=renderer.render({serpapi_google_search:google([panel('future_rows',
  Array.from({length:30},(_,i)=>({title:'Future '+(i+1),url:'https://example.org/'+i})))])});
assert.equal((many.match(/class="google-serp-source google-serp-named-result"/g)||[]).length,20);
assert.ok(many.includes('20 results shown of 30'));
assert.ok(!many.includes('Future 21'));
""")


def test_shared_thumbnails_and_distinct_site_icon_fallback_use_only_provided_safe_urls():
    run_message_browser(FIXTURES + r"""
const metadata=panel('knowledge_graph',{title:'Provided entity',
  header_images:[{image:'https://images.example/entity.jpg'}]});
const organicImages=panel('organic_results',[
  {title:'Content image',link:'https://example.org/one',thumbnail:'https://images.example/content.jpg',favicon:'https://images.example/not-needed.png'},
  {title:'Site identity',link:'https://example.org/two',favicon:'https://images.example/favicon.svg'},
  {title:'Other site identity',link:'https://example.org/three',source_icon:'https://images.example/source-icon.svgz'},
  {title:'No provided media',link:'https://example.org/four'},
]);
const offer=panel('available_on',[{name:'Provider',image:'http://images.example/provider.png',price:'Subscription'}]);
const html=renderer.render({serpapi_google_search:google([metadata,organicImages,offer])});
assert.equal((html.match(/class="google-serp-thumbnail"/g)||[]).length,3);
assert.equal((html.match(/class="google-serp-site-icon"/g)||[]).length,2);
assert.equal((html.match(/class="google-serp-image"/g)||[]).length,5);
assert.ok(!html.includes('not-needed.png'));
assert.ok(html.includes('width="20" height="20"'));
assert.ok(html.includes('src="https://images.example/favicon.svg"'));
assert.ok(html.includes('src="https://images.example/source-icon.svgz"'));
for(const safe of ['https://images.example/thumbnail.svg','http://images.example/thumbnail.SVGZ?size=small']) {
  const supplied=renderer.render({serpapi_google_search:google([
    panel('future_images',[{title:'Provided SVG image',url:'https://example.org',thumbnail:safe}]),
    panel('knowledge_graph',{title:'Provided SVG entity',thumbnail:safe}),
  ])});
  assert.equal((supplied.match(/class="google-serp-image"/g)||[]).length,2);
  assert.equal(supplied.split('src="'+safe+'"').length-1,2);
  assert.ok(supplied.includes('loading="lazy"')&&supplied.includes('referrerpolicy="no-referrer"'));
  assert.ok(!/<details[^>]*structured-results-google[^>]* open>/.test(supplied));
}
for(const bad of ['javascript:alert(1)','data:image/svg+xml,<svg/>','file:///private/image.jpg',
  'ftp://images.example/photo.svg','https://user:secret@example.org/photo.jpg',
  'https://user@example.org/photo.svg','https://:secret@example.org/photo.svg',
  '//images.example/photo.svg','not a URL','<svg onload="alert(1)">',null,{image:'https://images.example/photo.svg'}]) {
  const unsafe=renderer.render({serpapi_google_search:google([
    panel('future_images',[{title:'Safe title',url:'https://example.org',thumbnail:bad}]),
    panel('knowledge_graph',{title:'Safe entity',thumbnail:bad}),
  ])});
  assert.ok(!unsafe.includes('class="google-serp-image"'),String(bad));
}
""")


def test_generic_photos_survive_live_saved_and_late_rendering_and_hide_on_failure():
    run_message_browser(FIXTURES + EPISODES + r"""
for(const live of [true,false]) {
  const html=render(chat(),'Episode results.',['serpapi_google_search'],{serpapi_google_search:google([episodes,sources])},live);
  assert.equal((html.match(/class="google-serp-image"/g)||[]).length,2);
  assert.ok(!/<details[^>]*structured-results-google[^>]* open>/.test(html));
}
""" + DOM + r"""
for(const form of ['live','saved','nested']) {
  const ui=chat(),payload={serpapi_google_search:Array.from({length:3},()=>google([episodes,sources])),
    _tool_trace:[{tool:'serpapi_google_search',ok:true}]};
  ui.addAssistantMessage('Saved episodes.',[],lateData(payload,form),form==='live'?{late:true}:{});
  const output=message(ui), sections=output.querySelectorAll('.structured-results-google');
  assert.equal(sections.length,3);
  assert.ok(sections.every(section=>section.open===undefined));
  const images=descendants(output).filter(el=>el.tag==='img');
  assert.equal(images.length,6);
  assert.ok(images.every(image=>image.loading==='lazy'&&image.referrerpolicy==='no-referrer'));
  const image=images[0]; image.matches=selector=>selector==='.google-serp-image';
  const failed=new Event('error');Object.defineProperty(failed,'target',{value:image});
  sandbox.document.dispatchEvent(failed);
  assert.equal(image.hidden,true);
  assert.equal(image.parentElement.hidden,true);
  assert.equal(images[1].hidden,undefined,'One broken image must not hide its siblings');
}
""")


def test_watch_entity_and_all_ten_organic_sources_render_without_five_row_loss():
    run_message_browser(FIXTURES + r"""
const payload=google([watch,entity,sources]), before=JSON.stringify(payload);
const html=renderer.render({serpapi_google_search:payload});
assert.equal((html.match(/class="google-serp-offer"/g)||[]).length,8);
assert.equal((html.match(/class="google-serp-source"/g)||[]).length,10);
for(const value of ['Where to watch','Star Wars: Episode IV – A New Hope','1977','Apple TV',
  '$19.99','Subscription (Requires add-on)','From $3.99','8 offers shown of 8',
  '10 sources shown of 10','Source 10','Evidence snippet 10','Portland, Oregon','US · EN · desktop',
  'individual web sources can refer to other titles','/api/stash/space_google/f_search?mode=local'])
  assert.ok(html.includes(value),value);
assert.ok(!/<details[^>]*structured-results-google[^>]* open>/.test(html));
assert.ok(!html.includes('private-search-id'));
assert.ok(!html.includes('/m/private-id'));
assert.ok(!html.includes('external-result-table'));
assert.equal(JSON.stringify(payload),before);
const live=render(chat(),'Found these options.',['serpapi_google_search'],{serpapi_google_search:payload});
const saved=render(chat(),'Found these options.',['serpapi_google_search'],{serpapi_google_search:payload},false);
assert.equal((live.match(/class="google-serp-offer"/g)||[]).length,8);
assert.equal((saved.match(/class="google-serp-offer"/g)||[]).length,8);
""")


def test_panel_only_results_and_bounded_unknown_sections_remain_visible_and_truthful():
    run_message_browser(FIXTURES + r"""
const knowledge=renderer.render({serpapi_google_search:google([entity])});
assert.ok(knowledge.includes('Star Wars: Episode IV'));
assert.ok(!/<details[^>]*structured-results-google[^>]* open>/.test(knowledge));
const unknown=renderer.render({serpapi_google_search:google([
  panel('future_panel',{measurement:0,enabled:false,precise:'Native data & meaning'}, {truncated:true}),
])});
assert.ok(!/<details[^>]*structured-results-google[^>]* open>/.test(unknown));
assert.ok(unknown.includes('Future Panel · 3 fields'));
assert.ok(unknown.includes('Native data &amp; meaning'));
assert.ok(unknown.includes('Saved section: /future_panel'));
assert.ok(!/<details[^>]*google-serp-other-panel[^>]* open>/.test(unknown));
const long=panel('organic_results',Array.from({length:30},(_,i)=>({title:'Source '+(i+1),link:'https://example.org/'+i})),
  {count:100,truncated:true});
const bounded=renderer.render({serpapi_google_search:google([long],{has_more:true})});
assert.equal((bounded.match(/class="google-serp-source"/g)||[]).length,20);
assert.ok(bounded.includes('20 sources shown of 100'));
assert.ok(bounded.includes('Preview shortened'));
assert.ok(bounded.includes('More rows are available in this saved section'));
assert.ok(!bounded.includes('Source 21'));
""")


def test_native_flight_dates_airport_offsets_and_actual_source_are_readable():
    run_message_browser(FIXTURES + r"""
const native=panel('flight_result',{airline:'United',airline_iata_code:'UA',
  available_dates:['2026-11-11','2026-11-12'],dates:[
    {date:'2026-11-11',metadata:{origin:'SYD',destination:'IAH',status:'IN_AIR_ARRIVING_DELAYED',
      departure_delay:0,arrival_delay:23},flight_designator:'UA 100',status:'Arriving late',duration:963,
      departure_airport:{id:'SYD',city:'Sydney',time:'2026-11-11T09:15:00.000+11:00',
        time_label:'9:15 AM',scheduled_time:'2026-11-11T09:15:00.000+11:00',terminal:'1',gate:'50',status:'Departed'},
      arrival_airport:{id:'IAH',city:'Houston',time:'2026-11-11T08:18:00.000-06:00',
        time_label:'8:18 AM',scheduled_time:'2026-11-11T07:55:00.000-06:00',scheduled_time_label:'7:55 AM',
        terminal:'E',gate:'E7',status:'Estimated arrival'},source:'OAG',
      source_url:'https://www.flightview.com/flight-tracker/UA/100',updated_at:'2026-11-11T07:12:34.115Z'},
    {date:'2026-11-12',metadata:{origin:'SYD',destination:'IAH',status:'DEPARTING_ON_TIME',
      departure_delay:0,arrival_delay:0}},
  ]});
const html=renderer.render({serpapi_google_search:google([native],{query:'UA100 flight status'})});
assert.equal((html.match(/class="google-serp-flight"/g)||[]).length,2);
for(const value of ['UA 100','United','Sydney · SYD','Houston · IAH','9:15 AM · UTC+11:00',
  '8:18 AM · UTC-06:00','Scheduled: 2026-11-11 7:55 AM · UTC-06:00',
  'Gate E7','OAG','Arriving late','Departing On Time','16h 3m','Departure delay: 0 min','Arrival delay: 23 min',
  'https://www.flightview.com/flight-tracker/UA/100']) assert.ok(html.includes(value),value);
assert.ok(!html.includes('Cirium'));
assert.ok(!html.includes('IN_AIR_ARRIVING_DELAYED'));
assert.ok(!html.includes('9:15 AM: 2026'));
assert.equal((html.match(/>16h 3m</g)||[]).length,1);
""")


def test_flight_duration_prefers_provider_labels_formats_minutes_and_omits_malformed_values():
    run_message_browser(FIXTURES + r"""
const renderDuration=fields=>renderer.render({serpapi_google_search:google([
  panel('flight_result',{dates:[{date:'2026-11-11',status:'In flight',...fields}]}),
])});
for(const [fields,expected] of [
  [{duration:963},'16h 3m'],
  [{duration:144,duration_label:'2h 24m'},'2h 24m'],
  [{duration:963,duration_label:'Provider duration label'},'Provider duration label'],
  [{duration:'16 hours 3 minutes'},'16 hours 3 minutes'],
  [{duration:63,duration_label:'   '},'1h 3m'],
  [{duration:60},'1h'],[{duration:59},'59m'],[{duration:0},'0m'],
]) {
  const html=renderDuration(fields);
  const values=[...html.matchAll(/class="google-serp-fact">([^<]*)</g)].map(match=>match[1]);
  assert.deepEqual(values,['In flight',expected]);
}
for(const duration of [-1,1.5,true,false,null,undefined,{},[],NaN,Infinity,Number.MAX_SAFE_INTEGER+1,'   ']) {
  const html=renderDuration({duration,duration_label:{malformed:true}});
  const values=[...html.matchAll(/class="google-serp-fact">([^<]*)</g)].map(match=>match[1]);
  assert.deepEqual(values,['In flight']);
}
const safe=renderDuration({duration:963,duration_label:'<img src=x onerror=alert(1)>'});
assert.ok(safe.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert.ok(!safe.includes('<img'));
assert.ok(!safe.includes('16h 3m'),'The provider label must replace the numeric fallback');
""")


def test_untrusted_panels_cannot_add_markup_urls_images_or_provider_requests():
    run_message_browser(FIXTURES + r"""
sandbox.fetch=async()=>{throw new Error('Google previews must never fetch');};
const attack='<img src=x onerror=alert(1)>', invalid=['javascript:alert(2)','data:text/html,attack','https://user:secret@example.org/private'];
const payload=google([panel('available_on',invalid.map(link=>({name:attack,price:'<script>alert(3)</script>',link}))),
  panel('knowledge_graph',{title:attack,description:'<iframe src=x>',website:'javascript:alert(4)'}),
  panel('organic_results',[{title:attack,link:'javascript:alert(5)',snippet:attack}]),
  panel('unknown_section',{url:'javascript:alert(6)',image:'https://tracking.example/pixel.svg',nested:attack}),
]);
const html=renderer.render({serpapi_google_search:payload});
assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert.ok(html.includes('&lt;script&gt;alert(3)&lt;/script&gt;'));
for(const bad of ['<img','<iframe','<script','href="javascript:','href="data:','href="https://user:','src="https://tracking'])
  assert.ok(!html.includes(bad),bad);
""")


def test_google_sections_default_closed_at_any_call_count_and_preserve_other_tool_cards():
    run_message_browser(FIXTURES + r"""
for(const count of [1,3,4]) {
  const payloads=Array.from({length:count},()=>google([watch]));
  const trace=payloads.map(()=>({tool:'serpapi_google_search',ok:true}));
  trace.push({tool:'tavily_search',ok:true});
  const html=renderer.render({serpapi_google_search:payloads,tavily_search:{query:'Other',results:[{title:'Separate source'}]},_tool_trace:trace});
  const roots=[...html.matchAll(/<details\b[^>]*class="[^"]*structured-results-google[^>]*>/g)].map(match=>match[0]);
  assert.equal(roots.length,count);
  assert.ok(roots.every(root=>!root.includes(' open')));
  assert.ok(/<details[^>]*aria-label="Tavily Search"[^>]* open>/.test(html));
  assert.ok(html.includes('data-orchestration-tool="serpapi_google_search"'));
}
""")


def test_read_result_uses_the_same_panel_model_and_preserves_saved_mode_without_another_call():
    run_message_browser(FIXTURES + DOM + r"""
const payload=google([panel('available_on',watch.preview.slice(6),{count:8,truncated:true})],
  {selected_path:'/available_on',offset:6,returned_count:2,has_more:false});
const html=renderer.render({serpapi_google_search:{ok:true,data:payload}});
assert.ok(html.includes('Amazon Prime Video')&&html.includes('Apple TV'));
assert.ok(html.includes('Offers 7–8 of 8'));
for(const form of ['live','saved','nested']) {
  const ui=chat(), data=lateData({_background_mode:'cloud',serpapi_google_search:payload},form);
  ui.addAssistantMessage('Saved offers.',[],data,form==='live'?{late:true}:{});
  const output=message(ui);
  assert.equal(output.querySelectorAll('.google-serp-offer').length,2);
  assert.ok(visible(output).includes('Apple TV'));
  assert.ok(descendants(output).some(el=>el.tag==='a'&&el.href==='/api/stash/space_google/f_search?mode=local'));
}
""")


def test_saved_offer_pages_show_distinct_ranges_without_relabeling_other_panels():
    run_message_browser(FIXTURES + r"""
const page=offset=>google([
  panel('available_on',watch.preview.slice(offset,offset+4),{count:8,truncated:true}),sources,
],{selected_path:'/available_on',offset,returned_count:4,has_more:offset===0});
const first=renderer.render({serpapi_google_search:page(0)});
const second=renderer.render({serpapi_google_search:page(4)});
assert.ok(first.includes('Offers 1–4 of 8'));
assert.ok(!first.includes('Offers 5–8 of 8'));
assert.ok(first.includes('Disney+')&&!first.includes('Apple TV'));
assert.ok(second.includes('Offers 5–8 of 8'));
assert.ok(!second.includes('Offers 1–4 of 8'));
assert.ok(second.includes('Apple TV')&&!second.includes('Disney+'));
for(const html of [first,second]) {
  assert.ok(html.includes('10 sources shown of 10'));
  assert.ok(!html.includes('Sources 5–14'));
  assert.ok(!html.includes('/available_on'));
}
const incomplete=page(4);incomplete.result.panels[0].preview=watch.preview.slice(6);
const bounded=renderer.render({serpapi_google_search:incomplete});
assert.ok(bounded.includes('2 offers shown of 8'));
assert.ok(!bounded.includes('Offers 5–6 of 8'));
""")


def test_missing_optional_helper_falls_back_to_safe_retained_external_result():
    run_message_browser(FIXTURES + r"""
sandbox.window.createGoogleSearchResultAdapter=undefined;
const fallback=new sandbox.window.StructuredResultsRenderer();
const html=fallback.render({serpapi_google_search:google([watch])});
assert.ok(html.includes('Download raw response'));
assert.ok(!html.includes('google-serp-offer'));
assert.ok(!/<details[^>]*structured-results-external[^>]* open>/.test(html));
""")
