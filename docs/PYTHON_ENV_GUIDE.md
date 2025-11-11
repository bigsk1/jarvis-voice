# Python Environment Guide for Jarvis

## Your Current Setup ✅

- **Python**: 3.12.3
- **Environment**: Standard Python venv (`~/jarvis-venv/`)
- **Package Manager**: `uv` (0.8.17) - Modern & Fast! 🚀

---

## Activating the Environment

```bash
source ~/jarvis-venv/bin/activate
```

**Verify it's active:**
```bash
which python  # Should show: /home/boss/jarvis-venv/bin/python
```

**Deactivate when done:**
```bash
deactivate
```

---

## Installing Packages

### Using uv (Recommended - Fast!)

```bash
# Activate venv first
source ~/jarvis-venv/bin/activate

# Install a package with uv
uv pip install openwakeword

# Install from requirements.txt
uv pip install -r requirements.txt

# Upgrade a package
uv pip install --upgrade openwakeword
```

### Using regular pip (Also works)

```bash
source ~/jarvis-venv/bin/activate
pip install openwakeword
```

**Why uv is better:**
- ⚡ 10-100x faster than pip
- 🔒 Better dependency resolution
- 💾 Smart caching
- 🎯 Drop-in replacement for pip

---

## Required Packages for Jarvis

```bash
source ~/jarvis-venv/bin/activate

# Core dependencies
uv pip install openwakeword sounddevice numpy

# For local mode
uv pip install faster-whisper

# Optional: for better audio processing
uv pip install webrtcvad
```

---

## Checking Installed Packages

```bash
source ~/jarvis-venv/bin/activate
pip list | grep -E "openwakeword|sounddevice|faster-whisper"
```

---

## Creating requirements.txt

If you want to document your environment:

```bash
source ~/jarvis-venv/bin/activate
pip freeze > requirements.txt
```

Then you can recreate it elsewhere:
```bash
python3 -m venv new-jarvis-venv
source new-jarvis-venv/bin/activate
uv pip install -r requirements.txt
```

---

## Conda vs venv

You asked about conda - here's the comparison:

| Feature | venv (Your Setup) | conda |
|---------|-------------------|-------|
| **Speed** | ⚡ Fast (especially with uv) | Slower |
| **Size** | Lightweight | Heavy (~3GB) |
| **Python Versions** | Uses system Python | Can install different Python versions |
| **Package Sources** | PyPI only | conda-forge + PyPI |
| **Complexity** | Simple | More complex |
| **Best For** | Python-only projects | Multi-language, data science |

**Recommendation for Jarvis**: Stick with venv + uv! ✅

You don't need conda unless you:
- Need to switch Python versions frequently
- Use non-Python dependencies (R, Julia, etc.)
- Have complex scientific computing needs

Your current setup is perfect for Jarvis! 🎉

---

## Troubleshooting

### "Command not found" after activation

Check venv path:
```bash
ls ~/jarvis-venv/bin/activate
```

If it doesn't exist, recreate:
```bash
python3 -m venv ~/jarvis-venv
```

### Packages not found

Make sure venv is activated:
```bash
source ~/jarvis-venv/bin/activate
which python  # Should be in jarvis-venv/
```

### uv not working

Check uv installation:
```bash
uv --version
which uv  # Should show: /home/boss/.local/bin/uv
```

If missing, reinstall:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Quick Reference

```bash
# Activate
source ~/jarvis-venv/bin/activate

# Install package
uv pip install PACKAGE_NAME

# List packages
pip list

# Deactivate
deactivate
```

---

**Your setup is great - no need to change anything!** 🚀

