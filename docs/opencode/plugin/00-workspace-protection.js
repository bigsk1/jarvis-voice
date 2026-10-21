/**
 * OpenCode 2 workspace guard. File tools may read source outside the workspace,
 * but may only mutate workspace files. The systemd unit supplies the filesystem
 * write boundary for arbitrary shell commands and Code Mode execution.
 *
 * V2 accepts this dependency-free { id, setup } definition directly; the public
 * Plugin.define helper returns the same object (packages/plugin/src/promise/plugin.ts).
 */
import { realpathSync, lstatSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

function canonicalPath(input, directory) {
  const absolute = path.resolve(directory, input);
  const suffix = [];
  let parent = absolute;
  for (;;) {
    try {
      return path.join(realpathSync(parent), ...suffix);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      // A dangling symlink must not become a writable-looking lexical path.
      try {
        if (lstatSync(parent).isSymbolicLink()) throw new Error("BLOCKED: dangling symlink");
      } catch (statError) {
        if (statError.code !== "ENOENT") throw statError;
      }
      if (path.dirname(parent) === parent) throw error;
      suffix.unshift(path.basename(parent));
      parent = path.dirname(parent);
    }
  }
}

function within(candidate, root) {
  return candidate === root || candidate.startsWith(root + path.sep);
}

export default {
  id: "jarvis.workspace-protection",
  async setup(ctx) {
    const directory = ctx.location.directory;
    const workspace = canonicalPath(
      process.env.JARVIS_WORKSPACE_ROOT || path.join(homedir(), "jarvis-workspace"),
      directory,
    );
    const jarvis = canonicalPath(
      process.env.JARVIS_VOICE_ROOT || path.join(homedir(), "jarvis-voice"),
      directory,
    );
    function checkMutation(input) {
      if (typeof input !== "string" || !input) {
        throw new Error("BLOCKED: mutation requires a target path");
      }
      const target = canonicalPath(input, directory);
      if (!within(target, workspace) || within(target, jarvis)) {
        throw new Error("BLOCKED: edits must remain inside the Jarvis workspace");
      }
    }

    // This hook also covers nested file tools reached through V2 Code Mode.
    await ctx.permission.hook("evaluate", (event) => {
      if (event.action !== "edit") return;
      try {
        if (!event.resources.length) checkMutation(undefined);
        event.resources.forEach(checkMutation);
      } catch {
        event.effect = "deny";
        event.message = "Edits must remain inside the Jarvis workspace";
      }
    });

    await ctx.tool.hook("execute.before", (event) => {
      const input = event.input || {};
      if (["write", "edit", "delete", "move", "rename"].includes(event.tool)) {
        checkMutation(input.path || input.filePath || input.file_path);
        if (input.destination) checkMutation(input.destination);
      }
      if (event.tool === "patch") {
        // V2 patch input uses the same Add/Update/Delete/Move header grammar.
        const targets = [...String(input.patchText || "").matchAll(
          /^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$/gm,
        )];
        if (!targets.length) throw new Error("BLOCKED: patch requires target paths");
        targets.forEach((match) => checkMutation(match[1].trim()));
      }
    });

    await ctx.shell.hook("create.before", (event) => {
      // A cwd check is useful feedback, not a command parser or shell sandbox.
      checkMutation(event.cwd);
      const scratch = path.join(workspace, "temp");
      event.env.TMPDIR = scratch;
      event.env.TMP = scratch;
      event.env.TEMP = scratch;
    });
  },
};
