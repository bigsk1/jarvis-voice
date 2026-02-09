/**
 * OpenCode Workspace Protection Plugin
 * 
 * Purpose: Enforce strict workspace boundaries for OpenCode operations
 * 
 * Safety Rules:
 * 1. BLOCK write/edit/delete outside /home/boss/jarvis-workspace
 * 2. BLOCK all access to /home/boss/jarvis-voice (Jarvis codebase)
 * 3. BLOCK system directories (/etc, /usr, /bin, /sys, /proc, etc.)
 * 4. ALLOW read-only access for reference (can read Jarvis code to understand APIs)
 * 
 * Architecture: Jarvis (boss) → OpenCode (specialist)
 * This plugin ensures OpenCode stays in its sandbox.
 */

export const WorkspaceProtection = async ({ project, client, $, directory, worktree }) => {
  // Define protected paths
  const WORKSPACE_ROOT = "/home/boss/jarvis-workspace";
  const JARVIS_ROOT = "/home/boss/jarvis-voice";
  
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
  
  const PROTECTED_HOME_DIRS = [
    "/home/boss/.ssh",
    "/home/boss/.gnupg",
    "/home/boss/.config",  // Except opencode subdir
    "/home/boss/.local",
  ];

  /**
   * Check if a path is within the allowed workspace
   */
  function isInWorkspace(path) {
    if (!path) return false;
    
    // Normalize path (resolve relative paths from current directory)
    const absolutePath = path.startsWith('/') 
      ? path 
      : `${directory}/${path}`;
    
    return absolutePath.startsWith(WORKSPACE_ROOT);
  }

  /**
   * Check if a path is the Jarvis codebase (protected)
   */
  function isJarvisCode(path) {
    if (!path) return false;
    const absolutePath = path.startsWith('/') ? path : `${directory}/${path}`;
    return absolutePath.startsWith(JARVIS_ROOT);
  }

  /**
   * Check if a path is a system directory (protected)
   */
  function isSystemDir(path) {
    if (!path) return false;
    const absolutePath = path.startsWith('/') ? path : `${directory}/${path}`;
    
    // Check system directories
    for (const sysDir of SYSTEM_DIRS) {
      if (absolutePath.startsWith(sysDir)) {
        return true;
      }
    }
    
    // Check protected home directories (except opencode config)
    for (const protectedDir of PROTECTED_HOME_DIRS) {
      if (absolutePath.startsWith(protectedDir)) {
        // Allow opencode's own config
        if (protectedDir === "/home/boss/.config" && 
            absolutePath.startsWith("/home/boss/.config/opencode")) {
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
  function formatPath(path) {
    return path.replace('/home/boss', '~');
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

      // RULE 1: Block ALL access to Jarvis codebase
      if (isJarvisCode(filePath)) {
        throw new Error(
          `❌ BLOCKED: Cannot access Jarvis codebase\n` +
          `   Path: ${formatPath(filePath)}\n` +
          `   Reason: ${formatPath(JARVIS_ROOT)} is protected (read-only from workspace only)\n\n` +
          `   If you need to understand Jarvis APIs, ask Jarvis to provide the information.`
        );
      }

      // RULE 2: Block destructive operations outside workspace
      if (DESTRUCTIVE_TOOLS.includes(tool)) {
        if (!isInWorkspace(filePath)) {
          // Check if it's a system directory for specific error message
          if (isSystemDir(filePath)) {
            throw new Error(
              `❌ BLOCKED: Cannot modify system directories\n` +
              `   Tool: ${tool}\n` +
              `   Path: ${formatPath(filePath)}\n` +
              `   Reason: System directories are protected\n\n` +
              `   All file operations must be within: ${formatPath(WORKSPACE_ROOT)}`
            );
          }
          
          throw new Error(
            `❌ BLOCKED: File operation outside workspace\n` +
            `   Tool: ${tool}\n` +
            `   Path: ${formatPath(filePath)}\n` +
            `   Workspace: ${formatPath(WORKSPACE_ROOT)}\n\n` +
            `   All file operations must be within the workspace directory.\n` +
            `   Create your project in: ${formatPath(WORKSPACE_ROOT)}/projects/`
          );
        }
      }

      // RULE 3: Block system directory access (even reads)
      if (isSystemDir(filePath)) {
        throw new Error(
          `❌ BLOCKED: Cannot access system directories\n` +
          `   Tool: ${tool}\n` +
          `   Path: ${formatPath(filePath)}\n` +
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
      console.log(`   Current directory: ${formatPath(directory)}`);
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

