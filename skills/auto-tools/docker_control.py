#!/usr/bin/env python3
"""
Docker Control Tool - Safe, structured Docker operations.
Supports: list/start/stop/restart containers, pull images, logs, health checks, 
compose management, images, networks, volumes, exec, prune.
"""
import sys
import os
import json
import subprocess
import shlex

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config
from paths import assert_not_restricted_read_path

# Timeouts by operation type
TIMEOUTS = {
    'default': 30,
    'pull': 300,      # Image pulls can be slow
    'compose_up': 180,
    'compose_pull': 300,
    'compose_build': 600,
    'prune': 120,
    'exec': 60,
}

def run_command(cmd, timeout_key='default'):
    """Run shell command and return output."""
    timeout = TIMEOUTS.get(timeout_key, TIMEOUTS['default'])
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def list_containers(all_containers=False):
    """List Docker containers."""
    flag = '-a' if all_containers else ''
    cmd = f"docker ps {flag} --format '{{{{.ID}}}}|{{{{.Names}}}}|{{{{.Status}}}}|{{{{.Image}}}}|{{{{.Ports}}}}'"
    stdout, stderr, code = run_command(cmd)
    
    if code != 0:
        return {"ok": False, "error": stderr or "Failed to list containers"}
    
    containers = []
    for line in stdout.split('\n'):
        if line:
            parts = line.split('|')
            if len(parts) >= 4:
                containers.append({
                    "id": parts[0],
                    "name": parts[1],
                    "status": parts[2],
                    "image": parts[3],
                    "ports": parts[4] if len(parts) > 4 else ""
                })
    
    status = "running and stopped" if all_containers else "running"
    return {
        "ok": True,
        "speech": f"Found {len(containers)} {status} containers",
        "data": {"containers": containers, "count": len(containers)}
    }

def start_container(container_name):
    """Start a stopped Docker container."""
    stdout, stderr, code = run_command(f"docker start {container_name}")
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or f"Failed to start {container_name}",
            "speech": f"Failed to start container {container_name}"
        }
    
    return {
        "ok": True,
        "speech": f"Started container {container_name}",
        "data": {"container": container_name, "action": "started"}
    }

def stop_container(container_name, timeout=10):
    """Stop a running Docker container."""
    stdout, stderr, code = run_command(f"docker stop -t {timeout} {container_name}")
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or f"Failed to stop {container_name}",
            "speech": f"Failed to stop container {container_name}"
        }
    
    return {
        "ok": True,
        "speech": f"Stopped container {container_name}",
        "data": {"container": container_name, "action": "stopped"}
    }

def restart_container(container_name):
    """Restart a Docker container."""
    stdout, stderr, code = run_command(f"docker restart {container_name}")
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or f"Failed to restart {container_name}",
            "speech": f"Failed to restart container {container_name}"
        }
    
    return {
        "ok": True,
        "speech": f"Restarted container {container_name}",
        "data": {"container": container_name, "action": "restarted"}
    }

def pull_image(image_name):
    """Pull a Docker image."""
    stdout, stderr, code = run_command(f"docker pull {image_name}", timeout_key='pull')
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or f"Failed to pull {image_name}",
            "speech": f"Failed to pull image {image_name}"
        }
    
    return {
        "ok": True,
        "speech": f"Pulled image {image_name}",
        "data": {"image": image_name, "action": "pulled", "output": stdout[-500:] if len(stdout) > 500 else stdout}
    }

def get_logs(container_name, lines=50, follow=False, since=None):
    """Get container logs."""
    cmd = f"docker logs --tail {lines}"
    if since:
        cmd += f" --since {since}"
    cmd += f" {container_name}"
    
    stdout, stderr, code = run_command(cmd)
    
    # Docker logs go to stderr for some containers
    log_output = stdout or stderr
    
    if code != 0 and not log_output:
        return {
            "ok": False,
            "error": stderr or f"Failed to get logs for {container_name}",
            "speech": f"Failed to get logs for {container_name}"
        }
    
    log_lines = log_output.split('\n') if log_output else []
    return {
        "ok": True,
        "speech": f"Retrieved {len(log_lines)} log lines from {container_name}",
        "data": {
            "container": container_name,
            "logs": log_output,
            "line_count": len(log_lines)
        }
    }

