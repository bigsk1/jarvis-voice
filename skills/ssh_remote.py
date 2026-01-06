#!/usr/bin/env python3
"""
SSH Remote Tool - Execute commands on remote hosts via SSH.
Supports: run commands, sudo commands, multi-command sequences, apt updates.
Uses Paramiko for clean session management - no orphaned connections.

Security:
- SSH keys stored in paths defined in config/ssh.json
- Sudo passwords stored in .env files, referenced by env var name
- Connections are always closed after use (finally block)
- Output truncated by default to prevent context overflow
"""
import sys
import os
import json
import time
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value

# Import paramiko
try:
    import paramiko
except ImportError:
    print(json.dumps({
        "ok": False,
        "error": "paramiko not installed. Run: pip install paramiko",
        "speech": "SSH library not available"
    }))
    sys.exit(1)

# Config paths
CONFIG_DIR = Path(__file__).parent.parent / "config"
SSH_CONFIG_PATH = CONFIG_DIR / "ssh.json"

def load_ssh_config() -> Dict[str, Any]:
    """Load SSH host configuration."""
    if not SSH_CONFIG_PATH.exists():
        raise FileNotFoundError(f"SSH config not found at {SSH_CONFIG_PATH}. Copy ssh.json.example to ssh.json")
    
    with open(SSH_CONFIG_PATH) as f:
        return json.load(f)

def get_host_config(host_alias: str) -> Dict[str, Any]:
    """Get configuration for a specific host."""
    config = load_ssh_config()
    hosts = config.get("hosts", {})
    
    if host_alias not in hosts:
        available = list(hosts.keys())
        raise ValueError(f"Host '{host_alias}' not found. Available: {available}")
    
    host_config = hosts[host_alias]
    defaults = config.get("defaults", {})
    
    # Merge defaults with host config
    return {
        "host": host_config["host"],
        "user": host_config.get("user", "root"),
        "port": host_config.get("port", 22),
        "key_path": os.path.expanduser(host_config.get("key_path", "~/.ssh/id_rsa")),
        "sudo_env": host_config.get("sudo_env"),
        "description": host_config.get("description", ""),
        "output_limit": host_config.get("output_limit", defaults.get("output_limit", 150)),
        "timeout": host_config.get("timeout", defaults.get("timeout", 60)),
        "connect_timeout": host_config.get("connect_timeout", defaults.get("connect_timeout", 10)),
    }

