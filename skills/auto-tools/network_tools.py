#!/usr/bin/env python3
"""
Network diagnostics tool for ping, DNS lookup, port scanning, HTTP/HTTPS checks, and connectivity checks.
"""
import sys
import os
import json
import socket
import time
import subprocess
import platform
import re
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

def ping_host(host, count=4, timeout=2):
    """Ping a host using system ping command with detailed statistics."""
    is_windows = platform.system().lower() == 'windows'
    param = '-n' if is_windows else '-c'
    timeout_param = '-w' if is_windows else '-W'
    
    command = ['ping', param, str(count), timeout_param, 
               str(timeout * 1000 if is_windows else timeout), host]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout * count + 5)
        success = result.returncode == 0
        output = result.stdout if success else result.stderr
        
        stats = {
            'reachable': success,
            'packets_sent': count,
            'packets_received': 0,
            'packet_loss_percent': 100.0,
            'min_ms': None,
            'avg_ms': None,
            'max_ms': None,
            'raw_output': output
        }
        
        if success:
            # Parse packet loss (Linux: "4 packets transmitted, 4 received")
            # Windows: "Packets: Sent = 4, Received = 4, Lost = 0"
            loss_match = re.search(r'(\d+) received|Received = (\d+)', output)
            if loss_match:
                received = int(loss_match.group(1) or loss_match.group(2))
                stats['packets_received'] = received
                stats['packet_loss_percent'] = round(((count - received) / count) * 100, 1)
            
            # Parse round-trip times (Linux/Mac)
            # "rtt min/avg/max/mdev = 12.345/23.456/34.567/5.678 ms"
            rtt_match = re.search(r'rtt min/avg/max/(?:mdev|stddev) = ([\d.]+)/([\d.]+)/([\d.]+)', output)
            if rtt_match:
                stats['min_ms'] = float(rtt_match.group(1))
                stats['avg_ms'] = float(rtt_match.group(2))
                stats['max_ms'] = float(rtt_match.group(3))
            
            # Parse Windows format: "Minimum = 12ms, Maximum = 34ms, Average = 23ms"
            if not rtt_match:
                min_match = re.search(r'Minimum = (\d+)ms', output)
                avg_match = re.search(r'Average = (\d+)ms', output)
                max_match = re.search(r'Maximum = (\d+)ms', output)
                if min_match and avg_match and max_match:
                    stats['min_ms'] = float(min_match.group(1))
                    stats['avg_ms'] = float(avg_match.group(1))
                    stats['max_ms'] = float(max_match.group(1))
        
        return stats
    except subprocess.TimeoutExpired:
        return {'reachable': False, 'error': 'Ping timed out'}
    except Exception as e:
        return {'reachable': False, 'error': str(e)}

def dns_lookup(hostname):
    """Resolve hostname to IP address(es)."""
    try:
        ip_list = socket.gethostbyname_ex(hostname)
        return {
            'hostname': ip_list[0],
            'aliases': ip_list[1],
            'ip_addresses': ip_list[2],
            'primary_ip': ip_list[2][0] if ip_list[2] else None
        }
    except socket.gaierror as e:
        return {'error': f'DNS lookup failed: {e}'}
    except Exception as e:
        return {'error': str(e)}

