# Shell Alias Guide

## The Problem

Your `~/.bashrc` has aliases pointing to the old script locations in `/home/boss/`, so when you type `jarvis`, it runs the old setup instead of the new structured project.

**Current aliases (in ~/.bashrc):**
```bash
alias jarvis="source $HOME/jarvis-venv/bin/activate && $HOME/wake_jarvis.py"
alias jarvis-local="source $HOME/jarvis-venv/bin/activate && $HOME/wake_jarvis_local.py"
# ... etc
```

These point to `/home/boss/wake_jarvis.py` (old) instead of `/home/boss/jarvis-voice/bin/wake_jarvis.py` (new).

---

## Solution Options

### Option 1: Automated Update (Easiest)

Run the update script:

```bash
cd /home/boss/jarvis-voice
./update-aliases.sh
```

This will:
1. Backup your `.bashrc`
2. Comment out old aliases
3. Add new aliases pointing to structured project
4. Safe and reversible!

Then reload:
```bash
source ~/.bashrc
```

---

### Option 2: Manual Update

Edit `~/.bashrc`:
```bash
nano ~/.bashrc
```

**Find and comment out** the old aliases (add `#` at the start):
```bash
# OLD: alias jarvis="source $HOME/jarvis-venv/bin/activate && $HOME/wake_jarvis.py"
# OLD: alias jarvis-local="source $HOME/jarvis-venv/bin/activate && $HOME/wake_jarvis_local.py"
# ... etc
```

**Add new aliases** at the end:
```bash
# Jarvis Voice Assistant - Structured Project
alias jarvis="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis.py"
alias jarvis-local="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis_local.py"
alias say="$HOME/jarvis-voice/bin/say.sh"
alias say-local="$HOME/jarvis-voice/bin/say-local.sh"
alias question="$HOME/jarvis-voice/bin/question.sh"
alias question-local="$HOME/jarvis-voice/bin/question-local.sh"
alias question-mic="$HOME/jarvis-voice/bin/question-mic.sh"
alias question-mic-local="$HOME/jarvis-voice/bin/question-mic-local.sh"

# Shortcuts
alias jarvis-cd="cd $HOME/jarvis-voice"
alias jarvis-env="source $HOME/jarvis-venv/bin/activate"
```

Save and reload:
```bash
source ~/.bashrc
```

---

### Option 3: Temporary Testing (No Changes)

Just comment out the aliases temporarily to test:

```bash
nano ~/.bashrc
```

Add `#` in front of each jarvis alias, then:
```bash
source ~/.bashrc
```

Now test the new structure:
```bash
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate
./jarvis
```

If it works, decide if you want to permanently update aliases.

---

### Option 4: Keep Both (Use Different Names)

Keep old aliases, add new ones with different names:

```bash
# Old (keep as-is)
alias jarvis="source $HOME/jarvis-venv/bin/activate && $HOME/wake_jarvis.py"

# New (add these)
alias jarvis2="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis.py"
alias jarvis-new="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis.py"
```

Then use `jarvis` for old setup, `jarvis-new` for structured project.

---

## Current vs New Aliases

| Command | Old Location | New Location |
|---------|-------------|--------------|
| `jarvis` | `/home/boss/wake_jarvis.py` | `/home/boss/jarvis-voice/bin/wake_jarvis.py` |
| `jarvis-local` | `/home/boss/wake_jarvis_local.py` | `/home/boss/jarvis-voice/bin/wake_jarvis_local.py` |
| `say` | `/home/boss/say.sh` | `/home/boss/jarvis-voice/bin/say.sh` |
| `question` | `/home/boss/question.sh` | `/home/boss/jarvis-voice/bin/question.sh` |

---

## Using the New Aliases

After updating:

```bash
# From anywhere in your system:
jarvis              # Start cloud mode
jarvis-local        # Start local mode

# Quick actions:
say "Hello"         # Cloud TTS
say-local "Hello"   # Local TTS
question "What is 2+2?"
question-local "What is 2+2?"

# Shortcuts:
jarvis-cd           # Go to project directory
jarvis-env          # Activate venv
```

---

## Reverting Changes

If you used the automated script, your backup is at:
```bash
ls ~/.bashrc.backup-*
```

To restore:
```bash
cp ~/.bashrc.backup-YYYYMMDD-HHMMSS ~/.bashrc
source ~/.bashrc
```

---

## Recommendation

**Use Option 1 (automated script)** - it's:
- ✅ Safe (creates backup)
- ✅ Fast (30 seconds)
- ✅ Reversible
- ✅ Comments out old aliases (keeps them for reference)

```bash
cd /home/boss/jarvis-voice
./update-aliases.sh
source ~/.bashrc
jarvis  # Now uses new structured project!
```

---

## Without Aliases

You can also skip aliases entirely and just run directly:

```bash
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate
./jarvis        # Uses symlink to bin/wake_jarvis.py
```

Or full path:
```bash
source ~/jarvis-venv/bin/activate
/home/boss/jarvis-voice/bin/wake_jarvis.py
```

---

**Bottom line:** Your aliases are pointing to the old location. Update them to point to the new structured project, or temporarily disable them to test the new setup!

