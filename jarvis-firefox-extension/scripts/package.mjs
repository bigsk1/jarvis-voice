import {spawnSync} from 'node:child_process';
import {access, mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {releaseMetadata} from './version.mjs';
const root = fileURLToPath(new URL('..', import.meta.url));
const {filename, version} = await releaseMetadata(root);
const destination = path.join(root, 'web-ext-artifacts', filename);
try {
  await access(destination);
  console.error(`Preserving ${filename}. Bump the version with npm run bump -- patch|minor|major before packaging another update.`);
  process.exit(1);
} catch (error) { if (error.code !== 'ENOENT') throw error; }
const cli = path.join(root, 'node_modules/web-ext/bin/web-ext.js');
const excludes = ['node_modules', 'package.json', 'package-lock.json', 'tests', 'scripts', 'README.md', 'REVIEW.md', 'CHANGELOG.md', '.github', 'updates.json', 'assets/jarvis-firefox-extension.jpg', 'web-ext-artifacts', 'web-ext.config.mjs'];
for (const action of ['lint', 'build']) {
  const args = [cli, action, '--source-dir', root, ...(action === 'lint' ? ['--self-hosted'] : []), '--ignore-files', ...excludes];
  if (action === 'build') args.push('--artifacts-dir', path.join(root, 'web-ext-artifacts'), '--filename', filename);
  const result = spawnSync(process.execPath, args, {cwd: root, stdio: 'inherit'});
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
await mkdir(path.join(root, 'web-ext-artifacts'), {recursive: true});
const instructions = `Jarvis Companion ${version} — unlisted signing\n\n` +
  `1. Upload ${filename} at https://addons.mozilla.org/developers/addon/submit/distribution and choose "On your own".\n` +
  '2. Select desktop Firefox platforms. See REVIEW.md for source/build details and submission notes.\n' +
  '3. After Mozilla signs it, download the signed .xpi from the Developer Hub. Keep the signed file unchanged.\n' +
  '4. In Firefox open Add-ons and themes, the gear menu, then Install Add-on From File; select that signed .xpi.\n\n' +
  'The signed installation survives browser restarts and needs no about:debugging. You may share the signed .xpi through GitHub Releases.\n' +
  'This ZIP is unsigned and cannot be installed permanently in release Firefox. Renaming it to .xpi does not sign it.\n' +
  'For updates, upload each new signed XPI to a GitHub Release and update the repository updates.json with its version, download link, and SHA-256. Firefox then discovers the update automatically.\n' +
  'Unlisted submissions still follow Mozilla policies and can receive manual review. No hosted review server is provided.\n';
await writeFile(path.join(root, 'web-ext-artifacts', `jarvis_companion-${version}-INSTALL.txt`), instructions, {flag: 'wx'});
await writeFile(path.join(root, 'web-ext-artifacts', 'INSTALL.txt'), instructions);
