import {spawnSync} from 'node:child_process';
import {access, mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {releaseMetadata} from './version.mjs';
const root = fileURLToPath(new URL('..', import.meta.url));
const {filename} = await releaseMetadata(root);
const destination = path.join(root, 'web-ext-artifacts', filename);
try {
  await access(destination);
  console.error(`Preserving ${filename}. Bump the version with npm run bump -- patch|minor|major before packaging another update.`);
  process.exit(1);
} catch (error) { if (error.code !== 'ENOENT') throw error; }
const cli = path.join(root, 'node_modules/web-ext/bin/web-ext.js');
const excludes = ['node_modules', 'package.json', 'package-lock.json', 'tests', 'scripts', 'README.md', 'web-ext-artifacts', 'web-ext.config.mjs'];
for (const action of ['lint', 'build']) {
  const args = [cli, action, '--source-dir', root, '--ignore-files', ...excludes];
  if (action === 'build') args.push('--artifacts-dir', path.join(root, 'web-ext-artifacts'), '--filename', filename);
  const result = spawnSync(process.execPath, args, {cwd: root, stdio: 'inherit'});
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
await mkdir(path.join(root, 'web-ext-artifacts'), {recursive: true});
await writeFile(path.join(root, 'web-ext-artifacts', 'INSTALL.txt'),
  'Unsigned development package. In Firefox, open about:debugging, choose This Firefox, Load Temporary Add-on, and select the ZIP.\nPermanent Firefox installation requires Mozilla signing. See README.md in the source repository.\n');
