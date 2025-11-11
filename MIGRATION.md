# Migration Guide

## Migrating from Old Structure to New Structure

Your old Jarvis setup (scattered files in `/home/boss/`) still works! This new structure is designed to **coexist** safely. Here's how to migrate.

---

## Quick Migration Steps

### 1. Run Setup

```bash
cd /home/boss/jarvis-voice
./setup.sh
```

This will:
- Check dependencies
- Create directories
- Initialize git
- Create symlinks

### 2. Test New Structure

**Test Cloud Mode:**
```bash
source ~/jarvis-venv/bin/activate
cd /home/boss/jarvis-voice
./jarvis  # or ./bin/wake_jarvis.py
```

**Test Local Mode:**
```bash
source ~/jarvis-venv/bin/activate
cd /home/boss/jarvis-voice
./jarvis-local  # or ./bin/wake_jarvis_local.py
```

### 3. Verify Functionality

Say "Hey Jarvis" and test a few interactions. Verify:
- ✅ Wake word detection works
- ✅ Recording works (SoX)
- ✅ Transcription works
- ✅ Responses are spoken (TTS)
- ✅ Audio files saved correctly

### 4. Once Verified

When you're confident the new structure works:

**Option A: Keep Both (Recommended)**
- Keep old scripts as backup in `/home/boss/`
- Use new structure for daily use
- Old scripts remain functional

**Option B: Clean Up Old Files**
```bash
# Create backup first!
cd /home/boss
mkdir old-jarvis-backup
mv wake_jarvis.py old-jarvis-backup/
mv wake_jarvis_local.py old-jarvis-backup/
mv say*.sh old-jarvis-backup/
mv question*.sh old-jarvis-backup/
mv stt_local.py old-jarvis-backup/
# etc...
```

---

## What's Different?

### Old Structure
```
/home/boss/
├── wake_jarvis.py           # Hardcoded config
├── say.sh                    # API key in file
├── question-mic.sh           # Hardcoded paths
├── audio/                    # Mixed cloud/local
└── (everything scattered)
```

### New Structure
```
/home/boss/jarvis-voice/
├── bin/                      # All executables
├── lib/                      # Shared code
├── config/                   # Centralized settings
├── skills/                   # Tools/automation
├── orchestrator/             # Brain layer
└── audio/                    # Organized storage
```

---

## Config Migration

### Cloud Config

Your old API key and settings from scattered scripts are now in:
```bash
nano config/cloud.env
```

**What moved:**
- `OPENAI_API_KEY` (from say.sh, question-mic.sh, etc.)
- Device settings (from wake_jarvis.py)
- TTS personality (from say.sh)
- Threshold values (from wake_jarvis.py)

### Local Config

Your local endpoints are now in:
```bash
nano config/local.env
```

**What moved:**
- Ollama URL (from question-local.sh)
- Kokoro TTS URL (from say-local.sh)
- Model names (from question-local.sh)
- All other settings

---

## Troubleshooting Migration

### "Config file not found"
```bash
cd /home/boss/jarvis-voice
cp config/config.env.template config/cloud.env
# Edit with your API key
nano config/cloud.env
```

### "No such file or directory" when running `./jarvis`
```bash
cd /home/boss/jarvis-voice
chmod +x bin/*.py bin/*.sh
```

### "Import error: config_loader"
Make sure you're running from the project directory or using the symlinks:
```bash
cd /home/boss/jarvis-voice
./bin/wake_jarvis.py
```

### Settings seem wrong
Check that your tuned values made it to config files:
```bash
grep TRIGGER_THRESHOLD config/cloud.env
grep MIN_RMS config/cloud.env
```

These should match your old working values.

---

## Rollback Plan

If something goes wrong, simply go back to your old scripts:

```bash
cd /home/boss
source ~/jarvis-venv/bin/activate
python3 wake_jarvis.py   # or wake_jarvis_local.py
```

Your old setup is **completely untouched** and still works!

---

## Benefits of New Structure

✅ **Version Control**: Git tracks all changes  
✅ **Centralized Config**: Edit once, affects all scripts  
✅ **Organized**: Easy to find and modify components  
✅ **Extensible**: Ready for tools, orchestrator, MCP  
✅ **Safe Experimentation**: Feature branches prevent breakage  
✅ **Better Backups**: Can git-archive entire project  
✅ **Cleaner Home Directory**: No more scattered files  

---

## Next Steps After Migration

1. **Create your first feature branch**:
   ```bash
   cd /home/boss/jarvis-voice
   git checkout -b feature/test-new-greeting
   # Modify WAKE_GREETING in config/cloud.env
   # Test it
   git commit -am "Test new greeting"
   git checkout master  # go back if you don't like it
   ```

2. **Add a custom tool**:
   ```bash
   cp skills/example_tool.py skills/mytool.py
   nano skills/mytool.py
   chmod +x skills/mytool.py
   # Test: echo '{"param":"value"}' | ./skills/mytool.py
   ```

3. **Set up systemd service** (optional):
   ```bash
   # Create ~/.config/systemd/user/jarvis.service
   # Point ExecStart to /home/boss/jarvis-voice/bin/wake_jarvis.py
   systemctl --user enable jarvis.service
   systemctl --user start jarvis.service
   ```

---

## Need Help?

- Check `README.md` for usage
- Check `orchestrator/README.md` for tool development
- Check `skills/README.md` for creating skills
- Check original `/home/boss/jarvis-docs/jarvis-voice-architecture.md` for deep technical details

---

**Happy migrating! Your old setup is safe, so feel free to experiment! 🚀**

