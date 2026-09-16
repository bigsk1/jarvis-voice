import {readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export async function releaseMetadata(root) {
  const names = ['manifest.json', 'package.json', 'package-lock.json'];
  const files = await Promise.all(names.map(async name => ({name, data: JSON.parse(await readFile(path.join(root, name), 'utf8'))})));
  const version = files[0].data.version;
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version) ||
      files.some(file => file.data.version !== version) || files[2].data.packages?.['']?.version !== version) {
    throw new Error('Extension versions must match in manifest.json, package.json, and package-lock.json.');
  }
  return {files, version, filename: `jarvis_companion-${version}.zip`};
}

export async function bumpVersion(root, kind) {
  if (!['patch', 'minor', 'major'].includes(kind)) throw new Error('Use npm run bump -- patch|minor|major.');
  const {files, version} = await releaseMetadata(root);
  const parts = version.split('.').map(Number);
  const index = {major: 0, minor: 1, patch: 2}[kind];
  parts[index] += 1;
  for (let i = index + 1; i < parts.length; i++) parts[i] = 0;
  const next = parts.join('.');
  for (const {name, data} of files) {
    data.version = next;
    if (name === 'package-lock.json') data.packages[''].version = next;
    await writeFile(path.join(root, name), JSON.stringify(data, null, 2) + '\n');
  }
  return next;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { console.log(`Extension version: ${await bumpVersion(fileURLToPath(new URL('..', import.meta.url)), process.argv[2])}`); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
