import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, readFile, mkdir, copyFile, rm} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {bumpVersion, releaseMetadata} from '../scripts/version.mjs';

async function fixture(t) {
  const root = await mkdtemp(path.join(tmpdir(), 'jarvis-extension-version-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  for (const name of ['manifest.json', 'package.json', 'package-lock.json']) {
    await writeFile(path.join(root, name), JSON.stringify({version: '0.1.6', packages: {'': {version: '0.1.6'}}}));
  }
  return root;
}

test('release bump updates all version fields for fixes, features, and breaking changes', async t => {
  const root = await fixture(t);
  for (const [kind, expected] of [['patch', '0.1.7'], ['minor', '0.2.0'], ['major', '1.0.0']]) {
    assert.equal(await bumpVersion(root, kind), expected);
    assert.equal((await releaseMetadata(root)).filename, `jarvis_companion-${expected}.zip`);
  }
  await assert.rejects(bumpVersion(root, '0.1.6'), /patch\|minor\|major/);
  assert.equal((await releaseMetadata(root)).version, '1.0.0');
});

test('mismatched version metadata stops packaging and bumping before changes', async t => {
  const root = await fixture(t);
  await writeFile(path.join(root, 'manifest.json'), '{"version":"0.2.0"}');
  await assert.rejects(releaseMetadata(root), /must match/);
  await assert.rejects(bumpVersion(root, 'patch'), /must match/);
  assert.equal(JSON.parse(await readFile(path.join(root, 'package.json'))).version, '0.1.6');
});

test('packaging refuses to replace an existing versioned artifact', async t => {
  const root = await fixture(t);
  await mkdir(path.join(root, 'scripts'));
  await mkdir(path.join(root, 'web-ext-artifacts'));
  for (const name of ['package.mjs', 'version.mjs']) await copyFile(new URL(`../scripts/${name}`, import.meta.url), path.join(root, 'scripts', name));
  const artifact = path.join(root, 'web-ext-artifacts/jarvis_companion-0.1.6.zip');
  await writeFile(artifact, 'previous release');
  const env = {...process.env}; delete env.NODE_TEST_CONTEXT;
  const result = spawnSync(process.execPath, [path.join(root, 'scripts/package.mjs')], {env, encoding: 'utf8'});
  assert.ifError(result.error);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Preserving jarvis_companion-0.1.6.zip/);
  assert.equal(await readFile(artifact, 'utf8'), 'previous release');
});
