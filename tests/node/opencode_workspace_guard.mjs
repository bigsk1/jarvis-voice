import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = process.argv[3];
const workspace = path.join(root, "workspace");
const source = path.join(root, "jarvis-source");
fs.mkdirSync(workspace);
fs.mkdirSync(source);
fs.symlinkSync(source, path.join(workspace, "source-link"));
fs.symlinkSync(path.join(source, "missing"), path.join(workspace, "dangling"));
process.env.JARVIS_WORKSPACE_ROOT = workspace;
process.env.JARVIS_VOICE_ROOT = source;
const { default: plugin } = await import(pathToFileURL(process.argv[2]));
const hooks = {};
const domain = (name) => ({ hook: async (phase, callback) => { hooks[`${name}.${phase}`] = callback; } });
await plugin.setup({ location: { directory: workspace },
  tool: domain("tool"), permission: domain("permission"), shell: domain("shell") });
assert.equal(plugin.id, "jarvis.workspace-protection");
const tool = hooks["tool.execute.before"];
const permission = hooks["permission.evaluate"];
const shell = hooks["shell.create.before"];
assert.ok(tool && permission && shell);
for (const target of ["../jarvis-source/new.py", "source-link/new.py", "dangling", source,
                      path.join(root, "workspace-prefix/new.py"), "/etc/escaped"] ) {
  assert.throws(() => tool({ tool: "write", input: { path: target } }), /BLOCKED/);
  const event = { action: "edit", resources: [target], effect: "allow" };
  permission(event);
  assert.equal(event.effect, "deny");
}
tool({ tool: "write", input: { path: "new/nested/project.py" } });
tool({ tool: "read", input: { path: path.join(source, "app.py") } });
const read = { action: "read", resources: [source], effect: "allow" };
permission(read);
assert.equal(read.effect, "allow");
assert.throws(() => tool({ tool: "patch", input: { patchText:
  "*** Begin Patch\n*** Update File: okay.py\n@@\n-a\n+b\n*** Move to: ../jarvis-source/app.py\n*** End Patch" } }), /BLOCKED/);
tool({ tool: "patch", input: { patchText: "*** Begin Patch\n*** Add File: new.py\n+pass\n*** End Patch" } });
assert.throws(() => shell({ cwd: source, env: {} }), /BLOCKED/);
const shellEvent = { cwd: workspace, env: {} };
shell(shellEvent);
assert.equal(shellEvent.env.TMPDIR, path.join(workspace, "temp"));
console.log("OpenCode V2 workspace guard checks passed");
