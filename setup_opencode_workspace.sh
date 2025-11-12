#!/bin/bash
# Setup OpenCode workspace structure for Jarvis

set -e

echo "🏗️  Creating OpenCode workspace structure..."

# Create workspace directories
WORKSPACE_ROOT="$HOME/jarvis-workspace"

# Clean up any malformed directories from failed brace expansions
if [ -d "$WORKSPACE_ROOT" ]; then
    echo "🧹 Cleaning up any malformed directories..."
    # Use find to safely locate and remove malformed directories
    # Directories starting with '{' (failed brace expansion)
    while IFS= read -r -d '' dir; do
        echo "   Removing malformed directory: $(basename "$dir")"
        rm -rf "$dir" 2>/dev/null || true
    done < <(find "$WORKSPACE_ROOT" -maxdepth 1 -type d -name '{*' -print0 2>/dev/null || true)
    
    # Directories ending with '}' (failed brace expansion)
    while IFS= read -r -d '' dir; do
        echo "   Removing malformed directory: $(basename "$dir")"
        rm -rf "$dir" 2>/dev/null || true
    done < <(find "$WORKSPACE_ROOT" -maxdepth 1 -type d -name '*}' -print0 2>/dev/null || true)
fi

# Create workspace directories (using individual commands, not brace expansion)
echo "📁 Creating directory structure..."
mkdir -p "$WORKSPACE_ROOT/projects/websites"
mkdir -p "$WORKSPACE_ROOT/projects/scripts"
mkdir -p "$WORKSPACE_ROOT/projects/experiments"
mkdir -p "$WORKSPACE_ROOT/temp"
mkdir -p "$WORKSPACE_ROOT/deployments"

# Create README files for each directory
cat > ~/jarvis-workspace/README.md << 'EOF'
# Jarvis Workspace

This workspace is used by Jarvis + OpenCode for building projects, experiments, and deployments.

## Structure

- **projects/** - Long-term projects organized by type
  - **websites/** - Web applications and sites
  - **scripts/** - Utility scripts and tools
  - **experiments/** - Experimental code and prototypes
- **temp/** - Temporary builds (auto-cleanup after 24h)
- **deployments/** - Ready-to-deploy artifacts

## Security

- This directory is isolated from the Jarvis codebase
- OpenCode can only modify files within this workspace
- Jarvis system files in `/home/boss/jarvis-voice` are read-only

## Usage

When you say:
- "Hey Jarvis, build a website" → Creates in `projects/websites/`
- "Hey Jarvis, test this code" → Creates in `temp/`
- "Hey Jarvis, deploy my app" → Reads from `deployments/`
EOF

cat > ~/jarvis-workspace/projects/README.md << 'EOF'
# Projects Directory

Long-term projects organized by category.

## Categories

- **websites/** - Web apps, portfolios, blogs
- **scripts/** - Automation scripts, utilities
- **experiments/** - Testing new ideas

## Workflow

1. Jarvis creates project: `jarvis-workspace/projects/websites/my-blog`
2. OpenCode builds: Files, dependencies, tests
3. You can edit manually or via voice commands
4. Deploy when ready: "Hey Jarvis, deploy my-blog"
EOF

cat > ~/jarvis-workspace/temp/README.md << 'EOF'
# Temporary Workspace

Quick experiments and tests.

## Auto-Cleanup

Files older than 24 hours are automatically deleted.

## Usage

Perfect for:
- Quick code tests
- API experiments
- Prototype ideas
EOF

# Set proper permissions
chmod -R 755 ~/jarvis-workspace

# Display structure
echo ""
echo "✅ Workspace created at: ~/jarvis-workspace"
echo ""
echo "📁 Structure:"
find ~/jarvis-workspace -type d | sed 's|/home/boss/jarvis-workspace|.|' | head -20

echo ""
echo "🎯 Ready for OpenCode integration!"
