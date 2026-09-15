import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, readdir, access} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {JarvisTransport} from '../core/transport.js';
const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));

test('standalone manifest declares consent and least required permissions with packaged runtime assets', async () => {
  const manifest = JSON.parse(await readFile(path.join(root, 'manifest.json')));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.incognito, 'not_allowed');
  assert.equal(manifest.browser_specific_settings.gecko.strict_min_version, '140.0');
  assert.deepEqual(manifest.browser_specific_settings.gecko.data_collection_permissions.required,
    ['authenticationInfo', 'personalCommunications', 'websiteContent', 'browsingActivity']);
  assert.deepEqual(manifest.permissions, ['storage', 'activeTab', 'menus', 'alarms']);
  assert.deepEqual(manifest.optional_permissions, ['notifications']);
  const icon = await readFile(new URL('../assets/jarvis-96.png', import.meta.url));
  assert.equal(icon.subarray(1, 4).toString(), 'PNG');
  assert.equal(manifest.action.default_popup, undefined);
  assert.equal(manifest.content_scripts, undefined);
  assert.doesNotMatch(manifest.content_security_policy.extension_pages, /unsafe-eval|unsafe-inline/);
  for (const file of [...manifest.background.scripts, ...Object.values(manifest.icons), manifest.options_ui.page]) {
    await access(path.join(root, file));
  }
  async function scan(directory) {
    for (const entry of await readdir(path.join(root, directory), {withFileTypes: true})) {
      const relative = path.join(directory, entry.name);
      if (entry.isDirectory()) await scan(relative);
      else if (entry.name.endsWith('.js') || entry.name.endsWith('.html')) {
        const source = await readFile(path.join(root, relative), 'utf8');
        assert.doesNotMatch(source, /jarvis-web|JARVIS_VERSION/, relative);
        for (const match of source.matchAll(/(?:from\s+|import\s*)['"]([^'"]+)['"]/g)) {
          const resolved = path.resolve(root, directory, match[1]);
          assert.ok(resolved.startsWith(root + path.sep), `Import escapes package: ${relative}`);
          await access(resolved);
        }
      }
    }
  }
  for (const folder of ['core', 'browser', 'ui']) await scan(folder);
  assert.deepEqual(await readFile(path.join(root, 'vendor/socket.io.min.js')),
    await readFile(path.join(root, 'node_modules/socket.io-client/dist/socket.io.min.js')));
});

test('native fetch keeps its browser receiver instead of the transport instance', async () => {
  const nativeFetch = globalThis.fetch;
  try {
    globalThis.fetch = async function() {
      assert.equal(this, globalThis);
      return {ok: true, status: 200, json: async () => ({ok: true})};
    };
    const transport = new JarvisTransport({serverUrl: 'https://jarvis.example'});
    assert.deepEqual(await transport.status(), {ok: true});
  } finally { globalThis.fetch = nativeFetch; }
});

test('the packaged Socket.IO source map matches the pinned bundle and upstream distribution', async () => {
  const bundle = await readFile(path.join(root, 'vendor/socket.io.min.js'), 'utf8');
  const reference = bundle.match(/\/\/# sourceMappingURL=([^\s]+)/)?.[1];
  assert.equal(reference, 'socket.io.min.js.map');
  const packaged = await readFile(path.join(root, 'vendor', reference));
  const upstream = await readFile(path.join(root, 'node_modules/socket.io-client/dist', reference));
  assert.deepEqual(packaged, upstream, 'Keep the official matching source map unmodified');
  const map = JSON.parse(packaged);
  assert.equal(map.version, 3);
  assert.equal(map.file, 'socket.io.min.js');
  assert.equal(map.sourcesContent.length, map.sources.length, 'Source contents must be available without fetching external files');
  assert.ok(map.sourcesContent.every(source => typeof source === 'string'));
});
