#!/usr/bin/env python3
"""
System Monitor Tool - Comprehensive system monitoring using psutil.
Provides CPU, memory, disk, process, network, and uptime information.
"""
import sys
import os
import json
import time
from datetime import datetime

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config

try:
    import psutil
except ImportError:
    psutil = None

def get_cpu_usage():
    """Get CPU usage statistics."""
    cpu_per_core = psutil.cpu_percent(interval=1, percpu=True)
    cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 2) if cpu_per_core else psutil.cpu_percent(interval=None)
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
        if (
            partition.fstype in {"squashfs", "devtmpfs"}
            or partition.device.startswith("/dev/loop")
            or partition.mountpoint.startswith("/snap/")
        ):
            continue
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
    proc_list = list(psutil.process_iter(['pid', 'name']))

    for proc in proc_list:
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(0.2)

    for proc in proc_list:
        try:
            pinfo = proc.as_dict(attrs=[
                'pid',
                'ppid',
                'name',
                'cmdline',
                'memory_percent',
                'status',
                'create_time',
                'username',
            ])
            cpu_percent = proc.cpu_percent(interval=None)
            create_time = pinfo.get('create_time')
            age_seconds = max(0, int(time.time() - create_time)) if create_time else None
            cmdline = pinfo.get('cmdline') or []
            processes.append({
                "pid": pinfo['pid'],
                "ppid": pinfo.get('ppid'),
                "name": pinfo['name'],
                "cmdline": " ".join(str(part) for part in cmdline)[:500],
                "cpu_percent": round(cpu_percent or 0, 2),
                "memory_percent": round(pinfo['memory_percent'] or 0, 2),
                "status": pinfo['status'],
                "username": pinfo.get('username'),
                "age_seconds": age_seconds,
                "age_minutes": round(age_seconds / 60, 1) if age_seconds is not None else None,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # Sort by CPU or memory
    if sort_by == "memory":
        processes.sort(key=lambda x: x['memory_percent'], reverse=True)
    else:
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
    
    return processes[:limit]

def _severity_rank(severity):
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 0)

def _add_issue(issues, issue_type, severity, title, detail, dedupe_key, metadata=None):
    issues.append({
        "type": issue_type,
        "severity": severity,
        "title": title,
        "detail": detail,
        "dedupe_key": dedupe_key,
        "metadata": metadata or {}
    })

def _build_summary_markdown(data, analysis):
    top_process = analysis.get("top_process") or {}
    lines = [
        f"- Status: {analysis.get('status', 'unknown')}",
        f"- Issues: {analysis.get('issue_count', 0)}",
        f"- Highest severity: {analysis.get('highest_severity', 'none')}",
    ]
    cpu = data.get("cpu") or {}
    memory = data.get("memory") or {}
    ram = memory.get("ram") or {}
    swap = memory.get("swap") or {}
    uptime = data.get("uptime") or {}
    if cpu:
        lines.append(f"- CPU total: {cpu.get('total_percent')}%")
        lines.append(f"- Hot CPU cores: {analysis.get('hot_core_count', 0)}")
    if ram:
        lines.append(f"- RAM: {ram.get('percent_used')}%")
    if swap:
        lines.append(f"- Swap: {swap.get('percent_used')}%")
    if uptime:
        lines.append(f"- Uptime: {uptime.get('uptime_string')}")
    if top_process:
        lines.append(
            f"- Top process: {top_process.get('name')} "
            f"({top_process.get('cpu_percent')}% CPU, PID {top_process.get('pid')})"
        )
    lines.append("")
    lines.append("Issues:")
    lines.append(analysis.get("issue_summary") or "No threshold issues detected.")
    return "\n".join(lines)

def analyze_health(data, thresholds=None):
    """Convert raw monitor data into compact health issues for workflows."""
    thresholds = thresholds or {}
    cpu_total_threshold = float(thresholds.get("cpu_total_threshold", 90))
    cpu_core_threshold = float(thresholds.get("cpu_core_threshold", 95))
    process_cpu_threshold = float(thresholds.get("process_cpu_threshold", 90))
    process_min_age_minutes = float(thresholds.get("process_min_age_minutes", 5))
    memory_threshold = float(thresholds.get("memory_threshold", 90))
    swap_threshold = float(thresholds.get("swap_threshold", 50))
    disk_threshold = float(thresholds.get("disk_threshold", 90))
    suspicious_min_age_minutes = float(thresholds.get("suspicious_min_age_minutes", 10))
    suspicious_keywords = [
        str(item).lower()
        for item in thresholds.get(
            "suspicious_cmd_keywords",
            ["/dev/null", "aplay", "arecord", "ffmpeg"]
        )
    ]

    issues = []
    cpu = data.get("cpu") or {}
    total_cpu = float(cpu.get("total_percent") or 0)
    if total_cpu >= cpu_total_threshold:
        _add_issue(
            issues,
            "cpu_total_high",
            "high",
            f"CPU total at {total_cpu:.1f}%",
            f"Total CPU is {total_cpu:.1f}% with threshold {cpu_total_threshold:.1f}%.",
            "jarvis_self_check:cpu_total_high",
            {"cpu_percent": total_cpu, "threshold": cpu_total_threshold}
        )

    hot_cores = []
    for index, percent in enumerate(cpu.get("per_core_percent") or []):
        try:
            value = float(percent)
        except (TypeError, ValueError):
            continue
        if value >= cpu_core_threshold:
            core_number = index + 1
            hot_cores.append({"core": core_number, "percent": value})
            _add_issue(
                issues,
                "cpu_core_hot",
                "high",
                f"CPU core {core_number} at {value:.1f}%",
                f"CPU core {core_number} is at {value:.1f}% with threshold {cpu_core_threshold:.1f}%.",
                f"jarvis_self_check:cpu_core_hot:core_{core_number}",
                {"core": core_number, "cpu_percent": value, "threshold": cpu_core_threshold}
            )

    memory = data.get("memory") or {}
    ram = memory.get("ram") or {}
    ram_percent = float(ram.get("percent_used") or 0)
    if ram_percent >= memory_threshold:
        _add_issue(
            issues,
            "memory_high",
            "high",
            f"RAM at {ram_percent:.1f}%",
            f"RAM usage is {ram_percent:.1f}% with threshold {memory_threshold:.1f}%.",
            "jarvis_self_check:memory_high",
            {"memory_percent": ram_percent, "threshold": memory_threshold}
        )

    swap = memory.get("swap") or {}
    swap_percent = float(swap.get("percent_used") or 0)
    if swap_percent >= swap_threshold:
        _add_issue(
            issues,
            "swap_high",
            "medium",
            f"Swap at {swap_percent:.1f}%",
            f"Swap usage is {swap_percent:.1f}% with threshold {swap_threshold:.1f}%.",
            "jarvis_self_check:swap_high",
            {"swap_percent": swap_percent, "threshold": swap_threshold}
        )

    for disk in data.get("disks") or []:
        try:
            disk_percent = float(disk.get("percent_used") or 0)
        except (TypeError, ValueError):
            continue
        if disk_percent >= disk_threshold:
            mountpoint = str(disk.get("mountpoint") or "unknown")
            _add_issue(
                issues,
                "disk_high",
                "high",
                f"Disk {mountpoint} at {disk_percent:.1f}%",
                f"Disk {mountpoint} is {disk_percent:.1f}% full with {disk.get('free_gb')} GB free.",
                f"jarvis_self_check:disk_high:{mountpoint}",
                {"mountpoint": mountpoint, "disk_percent": disk_percent, "threshold": disk_threshold}
            )

    suspicious_processes = []
    for proc in data.get("processes") or []:
        name = str(proc.get("name") or "unknown")
        cmdline = str(proc.get("cmdline") or "")
        combined = f"{name} {cmdline}".lower()
        cpu_percent = float(proc.get("cpu_percent") or 0)
        age_minutes = float(proc.get("age_minutes") or 0)
        keyword_hit = next((kw for kw in suspicious_keywords if kw and kw in combined), None)
        if cpu_percent >= process_cpu_threshold and age_minutes >= process_min_age_minutes:
            suspicious_processes.append(proc)
            _add_issue(
                issues,
                "process_cpu_high",
                "high",
                f"Process {name} using {cpu_percent:.1f}% CPU",
                f"PID {proc.get('pid')} ({name}) is using {cpu_percent:.1f}% CPU for {age_minutes:.1f}m. Command: {cmdline[:160]}",
                f"jarvis_self_check:process_cpu_high:{name}",
                {"pid": proc.get("pid"), "name": name, "cpu_percent": cpu_percent, "age_minutes": age_minutes, "cmdline": cmdline}
            )
        elif keyword_hit and age_minutes >= suspicious_min_age_minutes and cpu_percent >= 10:
            suspicious_processes.append(proc)
            _add_issue(
                issues,
                "process_suspicious",
                "medium",
                f"Suspicious process {name}",
                f"PID {proc.get('pid')} matched '{keyword_hit}', age {age_minutes:.1f}m, CPU {cpu_percent:.1f}%. Command: {cmdline[:160]}",
                f"jarvis_self_check:process_suspicious:{name}:{keyword_hit}",
                {"pid": proc.get("pid"), "name": name, "cpu_percent": cpu_percent, "age_minutes": age_minutes, "keyword": keyword_hit}
            )

    highest = "none"
    if issues:
        highest = max((issue["severity"] for issue in issues), key=_severity_rank)

    status = "healthy"
    if highest in {"low", "medium"}:
        status = "attention"
    elif highest in {"high", "critical"}:
        status = "critical"

    summary_lines = [f"- {issue['severity'].upper()}: {issue['title']} - {issue['detail']}" for issue in issues]
    top_issue = issues[0] if issues else None

    analysis = {
        "status": status,
        "issue_count": len(issues),
        "highest_severity": highest,
        "issues": issues,
        "issue_summary": "\n".join(summary_lines) if summary_lines else "No threshold issues detected.",
        "alert_title": f"Jarvis self-check: {top_issue['title']}" if top_issue else "Jarvis self-check healthy",
        "alert_description": "\n".join(summary_lines[:8]) if summary_lines else "No threshold issues detected.",
        "dedupe_key": top_issue["dedupe_key"] if top_issue else "jarvis_self_check:healthy",
        "hot_core_count": len(hot_cores),
        "hot_cores": hot_cores,
        "suspicious_process_count": len(suspicious_processes),
        "top_process": (data.get("processes") or [{}])[0] if data.get("processes") else {},
    }
    analysis["summary_markdown"] = _build_summary_markdown(data, analysis)
    return analysis

def get_health_check(args):
    """Return compact health data and issue flags for scheduled workflows."""
    if psutil is None:
        issue = {
            "type": "monitor_unavailable",
            "severity": "critical",
            "title": "System monitor dependency missing",
            "detail": "psutil is not installed, so Jarvis cannot read local system health.",
            "dedupe_key": "jarvis_self_check:monitor_unavailable:psutil",
            "metadata": {"dependency": "psutil"}
        }
        return {
            "status": "critical",
            "issue_count": 1,
            "highest_severity": "critical",
            "issues": [issue],
            "issue_summary": f"- CRITICAL: {issue['title']} - {issue['detail']}",
            "alert_title": "Jarvis self-check: System monitor unavailable",
            "alert_description": issue["detail"],
            "dedupe_key": issue["dedupe_key"],
            "hot_core_count": 0,
            "hot_cores": [],
            "suspicious_process_count": 0,
            "top_process": {},
            "summary_markdown": (
                "- Status: critical\n"
                "- Issues: 1\n"
                "- Highest severity: critical\n\n"
                "Issues:\n"
                f"- CRITICAL: {issue['title']} - {issue['detail']}"
            ),
            "cpu": {},
            "memory": {},
            "disks": [],
            "processes": [],
            "network": {},
            "uptime": {},
        }

    raw = {
        "cpu": get_cpu_usage(),
        "memory": get_memory_usage(),
        "disks": get_disk_usage(),
        "processes": get_process_list(limit=args.get("limit", 15), sort_by=args.get("sort_by", "cpu")),
        "network": get_network_stats(),
        "uptime": get_system_uptime(),
    }
    analysis = analyze_health(raw, args)
    return {**raw, **analysis}

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
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)

        load_config()
        action = args.get('action', 'all').lower()

        if action == 'health_check':
            health_data = get_health_check(args)
            print(json.dumps({
                "ok": True,
                "speech": f"System health check: {health_data['status']} with {health_data['issue_count']} issue(s).",
                "data": health_data
            }))
            return

        if psutil is None:
            print(json.dumps({
                "ok": False,
                "error": "psutil library not installed",
                "speech": "System monitoring requires psutil library to be installed."
            }))
            sys.exit(1)
        
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
                "speech": f"Unknown monitoring action: {action}. Available: cpu_usage, memory_usage, disk_usage, process_list, network_stats, system_uptime, health_check, all"
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
