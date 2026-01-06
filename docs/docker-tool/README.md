# Docker Control Tool

Manage Docker containers and compose stacks with safe, structured commands.

## Overview

The `docker_control` tool provides a structured interface for Docker operations, safer and easier to reason about than raw shell commands. It supports container lifecycle management, compose operations, image management, and system cleanup.

## Features

- **Container management**: List, start, stop, restart, inspect, logs, stats
- **Compose operations**: Up, down, restart, pull, build with full options
- **Image management**: List images, pull new images
- **Network/Volume inspection**: List networks and volumes
- **Container exec**: Run commands inside containers
- **System cleanup**: Prune containers, images, volumes, networks

## Actions Reference

### Container Operations

#### `list` - List Containers

```json
{"action": "list", "all": false}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `all` | boolean | false | Include stopped containers |

#### `start` - Start Container

```json
{"action": "start", "container": "nginx"}
```

#### `stop` - Stop Container

```json
{"action": "stop", "container": "nginx", "timeout": 10}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeout` | integer | 10 | Seconds to wait before kill |

#### `restart` - Restart Container

```json
{"action": "restart", "container": "nginx"}
```

#### `logs` - View Container Logs

```json
{
  "action": "logs",
  "container": "nginx",
  "lines": 100,
  "since": "10m"
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lines` | integer | 50 | Number of log lines |
| `since` | string | - | Show logs since (e.g., "10m", "2h", "2024-01-01") |

#### `inspect` - Container Health/Status

```json
{"action": "inspect", "container": "nginx", "full": false}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `full` | boolean | false | Return full inspect JSON |

#### `stats` - Resource Usage

```json
{"action": "stats", "container": "nginx"}
```

Omit `container` to get stats for all running containers.

#### `exec` - Execute Command in Container

```json
{
  "action": "exec",
  "container": "nginx",
  "command": "nginx -t",
  "workdir": "/etc/nginx",
  "user": "root"
}
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `command` | string | Command to run |
| `workdir` | string | Working directory (optional) |
| `user` | string | User to run as (optional) |

### Image Operations

#### `pull` - Pull Docker Image

```json
{"action": "pull", "image": "nginx:latest"}
```

5-minute timeout for large images.

#### `images` - List Images

```json
{"action": "images", "all": false}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `all` | boolean | false | Include dangling images |

### Compose Operations

#### `compose` - Docker Compose Management

```json
{
  "action": "compose",
  "compose_action": "up",
  "compose_file": "/path/to/docker-compose.yml",
  "service": "web",
  "force_recreate": false,
  "build": false,
  "remove_orphans": false
}
```

**Compose Actions:**

| Action | Description | Key Flags |
|--------|-------------|-----------|
| `up` | Start stack | `force_recreate`, `build`, `remove_orphans` |
| `down` | Stop stack | `remove_orphans` |
| `restart` | Restart services | - |
| `pull` | Pull images | - |
| `build` | Build images | - |
| `ps` | List services | - |
| `logs` | View logs | - |
| `stop` | Stop services | - |
| `start` | Start services | - |
| `config` | Validate config | - |

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `compose_action` | string | Required: up, down, restart, pull, build, ps, logs, stop, start, config |
| `compose_file` | string | Path to docker-compose.yml (optional) |
| `service` | string | Specific service name (optional) |
| `force_recreate` | boolean | Force recreate containers on up |
| `build` | boolean | Build images before starting |
| `remove_orphans` | boolean | Remove containers not in compose file |

### Network & Volume Operations

#### `networks` - List Networks

```json
{"action": "networks"}
```

#### `volumes` - List Volumes

```json
{"action": "volumes"}
```

### Cleanup Operations

#### `prune` - System Cleanup

```json
{
  "action": "prune",
  "prune_type": "all",
  "force": true
}
```

| Prune Type | Description |
|------------|-------------|
| `containers` | Remove stopped containers |
| `images` | Remove unused images |
| `volumes` | Remove unused volumes |
| `networks` | Remove unused networks |
| `all` / `system` | Remove all unused resources |

## Usage Examples

### Via Jarvis (natural language)

```
"show me all docker containers"
"restart the nginx container"
"show logs for jarvis-grafana"
"docker compose up in /home/boss/myproject"
"pull the latest postgres image"
"what's the health status of blinko-app"
"prune docker system"
"show docker stats for all containers"
```

### Via CLI (direct)

```bash
# List all containers
python3 skills/auto-tools/docker_control.py '{"action": "list", "all": true}'

# Restart container
python3 skills/auto-tools/docker_control.py '{"action": "restart", "container": "nginx"}'

# Compose up with force recreate
python3 skills/auto-tools/docker_control.py '{
  "action": "compose",
  "compose_action": "up",
  "compose_file": "/home/boss/project/docker-compose.yml",
  "force_recreate": true
}'

# Get container stats
python3 skills/auto-tools/docker_control.py '{"action": "stats", "container": "jarvis-grafana"}'

# Execute command in container
python3 skills/auto-tools/docker_control.py '{
  "action": "exec",
  "container": "jarvis-grafana",
  "command": "grafana-cli --version"
}'

# Prune images
python3 skills/auto-tools/docker_control.py '{"action": "prune", "prune_type": "images"}'
```

## Timeouts

Different operations have different timeouts:

| Operation | Timeout |
|-----------|---------|
| Default | 30s |
| Image pull | 5 minutes |
| Compose up | 3 minutes |
| Compose pull | 5 minutes |
| Compose build | 10 minutes |
| Prune | 2 minutes |
| Exec | 1 minute |

## Output Examples

### Container List

```json
{
  "ok": true,
  "speech": "Found 9 running containers",
  "data": {
    "containers": [
      {
        "id": "75edfc320801",
        "name": "mcp-brave-search",
        "status": "Up 3 days",
        "image": "mcp/brave-search",
        "ports": ""
      },
      {
        "id": "6c81cf9733ee",
        "name": "jarvis-grafana",
        "status": "Up 2 weeks (healthy)",
        "image": "grafana/grafana:10.2.3",
        "ports": "0.0.0.0:3000->3000/tcp"
      }
    ],
    "count": 9
  }
}
```

### Container Stats

```json
{
  "ok": true,
  "speech": "Container jarvis-grafana using 0.59% CPU and 194.9MiB memory",
  "data": {
    "stats": {
      "name": "jarvis-grafana",
      "cpu": "0.59%",
      "memory": "194.9MiB / 30.15GiB",
      "network": "94.4MB / 1.4GB",
      "block_io": "264MB / 189MB"
    }
  }
}
```

### Compose Up

```json
{
  "ok": true,
  "speech": "Docker compose up completed",
  "data": {
    "action": "up",
    "output": "Container nginx Started\nContainer redis Started",
    "compose_file": "/home/boss/project/docker-compose.yml"
  }
}
```

## Permissions

The tool is marked with these permissions:

```json
{
  "dangerous": true,
  "bash": true,
  "network": false,
  "filesystem": true,
  "auto_approve": false
}
```

**Note**: `auto_approve: false` means Jarvis will ask for confirmation before executing Docker commands.

## Comparison: docker_control vs ssh_remote

| Use Case | Tool | Example |
|----------|------|---------|
| Local container management | `docker_control` | List, restart, logs, inspect |
| Local compose operations | `docker_control` | Up, down, pull, build |
| Local arbitrary `docker run` | `execute_bash` | `docker run nginx` |
| Remote any docker command | `ssh_remote` | `docker ps`, `docker run` |
| Remote compose operations | `ssh_remote` | Full flexibility |

## Files

| File | Purpose |
|------|---------|
| `skills/auto-tools/docker_control.py` | Tool implementation |
| `skills/auto-tools/docker_control.tool.json` | Tool definition for LLM |
| `skills/auto-tools/docker_control.report.json` | Build report (auto-generated) |

## Troubleshooting

### Docker Not Found

```bash
# Verify Docker is installed
docker --version

# Check Docker daemon is running
sudo systemctl status docker
```

### Permission Denied

```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in, or:
newgrp docker
```

### Compose File Not Found

Specify the full path:
```json
{
  "action": "compose",
  "compose_action": "up",
  "compose_file": "/full/path/to/docker-compose.yml"
}
```

### Command Timeout

For long-running operations, the tool has built-in extended timeouts. If still timing out, consider:
- Breaking into smaller operations
- Using `ssh_remote` for remote operations with custom timeout

## Future Enhancements

Potential additions:
- `run` action for `docker run` commands
- CVE scanning integration (Trivy/Docker Scout)
- Container resource limits management
- Docker Swarm support
