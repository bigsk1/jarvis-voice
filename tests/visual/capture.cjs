#!/usr/bin/env node
/* Capture real UI renderers against the local sample preview. No live app access. */
const path = require('node:path');
const fs = require('node:fs/promises');

const args = process.argv.slice(2);
const value = name => args.includes(name) ? args[args.indexOf(name) + 1] : null;
const out = path.resolve(value('--output') || path.join(__dirname, '../../docs/images'));
const modulePath = value('--playwright-module') || 'playwright';
const emojiFont = value('--emoji-font');
let chromium;
try {
  ({ chromium } = require(modulePath));
} catch {
  console.error('Playwright is optional. See tests/visual/README.md for browser setup.');
  process.exit(1);
}

async function main() {
  await fs.mkdir(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1.5,
      locale: 'en-US', timezoneId: 'America/Los_Angeles', colorScheme: 'dark',
    });
    const failures = [];
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (emojiFont && url.pathname === '/__preview/emoji.ttf') {
        return route.fulfill({path: path.resolve(emojiFont), contentType: 'font/ttf'});
      }
      if (url.hostname === '127.0.0.1' && ['8761', '8762', '8763', '8764'].includes(url.port)) {
        return route.continue();
      }
      if (['data:', 'blob:'].includes(url.protocol)) return route.continue();
      return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', error => failures.push(error.message));
    page.on('response', response => {
      if (response.status() >= 400) failures.push(`HTTP ${response.status()}: ${response.url()}`);
    });
    await page.clock.setFixedTime(new Date('2026-10-16T17:30:00Z'));
    async function capture(name, url, selector, setup) {
      await page.goto(url, { waitUntil: 'load' });
      if (emojiFont) {
        await page.addStyleTag({content: `
          @font-face {font-family: "Preview Emoji"; src: url('/__preview/emoji.ttf');}
          @font-face {font-family: Inter; src: url('/__preview/emoji.ttf');
            font-weight: 100 900; unicode-range: U+1F000-1FAFF, U+2300-27BF, U+FE0F;}
          @font-face {font-family: "JetBrains Mono"; src: url('/__preview/emoji.ttf');
            font-weight: 100 900; unicode-range: U+1F000-1FAFF, U+2300-27BF, U+FE0F;}
          body, button, input, select, textarea {font-family: Inter, "Preview Emoji", sans-serif;}
        `});
      }
      if (setup) await setup(page);
      await page.waitForSelector(selector);
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(700);
      if (name === 'jarvis-web-ui.png') {
        await page.evaluate(() => {
          const messages = document.getElementById('chatMessages');
          messages.style.scrollBehavior = 'auto';
          messages.scrollTo({top: 0, behavior: 'instant'});
        });
      }
      await page.mouse.move(1590, 990);
      await page.screenshot({ path: path.join(out, name), animations: 'disabled', caret: 'hide' });
      console.log(name);
    }
    await capture('jarvis-web-ui.png', 'http://127.0.0.1:8761/', '.message.assistant', async p => {
      await p.waitForFunction(() => window.jarvisApp && window.chatUI);
      await p.waitForFunction(() => document.getElementById('statusText')?.textContent === 'Connected');
      await p.waitForTimeout(250);
      await p.evaluate(async () => {
        const data = await fetch('/api/conversations/demo-research').then(r => r.json());
        await window.jarvisApp._displayLoadedConversation(data.conversation);
        window.jarvisApp.logPanel?.close();
      });
    });
    await capture('jarvis-canvas-ui.png', 'http://127.0.0.1:8764/?page=page_demo_workspace', '#pageView .page-content');
    await capture('jarvis-memory-ui.png', 'http://127.0.0.1:8762/?mode=cloud#memories', '.memory-card');
    await capture('jarvis-intelligence-ui.png', 'http://127.0.0.1:8763/?mode=cloud', '.insight-card', async p => {
      await p.locator('.nav-tabs-desktop .nav-tab[data-tab="insights"]').click();
    });
    await capture('jarvis-reflection-queue.png', 'http://127.0.0.1:8763/?mode=cloud', '.reflection-row', async p => {
      await p.locator('.nav-tabs-desktop .nav-tab[data-tab="reflection"]').click();
    });
    await capture('jarvis-scheduled-tasks.png', 'http://127.0.0.1:8762/?mode=cloud#scheduled', '.scheduled-task-card');
    await capture('jarvis-logs-viewer.png', 'http://127.0.0.1:8761/logs', '#viewerContent .record-card');
    if (failures.length) throw new Error('Browser errors: ' + [...new Set(failures)].join('; '));
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
