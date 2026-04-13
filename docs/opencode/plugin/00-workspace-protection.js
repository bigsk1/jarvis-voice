/**
 * OpenCode Workspace Protection Plugin
 *
 * Purpose: Enforce strict workspace boundaries for OpenCode operations
 *
 * Safety Rules:
 * 1. BLOCK write/edit/delete outside $HOME/jarvis-workspace (override: JARVIS_WORKSPACE_ROOT)
 * 2. BLOCK all access to $HOME/jarvis-voice (override: JARVIS_VOICE_ROOT)
 * 3. BLOCK system directories (/etc, /usr, /bin, /sys, /proc, etc.)
 * 4. ALLOW read-only access for reference (can read Jarvis code to understand APIs)
 *
 * Defaults match a clone at ~/jarvis-voice and workspace at ~/jarvis-workspace (see lib/paths.py).
 */

import { homedir } from "node:os";
import path from "node:path";

export const WorkspaceProtection = async ({ project, client, $, directory, worktree }) => {
  const HOME = homedir();
  const JARVIS_ROOT = path.resolve(process.env.JARVIS_VOICE_ROOT || path.join(HOME, "jarvis-voice"));
  const WORKSPACE_ROOT = path.resolve(
    process.env.JARVIS_WORKSPACE_ROOT || path.join(HOME, "jarvis-workspace"),
  );
  const CURRENT_DIRECTORY = path.resolve(directory || process.cwd());

  const SYSTEM_DIRS = [
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/sys",
    "/proc",
    "/boot",
    "/root",
    "/var/lib",
    "/var/log",
  ];
  
  const CONFIG_DIR = path.join(HOME, ".config");
  const PROTECTED_HOME_DIRS = [
    path.join(HOME, ".ssh"),
    path.join(HOME, ".gnupg"),
    CONFIG_DIR, // Except opencode subdir
    path.join(HOME, ".local"),
  ];

  function resolvePath(inputPath) {
    if (!inputPath) return "";
    return path.resolve(CURRENT_DIRECTORY, inputPath);
  }

  function isWithin(candidate, root) {
    return candidate === root || candidate.startsWith(root + path.sep);
  }

  /**
   * Check if a path is within the allowed workspace
   */
  function isInWorkspace(inputPath) {
    const absolutePath = resolvePath(inputPath);
    return isWithin(absolutePath, WORKSPACE_ROOT);
  }

  /**
   * Check if a path is the Jarvis codebase (protected)
   */
  function isJarvisCode(inputPath) {
    const absolutePath = resolvePath(inputPath);
    return isWithin(absolutePath, JARVIS_ROOT);
  }

  /**
   * Check if a path is a system directory (protected)
   */
  function isSystemDir(inputPath) {
    const absolutePath = resolvePath(inputPath);
    
    // Check system directories
    for (const sysDir of SYSTEM_DIRS) {
      if (isWithin(absolutePath, sysDir)) {
        return true;
      }
    }
    
    // Check protected home directories (except opencode config)
    for (const protectedDir of PROTECTED_HOME_DIRS) {
      if (isWithin(absolutePath, protectedDir)) {
        // Allow opencode's own config
        if (protectedDir === CONFIG_DIR &&
            isWithin(absolutePath, path.join(CONFIG_DIR, "opencode"))) {
          return false;
        }
        return true;
      }
    }
    
    return false;
  }

  /**
   * Get user-friendly path for error messages
   */
  function formatPath(p) {
    if (!p) return p;
    if (p === HOME || p.startsWith(HOME + path.sep)) {
      return "~" + (p === HOME ? "" : p.slice(HOME.length));
    }
    return p;
  }

  console.log("🛡️  Workspace Protection Plugin loaded");
  console.log(`   Workspace: ${formatPath(WORKSPACE_ROOT)}`);
  console.log(`   Protected: ${formatPath(JARVIS_ROOT)} (Jarvis codebase)`);

  return {
    /**
     * Hook: Before tool execution
     * Intercept file operations and enforce boundaries
     */
    "tool.execute.before": async (input, output) => {
      const tool = input.tool;
      const args = output.args || output;

      // Define destructive operations (need strict validation)
      const DESTRUCTIVE_TOOLS = [
        "write",
        "write_file", 
        "create_file",
        "edit",
        "edit_file",
        "delete",
        "delete_file",
        "rm",
        "move",
        "mv",
        "rename",
      ];

      // Get file path from various possible argument names
      const filePath = args.filePath || 
                      args.file_path || 
                      args.path || 
                      args.file ||
                      args.target ||
                      args.destination;

      if (!filePath) {
        // No file path found, skip validation
        return;
      }
      const resolvedPath = resolvePath(filePath);

      // RULE 1: Block ALL access to Jarvis codebase
      if (isJarvisCode(resolvedPath)) {
        throw new Error(
          `❌ BLOCKED: Cannot access Jarvis codebase\n` +
          `   Path: ${formatPath(resolvedPath)}\n` +
          `   Reason: ${formatPath(JARVIS_ROOT)} is protected (read-only from workspace only)\n\n` +
          `   If you need to understand Jarvis APIs, ask Jarvis to provide the information.`
        );
      }

      // RULE 2: Block destructive operations outside workspace
      if (DESTRUCTIVE_TOOLS.includes(tool)) {
        if (!isInWorkspace(resolvedPath)) {
          // Check if it's a system directory for specific error message
          if (isSystemDir(resolvedPath)) {
            throw new Error(
              `❌ BLOCKED: Cannot modify system directories\n` +
              `   Tool: ${tool}\n` +
              `   Path: ${formatPath(resolvedPath)}\n` +
              `   Reason: System directories are protected\n\n` +
              `   All file operations must be within: ${formatPath(WORKSPACE_ROOT)}`
            );
          }
          
          throw new Error(
            `❌ BLOCKED: File operation outside workspace\n` +
            `   Tool: ${tool}\n` +
            `   Path: ${formatPath(resolvedPath)}\n` +
            `   Workspace: ${formatPath(WORKSPACE_ROOT)}\n\n` +
            `   All file operations must be within the workspace directory.\n` +
            `   Create your project in: ${formatPath(WORKSPACE_ROOT)}/projects/`
          );
        }
      }

      // RULE 3: Block system directory access (even reads)
      if (isSystemDir(resolvedPath)) {
        throw new Error(
          `❌ BLOCKED: Cannot access system directories\n` +
          `   Tool: ${tool}\n` +
          `   Path: ${formatPath(resolvedPath)}\n` +
          `   Reason: System directories are protected\n\n` +
          `   Work within: ${formatPath(WORKSPACE_ROOT)}`
        );
      }

      // Allow the operation (passed all checks)
    },

    /**
     * Hook: On session start
     * Log workspace info for debugging
     */
    "session.start": async () => {
      console.log("\n🛡️  Workspace Protection Active");
      console.log(`   Current directory: ${formatPath(CURRENT_DIRECTORY)}`);
      console.log(`   Allowed workspace: ${formatPath(WORKSPACE_ROOT)}`);
      console.log(`   Protected: ${formatPath(JARVIS_ROOT)}\n`);
    },

    /**
     * Hook: On error
     * Log blocked operations for audit trail
     */
    "error": async ({ error }) => {
      if (error.message && error.message.includes("BLOCKED")) {
        console.error("\n🚫 Workspace Protection: Operation blocked");
        console.error(`   ${error.message}\n`);
      }
    }
  };
};
