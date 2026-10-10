"""Exercise Craft receipts and PDF previews through the shipped chat renderer."""
from test_web_assistant_message_rendering import run_message_browser


def test_pdf_preview_is_rendered_without_changing_primary_pdf():
    run_message_browser(r"""
const ui = chat();
const payload = {craft_pdf:{state:'succeeded', stash_ref:'stash://space/document',
  filename:'document.pdf',mime_type:'application/pdf',outputs:[
    {role:'primary',stash_ref:'stash://space/document',name:'document.pdf',mime_type:'application/pdf'},
    {role:'preview',stash_ref:'stash://space/preview',name:'preview.png',mime_type:'image/png'}]}};
const before=JSON.stringify(payload);
const html=render(ui,'PDF edited',['craft_pdf'],payload);
assert.ok(html.includes('src="/api/stash/space/preview"'));
assert.ok(!html.includes('src="/api/stash/space/document"'));
assert.equal(JSON.stringify(payload),before);
""")


def test_running_receipt_has_no_preview_and_keeps_foreground_state():
    run_message_browser(r"""
const ui = chat();
const payload={craft_video:{job_id:'a'.repeat(32),project_id:'b'.repeat(32),state:'running'}};
const html=render(ui,'Craft job accepted and still running',['craft_video'],payload);
assert.ok(html.includes('Craft job accepted and still running'));
assert.ok(!html.includes('<img') && !html.includes('<video'));
""")
