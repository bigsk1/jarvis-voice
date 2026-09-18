"""Friendly labels must never become storage, CDN, or download identifiers."""

import pytest

from test_web_attachment_bundle_ui import run_browser


SETUP = r"""
const elements=new Map(), downloads=[];
const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
sandbox.document.getElementById=el;
sandbox.document.addEventListener=()=>{};
sandbox.document.body=new Element();
sandbox.document.body.style={};
sandbox.document.createElement=tag=>{
  const item=new Element(tag);
  Object.defineProperty(item,'textContent',{set(value){this.innerHTML=sandbox.Utils.escapeHtml(value);}});
  item.click=()=>downloads.push(item.download);
  return item;
};
sandbox.window.addEventListener=()=>{};
sandbox.navigator={userAgent:'fixture',platform:'Linux'};
sandbox.URL={createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}};
sandbox.File=class {constructor(parts,name){this.name=name;}};
sandbox.IntersectionObserver=class {observe(){} disconnect(){}};
sandbox.setTimeout=()=>0;
sandbox.fetch=async(url,options)=>{
  requests.push([url,options]);
  return {ok:true,json:async()=>({ok:true,cached:true,url:'https://cdn.example/existing'}),blob:async()=>({type:'image/png'})};
};
sandbox.fixtureName='generated_sunset_20260918_003012_a1b2c3d4e5f60718293a4b5c6d7e8f90.png';
"""


def test_image_display_preserves_catalog_cdn_and_download_identity():
    run_browser(SETUP + r"""
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-canvas/client/static/js/gallery.js','utf8'),sandbox);
await vm.runInContext(`(async()=>{
  showToast=()=>{};copyToClipboard=async()=>true;
  const item={name:fixtureName,size:100,modified:'2026-09-18',cdn_cached:true};
  images=[item];filteredImages=[item];renderGallery();
  if(formatImageName(fixtureName)!=='sunset')throw Error('UUID leaked into label');
  if(formatImageName('generated_sunset_20260918_003012.png')!=='sunset')throw Error('Legacy label changed');
  if(formatImageName(fixtureName.replace('.png','_2.png'))!=='sunset (2)')throw Error('Batch label lost');
  const html=document.getElementById('gallery').innerHTML;
  if(html.split('title="'+fixtureName+'"').length!==3)throw Error('Full filename missing on image or label hover');
  if(!html.includes('/api/gallery/images/'+encodeURIComponent(fixtureName)))throw Error('Source identifier changed');
  openLightboxByIndex(0);
  if(currentImage!==fixtureName)throw Error('Current file identifier changed');
  if(document.getElementById('lightboxFilename').textContent!=='sunset')throw Error('Lightbox label leaked');
  await getCdnUrl(fixtureName);
  await downloadDirect(fixtureName);
  if(item.name!==fixtureName || !item.cdn_cached)throw Error('Catalog/CDN identity changed');
  // Exercise the fallback too: action identifiers cannot come from the label.
  currentImage=null;
  let deleted,handedOff;
  deleteImage=name=>{deleted=name;};
  sendImageToJarvisWeb=name=>{handedOff=name;};
  deleteFromLightbox();
  sendCurrentImageToJarvisWeb();
  if(deleted!==fixtureName||handedOff!==fixtureName)throw Error('Friendly label used as action identifier');
})()`,sandbox);
assert.ok(requests.some(([url])=>url===`/api/gallery/images/${sandbox.fixtureName}/cdn-url`));
assert.ok(requests.some(([url])=>url===`/api/gallery/images/${sandbox.fixtureName}/download`));
assert.deepEqual(downloads,[sandbox.fixtureName]);
""")


@pytest.mark.parametrize('prefix', ['video', 'social'])
def test_video_display_preserves_playback_and_download_identity(prefix):
    run_browser(SETUP + f"sandbox.fixtureName=sandbox.fixtureName.replace('generated_', '{prefix}_').replace('.png','.mp4');\n" + r"""
Element.prototype.play=()=>Promise.resolve();
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-canvas/client/static/js/video-gallery.js','utf8'),sandbox);
await vm.runInContext(`(async()=>{
  showToast=()=>{};
  const item={name:fixtureName,size:100,modified:'2026-09-18'};
  videos=[item];filteredVideos=[item];renderGallery();
  if(formatVideoName(fixtureName)!=='sunset')throw Error('UUID leaked into label');
  if(formatVideoName('video_sunset_20260918_003012.mp4')!=='sunset')throw Error('Legacy label changed');
  const html=document.getElementById('videoGallery').innerHTML;
  if(!html.includes('title="sunset"'))throw Error('Hover label leaked');
  if(!html.includes('/api/gallery/videos/'+encodeURIComponent(fixtureName)))throw Error('Source identifier changed');
  openLightboxByIndex(0);
  if(currentVideo!==fixtureName)throw Error('Current file identifier changed');
  if(document.getElementById('lightboxFilename').textContent!=='sunset')throw Error('Lightbox label leaked');
  await downloadDirect(fixtureName);
  if(item.name!==fixtureName)throw Error('Catalog identity changed');
  currentVideo=null;
  let deleted;
  deleteVideo=name=>{deleted=name;};
  deleteFromLightbox();
  if(deleted!==fixtureName)throw Error('Friendly label used as deletion identifier');
})()`,sandbox);
assert.equal(el('lightboxFilename').dataset.filename,sandbox.fixtureName);
assert.ok(requests.some(([url])=>url===`/api/gallery/videos/${sandbox.fixtureName}/download`));
assert.deepEqual(downloads,[sandbox.fixtureName]);
""")


def test_audio_title_fallback_preserves_filename_and_download_identity():
    run_browser(SETUP + r"""
sandbox.fixtureName=sandbox.fixtureName.replace('generated_', 'music_').replace('.png','.mp3');
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-canvas/client/static/js/audio-gallery.js','utf8'),sandbox);
await vm.runInContext(`(async()=>{
  showToast=()=>{};
  const item={name:fixtureName};
  if(getTrackTitle(item)!=='Sunset')throw Error('Fallback UUID leaked');
  item.title='My actual track title';
  if(getTrackTitle(item)!==item.title)throw Error('Catalog title ignored');
  await downloadAudio(item.name);
  if(item.name!==fixtureName)throw Error('Catalog identity changed');
})()`,sandbox);
assert.ok(requests.some(([url])=>url===`/api/gallery/audio/${sandbox.fixtureName}/download`));
assert.deepEqual(downloads,[sandbox.fixtureName]);
""")