def check_port(host, port, timeout=3):
    """Check if a port is open on a host."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    
    start_time = time.time()
    try:
        result = sock.connect_ex((host, port))
        latency = (time.time() - start_time) * 1000
        sock.close()
        
        return {
            'open': result == 0,
            'port': port,
            'host': host,
            'latency_ms': round(latency, 2)
        }
    except socket.gaierror:
        return {'open': False, 'port': port, 'host': host, 'error': 'Hostname could not be resolved'}
    except socket.timeout:
        return {'open': False, 'port': port, 'host': host, 'error': 'Connection timed out'}
    except Exception as e:
        return {'open': False, 'port': port, 'host': host, 'error': str(e)}

def traceroute(host, max_hops=30, timeout=2):
    """Simple traceroute implementation."""
    try:
        if platform.system().lower() == 'windows':
            cmd = ['tracert', '-h', str(max_hops), '-w', str(timeout * 1000), host]
        else:
            cmd = ['traceroute', '-m', str(max_hops), '-w', str(timeout), host]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=max_hops * timeout + 10)
        return {
            'success': result.returncode == 0,
            'output': result.stdout if result.returncode == 0 else result.stderr,
            'host': host
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Traceroute timed out'}
    except FileNotFoundError:
        return {'success': False, 'error': 'Traceroute command not available on this system'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def check_http(url: str, method: str = 'GET', timeout: int = 10, follow_redirects: bool = True) -> dict[str, Any]:
    """Check HTTP/HTTPS endpoint status and response time."""
    if not REQUESTS_AVAILABLE:
        return {
            'error': 'requests library not available. Install with: pip install requests',
            'available': False
        }
    
    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    start_time = time.time()
    
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            timeout=timeout,
            allow_redirects=follow_redirects,
            verify=True  # Verify SSL certificates
        )
        
        response_time_ms = round((time.time() - start_time) * 1000, 2)
        
        return {
            'url': url,
            'status_code': response.status_code,
            'status_text': response.reason,
            'success': 200 <= response.status_code < 400,
            'response_time_ms': response_time_ms,
            'content_length': len(response.content),
            'headers': dict(response.headers),
            'final_url': response.url if follow_redirects else url,
            'redirected': response.url != url if follow_redirects else False
        }
    
    except requests.exceptions.SSLError as e:
        return {
            'url': url,
            'success': False,
            'error': f'SSL certificate error: {str(e)}',
            'error_type': 'ssl_error'
        }
    except requests.exceptions.Timeout:
        return {
            'url': url,
            'success': False,
            'error': f'Request timed out after {timeout} seconds',
            'error_type': 'timeout'
        }
    except requests.exceptions.ConnectionError as e:
        return {
            'url': url,
            'success': False,
            'error': f'Connection failed: {str(e)}',
            'error_type': 'connection_error'
        }
    except Exception as e:
        return {
            'url': url,
            'success': False,
            'error': str(e),
            'error_type': 'unknown_error'
        }

def check_connectivity(test_hosts=None):
    """Check general internet connectivity."""
    if test_hosts is None:
        test_hosts = ['8.8.8.8', '1.1.1.1']
    
    results = []
    for host in test_hosts:
        result = check_port(host, 53, timeout=2)
        results.append({'host': host, 'reachable': result.get('open', False)})
    
    any_reachable = any(r['reachable'] for r in results)
    
    return {
        'connected': any_reachable,
        'tests': results
    }

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        operation = args.get('operation', 'ping')
        host = args.get('host')
        port = args.get('port')
        url = args.get('url')
        count = args.get('count', 4)
        timeout = args.get('timeout', 3)
        max_hops = args.get('max_hops', 30)
        method = args.get('method', 'GET')
        follow_redirects = args.get('follow_redirects', True)
        
        result_data = {}
        speech = ""
        
        if operation == 'ping':
            if not host:
                raise ValueError("Host is required for ping operation")
            result_data = ping_host(host, count, timeout)
            if result_data.get('reachable'):
                avg = result_data.get('avg_ms')
                loss = result_data.get('packet_loss_percent', 0)
                if avg:
                    speech = f"Host {host} is reachable. Average latency: {avg:.1f}ms, packet loss: {loss}%"
                else:
                    speech = f"Host {host} is reachable"
            else:
                speech = f"Host {host} is not reachable"
        
        elif operation == 'dns':
            if not host:
                raise ValueError("Host is required for DNS lookup")
            result_data = dns_lookup(host)
            if 'error' in result_data:
                speech = f"DNS lookup failed for {host}"
            else:
                ip = result_data.get('primary_ip')
                speech = f"DNS lookup for {host}: {ip}"
        
        elif operation == 'port':
            if not host or not port:
                raise ValueError("Host and port are required for port check")
            result_data = check_port(host, int(port), timeout)
            if result_data.get('open'):
                speech = f"Port {port} is open on {host}"
            else:
                speech = f"Port {port} is closed on {host}"
        
        elif operation == 'traceroute':
            if not host:
                raise ValueError("Host is required for traceroute")
            result_data = traceroute(host, max_hops, timeout)
            if result_data.get('success'):
                speech = f"Traceroute to {host} completed"
            else:
                speech = f"Traceroute to {host} failed"
        
        elif operation == 'connectivity':
            test_hosts = args.get('test_hosts')
            result_data = check_connectivity(test_hosts)
            if result_data.get('connected'):
                speech = "Internet connectivity is working"
            else:
                speech = "No internet connectivity detected"
        
        elif operation == 'http':
            target = url or host
            if not target:
                raise ValueError("URL or host is required for HTTP check")
            result_data = check_http(target, method, timeout, follow_redirects)
            if result_data.get('success'):
                status = result_data.get('status_code')
                response_time = result_data.get('response_time_ms')
                speech = f"HTTP check successful. Status: {status}, response time: {response_time}ms"
            else:
                error = result_data.get('error', 'Unknown error')
                speech = f"HTTP check failed: {error}"
        
        else:
            raise ValueError(f"Unknown operation: {operation}")
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": result_data
        }))
        
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "speech": f"Network diagnostic error: {e}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()