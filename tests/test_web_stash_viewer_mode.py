"""Exercise the shipped viewer script through its fetch and open/download links."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['cloud', 'local', None, 'invalid'])
def test_stash_viewer_preserves_validated_mode(mode):
    script = r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const html=fs.readFileSync(ROOT+'/jarvis-web/client/stash-viewer.html','utf8');
const source=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const elements={}, fetched=[];
const sandbox={URLSearchParams,document:{getElementById:id=>elements[id]??=( {} )},
  window:{location:{pathname:'/stash/view/space/file',search:mode===null?'':'?mode='+mode}},
  Utils:{auth:{fetch:async url=>{fetched.push(url);return {ok:true,
    headers:{get:key=>key==='content-type'?'text/plain':'report.txt'},text:async()=> 'report contents'};}}}};
vm.runInNewContext(source,sandbox);
setImmediate(()=>{
  if(mode==='invalid') {assert.equal(fetched.length,0);assert.match(elements.stashStatus.textContent,/Invalid stash mode/);return;}
  const url='/api/stash/space/file'+(mode?'?mode='+mode:'');
  assert.deepEqual(fetched,[url]);
  assert.equal(elements.rawLink.href,url);
  assert.equal(elements.downloadLink.href,url);
  assert.equal(elements.stashContent.textContent,'report contents');
});
'''
    result = subprocess.run(['node', '-e', 'const ROOT=' + json.dumps(str(ROOT)) +
                             ',mode=' + json.dumps(mode) + ';\n' + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