def connect_ssh(host_config: Dict[str, Any]) -> paramiko.SSHClient:
    """Create SSH connection to host."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    key_path = host_config["key_path"]
    if not os.path.exists(key_path):
        raise FileNotFoundError(f"SSH key not found: {key_path}")
    
    try:
        # Try loading key (handles both RSA and Ed25519)
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    except paramiko.ssh_exception.SSHException:
        try:
            private_key = paramiko.Ed25519Key.from_private_key_file(key_path)
        except:
            # Try as generic key
            private_key = None
    
    connect_kwargs = {
        "hostname": host_config["host"],
        "port": host_config["port"],
        "username": host_config["user"],
        "timeout": host_config["connect_timeout"],
        "allow_agent": True,
        "look_for_keys": True,
    }
    
    if private_key:
        connect_kwargs["pkey"] = private_key
    else:
        connect_kwargs["key_filename"] = key_path
    
    client.connect(**connect_kwargs)
    return client

def truncate_output(output: str, limit: int, label: str = "output") -> Tuple[str, bool]:
    """Truncate output to last N lines if too long."""
    lines = output.split('\n')
    if len(lines) > limit:
        truncated = '\n'.join(lines[-limit:])
        return f"[...truncated {len(lines) - limit} lines...]\n{truncated}", True
    return output, False

def run_command(
    client: paramiko.SSHClient,
    command: str,
    timeout: int = 60,
    output_limit: int = 150,
    sudo: bool = False,
    sudo_password: Optional[str] = None
) -> Dict[str, Any]:
    """Execute a command on the remote host."""
    
    if sudo:
        if sudo_password:
            # Use -S to read password from stdin, with proper escaping
            command = f"echo '{sudo_password}' | sudo -S bash -c '{command}'"
        else:
            # Try passwordless sudo
            command = f"sudo -n {command}"
    
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    
    # Wait for command to complete
    exit_code = stdout.channel.recv_exit_status()
    
    stdout_text = stdout.read().decode('utf-8', errors='replace')
    stderr_text = stderr.read().decode('utf-8', errors='replace')
    
    # Clean up sudo password prompt from stderr if present
    if sudo and sudo_password:
        stderr_text = '\n'.join(
            line for line in stderr_text.split('\n') 
            if not line.startswith('[sudo]') and 'password' not in line.lower()
        )
    
    # Truncate if needed
    stdout_truncated, was_truncated_out = truncate_output(stdout_text, output_limit, "stdout")
    stderr_truncated, was_truncated_err = truncate_output(stderr_text, output_limit // 2, "stderr")
    
    return {
        "exit_code": exit_code,
        "stdout": stdout_truncated,
        "stderr": stderr_truncated,
        "truncated": was_truncated_out or was_truncated_err,
        "success": exit_code == 0
    }

def list_hosts() -> Dict[str, Any]:
    """List all configured SSH hosts."""
    config = load_ssh_config()
    hosts = config.get("hosts", {})
    
    host_list = []
    for alias, details in hosts.items():
        host_list.append({
            "alias": alias,
            "host": details.get("host"),
            "user": details.get("user"),
            "description": details.get("description", "")
        })
    
    return {
        "ok": True,
        "speech": f"Found {len(host_list)} configured SSH hosts",
        "data": {"hosts": host_list, "count": len(host_list)}
    }

def test_connection(host_alias: str) -> Dict[str, Any]:
    """Test SSH connectivity to a host."""
    host_config = get_host_config(host_alias)
    client = None
    
    try:
        start = time.time()
        client = connect_ssh(host_config)
        connect_time = time.time() - start
        
        # Run simple test command
        result = run_command(client, "echo 'SSH connection successful' && hostname && uname -a", 
                           timeout=10, output_limit=10)
        
        return {
            "ok": True,
            "speech": f"Successfully connected to {host_alias}",
            "data": {
                "host": host_alias,
                "connect_time_seconds": round(connect_time, 2),
                "remote_info": result["stdout"].strip()
            }
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "speech": f"Failed to connect to {host_alias}: {e}"
        }
    finally:
        if client:
            client.close()

def execute_command(
    host_alias: str,
    command: str,
    sudo: bool = False,
    output_limit: Optional[int] = None
) -> Dict[str, Any]:
    """Execute a command on a remote host."""
    host_config = get_host_config(host_alias)
    client = None
    
    # Get sudo password if needed
    sudo_password = None
    if sudo and host_config.get("sudo_env"):
        sudo_password = get_config_value(host_config["sudo_env"])
        if not sudo_password:
            return {
                "ok": False,
                "error": f"Sudo password env var {host_config['sudo_env']} not set",
                "speech": f"Sudo password not configured for {host_alias}"
            }
    
    limit = output_limit or host_config["output_limit"]
    
    try:
        client = connect_ssh(host_config)
        
        result = run_command(
            client,
            command,
            timeout=host_config["timeout"],
            output_limit=limit,
            sudo=sudo,
            sudo_password=sudo_password
        )
        
        if result["success"]:
            speech = f"Command completed on {host_alias}"
            if result["truncated"]:
                speech += " (output truncated)"
        else:
            speech = f"Command failed on {host_alias} with exit code {result['exit_code']}"
        
        return {
            "ok": result["success"],
            "speech": speech,
            "data": {
                "host": host_alias,
                "command": command,
                "exit_code": result["exit_code"],
                "stdout": result["stdout"],
                "stderr": result["stderr"] if result["stderr"] else None,
                "truncated": result["truncated"]
            }
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "speech": f"SSH error on {host_alias}: {e}"
        }
    finally:
        if client:
            client.close()

def apt_update(host_alias: str, upgrade: bool = True) -> Dict[str, Any]:
    """Run apt update (and optionally upgrade) on remote host."""
    host_config = get_host_config(host_alias)
    client = None
    
    # Get sudo password
    sudo_password = None
    if host_config.get("sudo_env"):
        sudo_password = get_config_value(host_config["sudo_env"])
        if not sudo_password:
            return {
                "ok": False,
                "error": f"Sudo password env var {host_config['sudo_env']} not set",
                "speech": f"Sudo password not configured for {host_alias}"
            }
    
    try:
        client = connect_ssh(host_config)
        
        # Run apt update
        update_result = run_command(
            client,
            "apt update",
            timeout=120,
            output_limit=50,
            sudo=True,
            sudo_password=sudo_password
        )
        
        if not update_result["success"]:
            return {
                "ok": False,
                "speech": f"apt update failed on {host_alias}",
                "data": {
                    "host": host_alias,
                    "stage": "update",
                    "exit_code": update_result["exit_code"],
                    "stderr": update_result["stderr"]
                }
            }
        
        # Check for upgradable packages
        check_result = run_command(
            client,
            "apt list --upgradable 2>/dev/null | grep -v 'Listing'",
            timeout=30,
            output_limit=50,
            sudo=False
        )
        
        upgradable = [line for line in check_result["stdout"].split('\n') if line.strip()]
        upgradable_count = len(upgradable)
        
        upgrade_result = None
        if upgrade and upgradable_count > 0:
            # Run apt upgrade with -y flag
            upgrade_result = run_command(
                client,
                "DEBIAN_FRONTEND=noninteractive apt upgrade -y",
                timeout=600,  # 10 min for upgrades
                output_limit=100,
                sudo=True,
                sudo_password=sudo_password
            )
        
        # Determine speech output
        if upgradable_count == 0:
            speech = f"{host_alias} is up to date, no packages to upgrade"
        elif upgrade and upgrade_result:
            if upgrade_result["success"]:
                speech = f"Upgraded {upgradable_count} packages on {host_alias}"
            else:
                speech = f"Upgrade failed on {host_alias}"
        else:
            speech = f"Found {upgradable_count} upgradable packages on {host_alias}"
        
        return {
            "ok": True if not upgrade_result or upgrade_result["success"] else False,
            "speech": speech,
            "data": {
                "host": host_alias,
                "upgradable_count": upgradable_count,
                "upgradable_packages": upgradable[:20] if upgradable else [],  # First 20
                "upgrade_performed": upgrade and upgradable_count > 0,
                "upgrade_success": upgrade_result["success"] if upgrade_result else None,
                "upgrade_output": upgrade_result["stdout"][-500:] if upgrade_result else None
            }
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "speech": f"apt update error on {host_alias}: {e}"
        }
    finally:
        if client:
            client.close()

def multi_command(host_alias: str, commands: List[str], sudo: bool = False, stop_on_error: bool = True) -> Dict[str, Any]:
    """Execute multiple commands in sequence on a remote host."""
    host_config = get_host_config(host_alias)
    client = None
    
    # Get sudo password if needed
    sudo_password = None
    if sudo and host_config.get("sudo_env"):
        sudo_password = get_config_value(host_config["sudo_env"])
        if not sudo_password:
            return {
                "ok": False,
                "error": f"Sudo password env var {host_config['sudo_env']} not set",
                "speech": f"Sudo password not configured for {host_alias}"
            }
    
    try:
        client = connect_ssh(host_config)
        
        results = []
        all_success = True
        
        for i, cmd in enumerate(commands):
            result = run_command(
                client,
                cmd,
                timeout=host_config["timeout"],
                output_limit=host_config["output_limit"] // len(commands),  # Split output limit
                sudo=sudo,
                sudo_password=sudo_password
            )
            
            results.append({
                "command": cmd,
                "exit_code": result["exit_code"],
                "stdout": result["stdout"][:500] if result["stdout"] else "",  # Limit each
                "stderr": result["stderr"][:200] if result["stderr"] else "",
                "success": result["success"]
            })
            
            if not result["success"]:
                all_success = False
                if stop_on_error:
                    break
        
        successful = sum(1 for r in results if r["success"])
        
        return {
            "ok": all_success,
            "speech": f"Executed {successful}/{len(commands)} commands on {host_alias}",
            "data": {
                "host": host_alias,
                "total_commands": len(commands),
                "successful": successful,
                "failed": len(results) - successful,
                "stopped_early": len(results) < len(commands),
                "results": results
            }
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "speech": f"SSH error on {host_alias}: {e}"
        }
    finally:
        if client:
            client.close()

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        action = args.get('action', 'run')
        
        if action == 'list_hosts':
            result = list_hosts()
        
        elif action == 'test':
            host = args.get('host')
            if not host:
                result = {"ok": False, "error": "host parameter required", "speech": "Host name required"}
            else:
                result = test_connection(host)
        
        elif action == 'run':
            host = args.get('host')
            command = args.get('command')
            if not host or not command:
                result = {"ok": False, "error": "host and command required", "speech": "Host and command required"}
            else:
                result = execute_command(
                    host,
                    command,
                    sudo=args.get('sudo', False),
                    output_limit=args.get('output_limit')
                )
        
        elif action == 'apt_update':
            host = args.get('host')
            if not host:
                result = {"ok": False, "error": "host parameter required", "speech": "Host name required"}
            else:
                result = apt_update(host, upgrade=args.get('upgrade', True))
        
        elif action == 'multi':
            host = args.get('host')
            commands = args.get('commands', [])
            if not host or not commands:
                result = {"ok": False, "error": "host and commands required", "speech": "Host and commands list required"}
            else:
                result = multi_command(
                    host,
                    commands,
                    sudo=args.get('sudo', False),
                    stop_on_error=args.get('stop_on_error', True)
                )
        
        else:
            result = {"ok": False, "error": f"Unknown action: {action}", "speech": "Unknown SSH action"}
        
        print(json.dumps(result))
        
    except FileNotFoundError as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": "SSH configuration file not found"
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"SSH error: {str(e)}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()
