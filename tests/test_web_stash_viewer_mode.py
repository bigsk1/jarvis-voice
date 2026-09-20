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


def test_browser_research_viewer_renders_captured_dom_as_literal_evidence():
    script = r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const html=fs.readFileSync(ROOT+'/jarvis-web/client/stash-viewer.html','utf8');
const source=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const elements={};
const artifact='# Browser research\n\nTask <img src=x>\n\n## Report\n\nPartial report\n\n'
  +'## Source 1: News <script>alert(1)</script>\n\nhttps://example.com/news?a=1&b=2\n\n'
  +'[1]<div onclick="alert(2)">headline</div>';
const escapeHtml=value=>String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;');
const sandbox={URL,URLSearchParams,document:{getElementById:id=>elements[id]??=({})},
  window:{location:{pathname:'/stash/view/space/file',search:''}},
  Utils:{escapeHtml,parseMarkdown:value=>value,unwrapBrowserResearchMarkdown:value=>value,
    auth:{fetch:async()=>({ok:true,
    headers:{get:key=>key==='content-type'?'text/markdown':
      key==='x-stash-filename'?'browser-research.md':''},text:async()=>artifact})}}};
vm.runInNewContext(source,sandbox);
setImmediate(()=>{
  const rendered=elements.stashContent.innerHTML;
  assert.equal(elements.stashContent.className,'markdown-viewer browser-research-viewer');
  assert.ok(rendered.includes('browser-research-evidence'));
  assert.ok(rendered.includes('&lt;div onclick=&quot;alert(2)&quot;&gt;headline&lt;/div&gt;'));
  assert.ok(!rendered.includes('<script>') && !rendered.includes('<div onclick='));
  assert.ok(rendered.includes('href="https://example.com/news?a=1&amp;b=2"'));
});
'''
    result = subprocess.run(['node', '-e', 'const ROOT=' + json.dumps(str(ROOT)) + ';\n' + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_cloud_research_viewer_unwraps_a_returned_markdown_file():
    script = r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const html=fs.readFileSync(ROOT+'/jarvis-web/client/stash-viewer.html','utf8');
const viewer=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const utils=fs.readFileSync(ROOT+'/jarvis-web/client/js/utils.js','utf8');
const elements={}, parsed=[];
const artifact='# Browser Use Cloud research\n\n## Request\n\nFind trends\n\n## Report\n\n'
  +'Retrieved successfully. Complete file contents:\n\n````markdown\n'
  +'# GitHub Trending Report\n\n| Rank | Repo |\n| --- | --- |\n| 1 | Example |\n````\n';
const sandbox={URL,URLSearchParams,document:{getElementById:id=>elements[id]??=({}),
  addEventListener(){}},window:{location:{pathname:'/stash/view/space/file',search:''}}};
vm.createContext(sandbox);
vm.runInContext(utils,sandbox);
sandbox.Utils=sandbox.window.Utils;
sandbox.Utils.parseMarkdown=value=>{parsed.push(value);return value;};
sandbox.Utils.auth={fetch:async()=>({ok:true,
  headers:{get:key=>key==='content-type'?'text/markdown':
    key==='x-stash-filename'?'browser-research.md':''},text:async()=>artifact})};
vm.runInContext(viewer,sandbox);
setImmediate(()=>{
  assert.equal(parsed.length,1);
  assert.ok(parsed[0].includes('## Report\n\n# GitHub Trending Report'));
  assert.ok(parsed[0].includes('| Rank | Repo |'));
  assert.ok(!parsed[0].includes('````'));
  assert.ok(!parsed[0].includes('Retrieved successfully'));
  assert.equal(elements.stashContent.className,'markdown-viewer browser-research-viewer');
});
'''
    result = subprocess.run(['node', '-e', 'const ROOT=' + json.dumps(str(ROOT)) + ';\n' + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
