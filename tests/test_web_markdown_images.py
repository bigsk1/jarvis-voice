"""Regression coverage for images embedded in Web chat Markdown."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
MAIN_CSS = ROOT / "jarvis-web" / "client" / "css" / "main.css"
UTILS_JS = ROOT / "jarvis-web" / "client" / "js" / "utils.js"


def test_assistant_markdown_images_stay_within_the_message_bubble():
    css = MAIN_CSS.read_text(encoding="utf-8")
    rule = re.search(
        r"\.message\.assistant\s+\.message-bubble\s+img\s*\{(?P<body>[^}]*)\}",
        css,
    )

    assert rule is not None
    declarations = rule.group("body")
    assert "max-width: 100%;" in declarations
    assert "height: auto;" in declarations
    assert "display: block;" in declarations


def test_product_thumbnail_rule_limits_both_dimensions_without_cropping_or_mobile_overflow():
    css = MAIN_CSS.read_text(encoding="utf-8")
    rule = re.search(
        r"\.message\.assistant\s+\.message-bubble\s+img\.markdown-product-thumbnail\s*\{([^}]*)\}",
        css,
    )
    assert rule is not None
    for declaration in ("width: auto;", "max-width: min(100%, 240px);", "max-height: 220px;",
                        "object-fit: contain;"):
        assert declaration in rule.group(1)


def test_markdown_product_photos_get_compact_full_size_actions_only_on_exact_product_host():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tagName, attrs = {}) {
    this.tagName = tagName.toUpperCase(); this.attrs = attrs; this.children = []; this.events = {};
    this.alt = attrs.alt || ''; this.className = '';
    this.classList = {add: name => { this.className = [...new Set([...this.className.split(' '), name])].join(' ').trim(); }};
  }
  getAttribute(name) { return this.attrs[name] ?? null; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(name, handler) { this.events[name] = handler; }
  closest(selector) {
    for (let node = this; node; node = node.parentNode) {
      if (selector === 'a' && node.tagName === 'A') return node;
    }
    return null;
  }
  appendChild(node) {
    if (node.parentNode) node.parentNode.children = node.parentNode.children.filter(item => item !== node);
    this.children.push(node); node.parentNode = this;
  }
  insertBefore(node, before) {
    const index = this.children.indexOf(before);
    this.children.splice(index, 0, node); node.parentNode = this;
  }
}
const sandbox = {URL, console, window: {}, document: {
  addEventListener() {}, createElement: tag => new Element(tag),
}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(UTILS_PATH, 'utf8'), sandbox);
const Utils = sandbox.window.Utils;
const opened = [];
sandbox.window.showImageLightbox = source => opened.push(source);
const sources = [
  'https://www.traderjoes.com/content/dam/trjo/products/m442/66148.png',
  'https://www.traderjoes.com/content/dam/trjo/products/m442/66148.png/jcr:content/renditions/webp-1280.webp',
  'https://traderjoes.com/content/dam/trjo/products/m304/80794.png?version=1',
  'https://www.traderjoes.com/content/dam/trjo/context-images/66148-autumn-maple-coffee-pdp.jpg',
  'https://www.traderjoes.com.evil.test/content/dam/trjo/products/photo.png',
  'https://www.traderjoes.com/content/dam/trjo/stores/logo.png',
  'https://images.example/product.png?source=www.traderjoes.com/content/dam/trjo/products/',
  '/api/images/generated.png', '/api/uploads/user-photo.png', '/api/stash/images/upload.png',
  'https://i5.walmartimages.com/coffee.png',
  'https://user:secret@www.traderjoes.com/content/dam/trjo/products/photo.png',
];
{
  // This shared hydration boundary also handles images restored from saved Markdown.
  const bubble = new Element('div');
  const images = sources.map((src, index) => {
    const image = new Element('img', {src, alt: `Package ${index}`});
    bubble.appendChild(image); return image;
  });
  const root = {querySelectorAll: selector => selector === '.message.assistant .message-bubble img' ? images : []};
  Utils.hydrateRichContent(root);
  Utils.hydrateRichContent(root); // Reload/re-hydration must not duplicate actions.
  images.forEach((image, index) => {
    assert.equal(image.getAttribute('src'), sources[index]);
    if (index < 4) {
      assert.equal(image.className, 'markdown-product-thumbnail');
      const link = image.parentNode;
      assert.equal(link.tagName, 'A'); assert.equal(link.parentNode, bubble);
      assert.equal(link.href, sources[index]);
      assert.equal(link.target, '_blank'); assert.equal(link.rel, 'noopener noreferrer');
      assert.equal(link.attrs['aria-label'], `Open full-size Package ${index}`);
      let prevented = false;
      link.events.click({preventDefault() { prevented = true; }});
      assert.equal(prevented, true); assert.equal(opened.at(-1), sources[index]);
    } else {
      assert.equal(image.className, ''); assert.equal(image.parentNode, bubble);
    }
  });
  assert.equal(bubble.children.filter(node => node.tagName === 'A').length, 4);
}
// A pre-existing image link keeps its destination and click behavior.
const existingLink = new Element('a');
existingLink.href = 'https://www.traderjoes.com/home/products/pdp/coffee-066148';
const existingClick = () => {};
existingLink.events.click = existingClick;
const linkedImage = new Element('img', {src: sources[0]});
existingLink.appendChild(linkedImage);
Utils.hydrateRichContent({querySelectorAll: selector => selector === '.message.assistant .message-bubble img' ? [linkedImage] : []});
assert.equal(linkedImage.className, 'markdown-product-thumbnail');
assert.equal(linkedImage.parentNode, existingLink);
assert.equal(existingLink.href, 'https://www.traderjoes.com/home/products/pdp/coffee-066148');
assert.equal(existingLink.events.click, existingClick);
process.stdout.write('ok');
""".replace("UTILS_PATH", json.dumps(str(UTILS_JS)))
    result = subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)
    assert result.stdout == "ok"
