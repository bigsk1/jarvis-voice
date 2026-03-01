# SSH Remote Tool

Execute commands on remote hosts via SSH with secure credential management and automatic session handling.

## Overview

The `ssh_remote` tool allows Jarvis to connect to remote servers, execute commands, manage packages, and perform administrative tasks—all without leaving orphaned SSH sessions.

## Features

- **Secure credential storage**: SSH keys in filesystem, sudo passwords in `.env` files
- **Stateless connections**: Opens, executes, closes—no orphaned sessions
- **Output truncation**: Prevents context overflow (configurable limit)
- **Multi-command support**: Execute sequences in a single session
- **Apt management**: Built-in update/upgrade with package detection

## Configuration

### 1. SSH Host Configuration (`config/ssh.json`)

```json
{
  "hosts": {
    "vps2": {
      "host": "your.vps.ip.address",
      "user": "boss",
      "port": 22,
      "key_path": "~/.ssh/vps2/id_ed25519",
      "sudo_env": "VPS2_SUDO_PASS",
      "description": "VPS2 remote server"
    },
    "production": {
      "host": "prod.example.com",
      "user": "deploy",
      "port": 22,
      "key_path": "~/.ssh/prod/id_rsa",
      "sudo_env": "PROD_SUDO_PASS",
      "description": "Production server"
    }
  },
  "defaults": {
    "output_limit": 150,
    "timeout": 60,
    "connect_timeout": 10
  }
}
```

> **Note**: `config/ssh.json` is gitignored. Copy from `config/ssh.json.example`.

### 2. Sudo Passwords (`config/cloud.env` or `config/local.env`)

```bash
# SSH Remote Tool - Sudo Passwords
VPS2_SUDO_PASS="your_sudo_password_here"
PROD_SUDO_PASS="production_sudo_password"
```

### 3. SSH Key Setup

```bash
# Generate or copy your SSH key
mkdir -p ~/.ssh/vps2
cp /path/to/your/key ~/.ssh/vps2/id_ed25519

# Set correct permissions
chmod 600 ~/.ssh/vps2/id_ed25519
chmod 644 ~/.ssh/vps2/id_ed25519.pub
```

## Actions

### `list_hosts` - Show Configured Hosts

```json
{"action": "list_hosts"}
```

Returns all hosts configured in `ssh.json`.

### `test` - Test SSH Connectivity

```json
{"action": "test", "host": "vps2"}
```

Connects, runs hostname/uname, reports connection time.

### `run` - Execute Single Command

```json
{
  "action": "run",
  "host": "vps2",
  "command": "df -h && free -h",
  "sudo": false
}
```

**With sudo:**
```json
{
  "action": "run",
  "host": "vps2",
  "command": "systemctl restart nginx",
  "sudo": true
}
```

### `apt_update` - Package Management

```json
{
  "action": "apt_update",
  "host": "vps2",
  "upgrade": true
}
```

- Runs `apt update`
- Lists upgradable packages
- Optionally runs `apt upgrade -y` (if `upgrade: true`)

**Check only (no upgrade):**
```json
{
  "action": "apt_update",
  "host": "vps2",
  "upgrade": false
}
```

### `multi` - Execute Multiple Commands

```json
{
  "action": "multi",
  "host": "vps2",
  "commands": [
    "uptime",
    "whoami",
    "df -h",
    "docker ps"
  ],
  "sudo": false,
  "stop_on_error": true
}
```

Executes commands sequentially in a single SSH session.

## Parameters Reference

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | `list_hosts`, `test`, `run`, `apt_update`, `multi` |
| `host` | string | For most | Host alias from `ssh.json` |
| `command` | string | For `run` | Command to execute |
| `commands` | array | For `multi` | List of commands |
| `sudo` | boolean | No | Run with sudo (default: false) |
| `upgrade` | boolean | No | For `apt_update`: run upgrade (default: true) |
| `stop_on_error` | boolean | No | For `multi`: stop on failure (default: true) |
| `output_limit` | integer | No | Max output lines (default: 150) |

## Usage Examples

### Via Jarvis (natural language)

```
"ssh into vps2 and check disk space"
"run apt update on vps2"
"update packages on vps2"
"check if nginx is running on vps2"
"run docker ps on vps2"
"execute 'ls -la /var/log' on vps2"
```

### Via CLI (direct)

```bash
# Test connection
python3 skills/ssh_remote.py '{"action": "test", "host": "vps2"}'

# Run command
python3 skills/ssh_remote.py '{"action": "run", "host": "vps2", "command": "uptime"}'

# Apt update (check only)
python3 skills/ssh_remote.py '{"action": "apt_update", "host": "vps2", "upgrade": false}'

# Multiple commands
python3 skills/ssh_remote.py '{"action": "multi", "host": "vps2", "commands": ["whoami", "pwd", "ls"]}'
```

## Security Model

### Credentials Never Exposed

1. **SSH keys**: Stored in filesystem, path in `ssh.json`
2. **Sudo passwords**: Stored in `.env`, referenced by env var name
3. **No credentials in git**: Both `ssh.json` and `.env` files are gitignored

### Session Lifecycle

```
Tool Call → Connect → Execute → Close
                ↓
         (always closes in finally block)
```

- No persistent connections
- No orphaned sessions
- Each tool call is independent

### Output Handling

- Default limit: 150 lines
- Truncates from the beginning, keeps recent output
- Prevents context window overflow
- Can save full output to stash if needed

## Adding a New Host

1. **Add SSH key**:
   ```bash
   mkdir -p ~/.ssh/newhost
   cp /path/to/key ~/.ssh/newhost/id_ed25519
   chmod 600 ~/.ssh/newhost/id_ed25519
   ```

2. **Add to `config/ssh.json`**:
   ```json
   "newhost": {
     "host": "192.168.1.100",
     "user": "admin",
     "port": 22,
     "key_path": "~/.ssh/newhost/id_ed25519",
     "sudo_env": "NEWHOST_SUDO_PASS",
     "description": "New server"
   }
   ```

3. **Add sudo password to `.env`**:
   ```bash
   NEWHOST_SUDO_PASS="your_password"
   ```

4. **Test connection**:
   ```bash
   python3 skills/ssh_remote.py '{"action": "test", "host": "newhost"}'
   ```

## Troubleshooting

### Connection Failed

```bash
# Check SSH key permissions
ls -la ~/.ssh/vps2/
# Should be: 600 for private key, 644 for public

# Test manual SSH
ssh -i ~/.ssh/vps2/id_ed25519 user@host
```

### Sudo Password Not Working

```bash
# Verify env var is set
grep "VPS2_SUDO_PASS" config/cloud.env

# Test sudo manually on remote
ssh user@host "echo 'password' | sudo -S whoami"
```

### Command Timeout

Increase timeout in `ssh.json`:
```json
"defaults": {
  "timeout": 120
}
```

Or per-host:
```json
"slowhost": {
  "host": "...",
  "timeout": 300
}
```

## Files

| File | Purpose |
|------|---------|
| `skills/ssh_remote.py` | Tool implementation |
| `skills/ssh_remote.tool.json` | Tool definition for LLM |
| `config/ssh.json` | Host configuration (gitignored) |
| `config/ssh.json.example` | Template for ssh.json |

## Dependencies

- **paramiko**: Python SSH library (`pip install paramiko`)
