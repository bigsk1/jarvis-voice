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

This directory contains projects built by Jarvis + OpenCode.

## Git Strategy

**This workspace itself is NOT tracked by jarvis-voice git.**

However, you can (and should) initialize git repos for individual projects:

```bash
# Example: Create a website project with git
cd ~/jarvis-workspace/projects/websites/my-portfolio
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/yourusername/my-portfolio.git
git push -u origin main
```

## Directory Structure

- **projects/** - Long-term projects (can have their own git repos)
  - **websites/** - Web applications and sites
  - **scripts/** - Utility scripts and tools
  - **experiments/** - Experimental code and prototypes
- **temp/** - Temporary builds (auto-cleanup after 24h, NEVER git track)
- **deployments/** - Ready-to-deploy artifacts

## Backup Strategy

Since this is outside git, consider:
1. Individual git repos per project
2. Cloud sync (Dropbox, Google Drive, etc.)
3. Regular backups of important projects
4. Keep source in jarvis-voice repo, builds here

## Security

- Jarvis system files are READ-ONLY from OpenCode builds
- This workspace is isolated and safe for experimentation
- Each project can have its own .gitignore

## Usage

When you say:
- "Hey Jarvis, build a website" → Creates in `projects/websites/`
- "Hey Jarvis, test this code" → Creates in `temp/`
- "Hey Jarvis, deploy my app" → Reads from `deployments/`

---

**Note**: If you accidentally build something here and want to move it to a tracked repo, 
just copy the files to a proper git repository location.
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