def inspect_container(container_name, full=False):
    """Inspect container health and status."""
    if full:
        cmd = f"docker inspect {container_name}"
    else:
        cmd = f"docker inspect {container_name} --format '{{{{json .State}}}}'"
    
    stdout, stderr, code = run_command(cmd)
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or f"Failed to inspect {container_name}",
            "speech": f"Failed to inspect container {container_name}"
        }
    
    try:
        if full:
            data = json.loads(stdout)
            return {
                "ok": True,
                "speech": f"Full inspection of {container_name}",
                "data": {"container": container_name, "inspect": data}
            }
        
        state = json.loads(stdout)
        health = state.get('Health', {}).get('Status', 'no healthcheck')
        
        return {
            "ok": True,
            "speech": f"Container {container_name} is {state.get('Status')} with health: {health}",
            "data": {
                "container": container_name,
                "status": state.get('Status'),
                "running": state.get('Running'),
                "health": health,
                "exit_code": state.get('ExitCode'),
                "started_at": state.get('StartedAt'),
                "finished_at": state.get('FinishedAt'),
                "error": state.get('Error', '')
            }
        }
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": "Failed to parse inspect output",
            "speech": f"Failed to parse status for {container_name}"
        }

def compose_action(action, compose_file=None, service=None, force_recreate=False, build=False, remove_orphans=False):
    """Manage Docker Compose stacks."""
    valid_actions = ['up', 'down', 'restart', 'pull', 'ps', 'logs', 'build', 'stop', 'start', 'config']
    if action not in valid_actions:
        return {
            "ok": False,
            "error": f"Invalid action. Must be one of: {', '.join(valid_actions)}",
            "speech": "Invalid compose action"
        }
    
    if compose_file:
        compose_file = str(assert_not_restricted_read_path(
            compose_file,
            label="Compose file",
        ))
    file_flag = f"-f {shlex.quote(compose_file)}" if compose_file else ""
    service_flag = service if service else ""
    
    timeout_key = 'default'
    
    if action == 'up':
        flags = ["-d"]  # Always detached
        if force_recreate:
            flags.append("--force-recreate")
        if build:
            flags.append("--build")
        if remove_orphans:
            flags.append("--remove-orphans")
        cmd = f"docker compose {file_flag} up {' '.join(flags)} {service_flag}"
        timeout_key = 'compose_up'
    elif action == 'down':
        flags = []
        if remove_orphans:
            flags.append("--remove-orphans")
        cmd = f"docker compose {file_flag} down {' '.join(flags)}"
    elif action == 'logs':
        cmd = f"docker compose {file_flag} logs --tail 100 {service_flag}"
    elif action == 'pull':
        cmd = f"docker compose {file_flag} pull {service_flag}"
        timeout_key = 'compose_pull'
    elif action == 'build':
        cmd = f"docker compose {file_flag} build {service_flag}"
        timeout_key = 'compose_build'
    elif action == 'config':
        cmd = f"docker compose {file_flag} config"
    else:
        cmd = f"docker compose {file_flag} {action} {service_flag}"
    
    stdout, stderr, code = run_command(cmd, timeout_key=timeout_key)
    
    # Compose outputs to stderr for progress
    output = stdout or stderr
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or f"Compose {action} failed",
            "speech": f"Docker compose {action} failed"
        }
    
    return {
        "ok": True,
        "speech": f"Docker compose {action} completed",
        "data": {
            "action": action,
            "output": output[-1000:] if len(output) > 1000 else output,
            "compose_file": compose_file,
            "service": service
        }
    }

