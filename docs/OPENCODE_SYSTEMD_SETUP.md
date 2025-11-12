# OpenCode Systemd Service Setup

## Installation

1. **Copy service file to systemd directory:**
   ```bash
   sudo cp systemd/opencode-jarvis.service /etc/systemd/system/
   ```

2. **Reload systemd and enable service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable opencode-jarvis.service
   sudo systemctl start opencode-jarvis.service
   ```

3. **Check status:**
   ```bash
   sudo systemctl status opencode-jarvis.service
   ```

4. **View logs:**
   ```bash
   sudo journalctl -u opencode-jarvis.service -f
   ```

## Configuration

### Step 1: OpenCode Config (Ollama Support)

Run the setup script to configure OpenCode with Ollama provider:

```bash
./bin/setup-opencode-config.sh
```

This creates `~/.config/opencode/opencode.json` with:
- Ollama provider (from your `local.env` OLLAMA_BASE_URL)
- OpenAI provider (uses OPENAI_API_KEY env var)
- Anthropic provider (uses ANTHROPIC_API_KEY env var)

### Step 2: Environment Variables for Systemd

**Important:** The systemd service needs access to API keys. Create the environment file:

```bash
./bin/create-opencode-env.sh
```

This creates `~/.config/opencode/jarvis-env.env` with API keys from `config/cloud.env`.

**After updating API keys**, run:
```bash
./bin/update-opencode-service.sh
```

This updates the env file and restarts the service.

### Jarvis Config

Enable/disable OpenCode in Jarvis:

**`config/local.env`** or **`config/cloud.env`**:
```bash
OPENCODE_ENABLED=true   # Set to false to disable
OPENCODE_BASE_URL="http://localhost:4096"
```

When `OPENCODE_ENABLED=false`, the `opencode` tool will not be registered and Jarvis will skip it.

## Usage

### Start/Stop Service

```bash
# Start
sudo systemctl start opencode-jarvis.service

# Stop
sudo systemctl stop opencode-jarvis.service

# Restart
sudo systemctl restart opencode-jarvis.service

# Check status
sudo systemctl status opencode-jarvis.service
```

### Verify OpenCode is Running

```bash
curl http://localhost:4096/config
```

Should return OpenCode config JSON.

## Troubleshooting

### Service won't start

1. Check if opencode binary exists:
   ```bash
   which opencode
   ```

2. Check service logs:
   ```bash
   sudo journalctl -u opencode-jarvis.service -n 50
   ```

3. Test manual start:
   ```bash
   /home/boss/.opencode/bin/opencode serve --port 4096 --hostname 127.0.0.1
   ```

### OpenCode not accessible

1. Check if port 4096 is in use:
   ```bash
   netstat -tuln | grep 4096
   ```

2. Check firewall:
   ```bash
   sudo ufw status
   ```

### Jarvis can't find OpenCode tool

1. Check `OPENCODE_ENABLED` in your `.env` file
2. Restart Jarvis to reload tool registry
3. Check tool discovery output when starting Jarvis

### Authentication Errors ("x-api-key header is required")

**Symptom:** OpenCode returns authentication errors when using Anthropic/OpenAI providers.

**Solution:**

1. **Create environment file:**
   ```bash
   ./bin/create-opencode-env.sh
   ```

2. **Update and restart service:**
   ```bash
   ./bin/update-opencode-service.sh
   ```

3. **Verify API keys are loaded:**
   ```bash
   # Check env file exists and has keys
   cat ~/.config/opencode/jarvis-env.env | sed 's/=.*/=***/'
   
   # Verify service is using the env file
   sudo systemctl show opencode-jarvis.service | grep EnvironmentFile
   ```

4. **Test authentication:**
   ```bash
   ./tests/integration/test-opencode-integration.sh
   ```

**Note:** The systemd service reads API keys from `~/.config/opencode/jarvis-env.env`. This file is created automatically from `config/cloud.env` when you run `create-opencode-env.sh`.

**Note:** If you update API keys in config/cloud.env later, just run ./bin/update-opencode-service.sh 

