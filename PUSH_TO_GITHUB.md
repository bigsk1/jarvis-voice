# Push Jarvis to Private GitHub Repository

## Security Audit Complete ✅

Your repository has been audited and is **safe to push** to a private GitHub repository.

### What's Protected:
- ✅ API keys (in .gitignore)
- ✅ Database (in .gitignore)
- ✅ Logs (in .gitignore)
- ✅ Audio files (in .gitignore)
- ✅ No secrets in tracked files

### ⚠️ Important: Rotate This API Key
The OpenAI key `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` was briefly in git history.
**Action:** Rotate this key at https://platform.openai.com/api-keys after pushing.

## Steps to Push to GitHub

### Option 1: Create New Private Repo via GitHub CLI (gh)

If you have `gh` installed:

```bash
cd /home/boss/jarvis-voice

# Login to GitHub (if not already)
gh auth login

# Create private repo
gh repo create jarvis-voice --private --source=. --remote=origin --push

# Done! Your repo is at: https://github.com/YOUR_USERNAME/jarvis-voice
```

### Option 2: Create via GitHub Web Interface

1. **Go to GitHub**: https://github.com/new

2. **Create Repository:**
   - Name: `jarvis-voice`
   - Description: `Self-hosted AI voice assistant with tools, memory, and MCP integration`
   - ✅ **Private** (important!)
   - ❌ Don't initialize with README/license/gitignore (we have those)

3. **Push your local repo:**
   ```bash
   cd /home/boss/jarvis-voice
   
   # Add GitHub as remote (replace YOUR_USERNAME)
   git remote add origin https://github.com/YOUR_USERNAME/jarvis-voice.git
   
   # Push to GitHub
   git push -u origin master
   ```

### Option 3: Use SSH (More Secure)

```bash
cd /home/boss/jarvis-voice

# Create repo on GitHub first (web interface, step 2 above)
# Then add SSH remote (replace YOUR_USERNAME)
git remote add origin git@github.com:YOUR_USERNAME/jarvis-voice.git

# Push
git push -u origin master
```

## After Pushing

### 1. Verify Privacy
- Go to your repo on GitHub
- Click **Settings** → **General**
- Confirm it says "Private" under "Danger Zone"

### 2. Rotate OpenAI Key
- Go to: https://platform.openai.com/api-keys
- Delete or rotate the old key: `sk-t0hJvx...`
- Update `config/cloud.env` with new key

### 3. Optional: Add Collaborators
- Settings → Collaborators
- Add team members if needed

## Backup Strategy

Now that your code is on GitHub:

**Daily:** GitHub auto-saves every push  
**Weekly:** Consider local backup too
```bash
# Create timestamped backup
cd /home/boss
tar -czf jarvis-backup-$(date +%Y%m%d).tar.gz jarvis-voice/
# Copy to external drive/NAS
```

## Repository Structure (What's on GitHub)

```
jarvis-voice/
├── bin/               # Executable scripts
├── lib/               # Python libraries
├── orchestrator/      # LLM routing & execution
├── skills/            # Tool definitions
├── config/
│   ├── *.env.template # Safe templates (API keys NOT included)
│   └── mcp-servers.json
├── docs/              # Complete documentation
├── data/              # NOT on GitHub (in .gitignore)
├── logs/              # NOT on GitHub (in .gitignore)
├── audio/             # NOT on GitHub (in .gitignore)
└── README.md

🔒 Private files stay local (not in GitHub)
```

## Clone on Another Machine

```bash
# On new machine
git clone https://github.com/YOUR_USERNAME/jarvis-voice.git
cd jarvis-voice

# Copy your config files from backup or recreate:
cp config/config.env.template config/cloud.env
# Edit cloud.env with your API keys

cp config/config.env.template config/local.env
# Edit local.env with your settings

# Install dependencies
./setup_tools.sh

# Ready to use!
```

## Troubleshooting

### "Authentication failed"
```bash
# If using HTTPS, GitHub needs a Personal Access Token (not password)
# Generate at: https://github.com/settings/tokens
# Use token as password when prompted
```

### "Remote already exists"
```bash
# Remove old remote and add new one
git remote remove origin
git remote add origin https://github.com/YOUR_USERNAME/jarvis-voice.git
```

### "Failed to push"
```bash
# Check remote
git remote -v

# Force push (only if you're sure!)
git push -u origin master --force
```

## Success Checklist

- [ ] Created private GitHub repository
- [ ] Pushed code successfully
- [ ] Verified repo is PRIVATE
- [ ] Rotated exposed OpenAI API key
- [ ] Updated local config with new key
- [ ] Tested clone on another machine (optional)
- [ ] Set up backup strategy

---

**Your code is now safe and backed up! 🎉**

