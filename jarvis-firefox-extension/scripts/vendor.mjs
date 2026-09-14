import {copyFile, mkdir, readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('..', import.meta.url));
const pkg = JSON.parse(await readFile(path.join(root, 'node_modules/socket.io-client/package.json')));
if (pkg.version !== '4.7.2') throw new Error('Unexpected Socket.IO version. Use the checked-in lockfile.');
await mkdir(path.join(root, 'vendor'), {recursive: true});
for (const [source, target] of [
  ['dist/socket.io.min.js', 'socket.io.min.js'],
  ['dist/socket.io.min.js.map', 'socket.io.min.js.map'],
  ['LICENSE', 'socket.io.LICENSE'],
]) {
  await copyFile(path.join(root, 'node_modules/socket.io-client', source), path.join(root, 'vendor', target));
}
console.log('Copied the unmodified socket.io-client 4.7.2 bundle, source map, and license.');
