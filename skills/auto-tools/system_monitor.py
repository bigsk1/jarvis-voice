#!/usr/bin/env python3
"""
System Monitor Tool - Comprehensive system monitoring using psutil.
Provides CPU, memory, disk, process, network, and uptime information.
"""
import sys
import os
import json
from datetime import datetime, timedelta

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value

try:
    import psutil
except ImportError:
    psutil = None

def get_cpu_usage():
    """Get CPU usage statistics."""
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_per_core = psutil.cpu_percent(interval=1, percpu=True)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_count_physical = psutil.cpu_count(logical=False)
    
    return {
        "total_percent": cpu_percent,
        "per_core_percent": cpu_per_core,
        "logical_cores": cpu_count,
        "physical_cores": cpu_count_physical
    }

def get_memory_usage():
    """Get memory usage statistics."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    return {
        "ram": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent_used": mem.percent
        },
        "swap": {
            "total_gb": round(swap.total / (1024**3), 2),
            "used_gb": round(swap.used / (1024**3), 2),
            "free_gb": round(swap.free / (1024**3), 2),
            "percent_used": swap.percent
        }
    }

def get_disk_usage():
    """Get disk usage per mount point."""
    disks = []
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({
                "device": partition.device,
                "mountpoint": partition.mountpoint,
                "fstype": partition.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "percent_used": usage.percent
            })
        except PermissionError:
            continue
    
    return disks

def get_process_list(limit=10, sort_by="cpu"):
    """Get list of running processes."""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
        try:
            pinfo = proc.info
            processes.append({
                "pid": pinfo['pid'],
                "name": pinfo['name'],
                "cpu_percent": round(pinfo['cpu_percent'] or 0, 2),
                "memory_percent": round(pinfo['memory_percent'] or 0, 2),
                "status": pinfo['status']
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # Sort by CPU or memory
    if sort_by == "memory":
        processes.sort(key=lambda x: x['memory_percent'], reverse=True)
    else:
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
    
    return processes[:limit]

def get_network_stats():
    """Get network I/O statistics."""
    net_io = psutil.net_io_counters()
    
    return {
        "bytes_sent_gb": round(net_io.bytes_sent / (1024**3), 2),
        "bytes_recv_gb": round(net_io.bytes_recv / (1024**3), 2),
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv,
        "errors_in": net_io.errin,
        "errors_out": net_io.errout,
        "drops_in": net_io.dropin,
        "drops_out": net_io.dropout
    }

def get_system_uptime():
    """Get system uptime."""
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_delta = datetime.now() - boot_time
    
    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return {
        "boot_time": boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        "uptime_days": days,
        "uptime_hours": hours,
        "uptime_minutes": minutes,
        "uptime_string": f"{days}d {hours}h {minutes}m"
    }

def main():
    try:
        if psutil is None:
            print(json.dumps({
                "ok": False,
                "error": "psutil library not installed",
                "speech": "System monitoring requires psutil library to be installed."
            }))
            sys.exit(1)
        
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        action = args.get('action', 'all').lower()
        result_data = {}
        speech_parts = []
        
        if action in ['cpu_usage', 'all']:
            cpu_data = get_cpu_usage()
            result_data['cpu'] = cpu_data
            speech_parts.append(f"CPU usage is {cpu_data['total_percent']}%")
        
        if action in ['memory_usage', 'all']:
            mem_data = get_memory_usage()
            result_data['memory'] = mem_data
            speech_parts.append(f"RAM usage is {mem_data['ram']['percent_used']}% ({mem_data['ram']['used_gb']} GB of {mem_data['ram']['total_gb']} GB used)")
        
        if action in ['disk_usage', 'all']:
            disk_data = get_disk_usage()
            result_data['disks'] = disk_data
            if disk_data:
                main_disk = disk_data[0]
                speech_parts.append(f"Main disk is {main_disk['percent_used']}% full ({main_disk['free_gb']} GB free)")
        
        if action in ['process_list', 'all']:
            limit = args.get('limit', 10)
            sort_by = args.get('sort_by', 'cpu')
            proc_data = get_process_list(limit=limit, sort_by=sort_by)
            result_data['processes'] = proc_data
            if proc_data:
                top_proc = proc_data[0]
                speech_parts.append(f"Top process: {top_proc['name']} using {top_proc['cpu_percent']}% CPU")
        
        if action in ['network_stats', 'all']:
            net_data = get_network_stats()
            result_data['network'] = net_data
            speech_parts.append(f"Network: {net_data['bytes_sent_gb']} GB sent, {net_data['bytes_recv_gb']} GB received")
        
        if action in ['system_uptime', 'all']:
            uptime_data = get_system_uptime()
            result_data['uptime'] = uptime_data
            speech_parts.append(f"System uptime: {uptime_data['uptime_string']}")
        
        if not result_data:
            print(json.dumps({
                "ok": False,
                "error": f"Unknown action: {action}",
                "speech": f"Unknown monitoring action: {action}. Available: cpu_usage, memory_usage, disk_usage, process_list, network_stats, system_uptime, all"
            }))
            sys.exit(1)
        
        speech = ". ".join(speech_parts) if speech_parts else "System monitoring complete"
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": result_data
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"System monitoring error: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()