def get_stats(container_name=None):
    """Get container resource usage stats."""
    if container_name:
        cmd = f"docker stats {container_name} --no-stream --format '{{{{.Name}}}}|{{{{.CPUPerc}}}}|{{{{.MemUsage}}}}|{{{{.NetIO}}}}|{{{{.BlockIO}}}}'"
    else:
        cmd = "docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}'"
    
    stdout, stderr, code = run_command(cmd)
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or "Failed to get stats",
            "speech": "Failed to get container stats"
        }
    
    stats = []
    for line in stdout.split('\n'):
        if line:
            parts = line.split('|')
            if len(parts) >= 5:
                stats.append({
                    "name": parts[0],
                    "cpu": parts[1],
                    "memory": parts[2],
                    "network": parts[3],
                    "block_io": parts[4]
                })
    
    if container_name and stats:
        s = stats[0]
        return {
            "ok": True,
            "speech": f"Container {s['name']} using {s['cpu']} CPU and {s['memory'].split('/')[0].strip()} memory",
            "data": {"stats": s}
        }
    
    return {
        "ok": True,
        "speech": f"Stats for {len(stats)} containers",
        "data": {"stats": stats, "count": len(stats)}
    }

def list_images(all_images=False):
    """List Docker images."""
    flag = '-a' if all_images else ''
    cmd = f"docker images {flag} --format '{{{{.Repository}}}}:{{{{.Tag}}}}|{{{{.ID}}}}|{{{{.Size}}}}|{{{{.CreatedSince}}}}'"
    stdout, stderr, code = run_command(cmd)
    
    if code != 0:
        return {"ok": False, "error": stderr or "Failed to list images"}
    
    images = []
    for line in stdout.split('\n'):
        if line:
            parts = line.split('|')
            if len(parts) >= 4:
                images.append({
                    "name": parts[0],
                    "id": parts[1],
                    "size": parts[2],
                    "created": parts[3]
                })
    
    return {
        "ok": True,
        "speech": f"Found {len(images)} images",
        "data": {"images": images, "count": len(images)}
    }

def list_networks():
    """List Docker networks."""
    cmd = "docker network ls --format '{{.ID}}|{{.Name}}|{{.Driver}}|{{.Scope}}'"
    stdout, stderr, code = run_command(cmd)
    
    if code != 0:
        return {"ok": False, "error": stderr or "Failed to list networks"}
    
    networks = []
    for line in stdout.split('\n'):
        if line:
            parts = line.split('|')
            if len(parts) >= 4:
                networks.append({
                    "id": parts[0],
                    "name": parts[1],
                    "driver": parts[2],
                    "scope": parts[3]
                })
    
    return {
        "ok": True,
        "speech": f"Found {len(networks)} networks",
        "data": {"networks": networks, "count": len(networks)}
    }

def list_volumes():
    """List Docker volumes."""
    cmd = "docker volume ls --format '{{.Name}}|{{.Driver}}|{{.Mountpoint}}'"
    stdout, stderr, code = run_command(cmd)
    
    if code != 0:
        return {"ok": False, "error": stderr or "Failed to list volumes"}
    
    volumes = []
    for line in stdout.split('\n'):
        if line:
            parts = line.split('|')
            if len(parts) >= 2:
                volumes.append({
                    "name": parts[0],
                    "driver": parts[1],
                    "mountpoint": parts[2] if len(parts) > 2 else ""
                })
    
    return {
        "ok": True,
        "speech": f"Found {len(volumes)} volumes",
        "data": {"volumes": volumes, "count": len(volumes)}
    }

def exec_command(container_name, command, workdir=None, user=None):
    """Execute a command in a running container."""
    flags = []
    if workdir:
        flags.append(f"-w {workdir}")
    if user:
        flags.append(f"-u {user}")
    
    # Escape command for shell
    escaped_cmd = command.replace('"', '\\"')
    cmd = f"docker exec {' '.join(flags)} {container_name} sh -c \"{escaped_cmd}\""
    
    stdout, stderr, code = run_command(cmd, timeout_key='exec')
    
    output = stdout or stderr
    
    return {
        "ok": code == 0,
        "speech": f"Executed command in {container_name}" if code == 0 else f"Command failed in {container_name}",
        "data": {
            "container": container_name,
            "command": command,
            "exit_code": code,
            "output": output[-2000:] if len(output) > 2000 else output
        }
    }

def prune(prune_type='all', force=True):
    """Clean up Docker resources."""
    valid_types = ['containers', 'images', 'volumes', 'networks', 'all', 'system']
    if prune_type not in valid_types:
        return {"ok": False, "error": f"Invalid prune type. Must be one of: {', '.join(valid_types)}"}
    
    force_flag = "-f" if force else ""
    
    if prune_type == 'all' or prune_type == 'system':
        cmd = f"docker system prune -a {force_flag}"
    elif prune_type == 'containers':
        cmd = f"docker container prune {force_flag}"
    elif prune_type == 'images':
        cmd = f"docker image prune -a {force_flag}"
    elif prune_type == 'volumes':
        cmd = f"docker volume prune {force_flag}"
    elif prune_type == 'networks':
        cmd = f"docker network prune {force_flag}"
    
    stdout, stderr, code = run_command(cmd, timeout_key='prune')
    
    if code != 0:
        return {
            "ok": False,
            "error": stderr or f"Prune {prune_type} failed",
            "speech": f"Docker prune {prune_type} failed"
        }
    
    return {
        "ok": True,
        "speech": f"Docker {prune_type} pruned",
        "data": {"type": prune_type, "output": stdout}
    }

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        action = args.get('action', 'list')
        
        # Check if docker is available
        _, _, code = run_command("docker --version")
        if code != 0:
            print(json.dumps({
                "ok": False,
                "error": "Docker is not installed or not accessible",
                "speech": "Docker is not available on this system"
            }))
            sys.exit(1)
        
        if action == 'list':
            result = list_containers(all_containers=args.get('all', False))
        elif action == 'start':
            container = args.get('container')
            if not container:
                result = {"ok": False, "error": "container parameter required", "speech": "Container name required"}
            else:
                result = start_container(container)
        elif action == 'stop':
            container = args.get('container')
            if not container:
                result = {"ok": False, "error": "container parameter required", "speech": "Container name required"}
            else:
                result = stop_container(container, timeout=args.get('timeout', 10))
        elif action == 'restart':
            container = args.get('container')
            if not container:
                result = {"ok": False, "error": "container parameter required", "speech": "Container name required"}
            else:
                result = restart_container(container)
        elif action == 'pull':
            image = args.get('image')
            if not image:
                result = {"ok": False, "error": "image parameter required", "speech": "Image name required"}
            else:
                result = pull_image(image)
        elif action == 'logs':
            container = args.get('container')
            if not container:
                result = {"ok": False, "error": "container parameter required", "speech": "Container name required"}
            else:
                result = get_logs(
                    container, 
                    lines=args.get('lines', 50),
                    since=args.get('since')
                )
        elif action == 'inspect':
            container = args.get('container')
            if not container:
                result = {"ok": False, "error": "container parameter required", "speech": "Container name required"}
            else:
                result = inspect_container(container, full=args.get('full', False))
        elif action == 'stats':
            result = get_stats(container_name=args.get('container'))
        elif action == 'compose':
            compose_cmd = args.get('compose_action')
            if not compose_cmd:
                result = {"ok": False, "error": "compose_action parameter required", "speech": "Compose action required"}
            else:
                result = compose_action(
                    compose_cmd,
                    compose_file=args.get('compose_file'),
                    service=args.get('service'),
                    force_recreate=args.get('force_recreate', False),
                    build=args.get('build', False),
                    remove_orphans=args.get('remove_orphans', False)
                )
        elif action == 'images':
            result = list_images(all_images=args.get('all', False))
        elif action == 'networks':
            result = list_networks()
        elif action == 'volumes':
            result = list_volumes()
        elif action == 'exec':
            container = args.get('container')
            command = args.get('command')
            if not container or not command:
                result = {"ok": False, "error": "container and command parameters required", "speech": "Container and command required"}
            else:
                result = exec_command(
                    container,
                    command,
                    workdir=args.get('workdir'),
                    user=args.get('user')
                )
        elif action == 'prune':
            result = prune(
                prune_type=args.get('prune_type', 'all'),
                force=args.get('force', True)
            )
        else:
            result = {"ok": False, "error": f"Unknown action: {action}", "speech": "Unknown Docker action"}
        
        print(json.dumps(result))
        
    except subprocess.TimeoutExpired as e:
        print(json.dumps({
            "ok": False,
            "error": f"Docker command timed out after {e.timeout} seconds",
            "speech": "Docker command timed out"
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Docker error: {str(e)}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()
