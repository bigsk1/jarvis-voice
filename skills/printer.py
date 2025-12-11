#!/usr/bin/env python3
"""
Tool Name: Printer
Description: Print text or files to the configured printer
Input: { "action": "print|status|cancel", "text": "...", "title": "..." }
Output: { "ok": bool, "speech": str, "data": { "job_id": str } }
"""

import sys
import os
import json
import subprocess
import tempfile
from datetime import datetime

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value


def get_printer_name() -> str:
    """Get configured printer name from config."""
    return get_config_value('PRINTER_NAME', 'Epson_ET4760')


def get_printer_status(printer: str) -> dict:
    """Get printer status and queue info."""
    try:
        # Get printer status
        result = subprocess.run(
            ['lpstat', '-p', printer],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        status = "unknown"
        if "idle" in result.stdout.lower():
            status = "idle"
        elif "printing" in result.stdout.lower():
            status = "printing"
        elif "disabled" in result.stdout.lower():
            status = "disabled"
        
        # Get queue
        queue_result = subprocess.run(
            ['lpstat', '-o', printer],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        jobs = []
        if queue_result.stdout.strip():
            for line in queue_result.stdout.strip().split('\n'):
                if line:
                    jobs.append(line.split()[0])  # Job ID
        
        return {
            "status": status,
            "queue_length": len(jobs),
            "jobs": jobs[:5],  # First 5 jobs
            "raw": result.stdout.strip()
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


def print_text(printer: str, text: str, title: str = None) -> dict:
    """Print text content to printer."""
    try:
        # Add header with timestamp if no title
        header = title or "Jarvis Print"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Format content with margins (add blank lines at top for margin)
        formatted = f"""


{'=' * 50}
{header}
{timestamp}
{'=' * 50}

{text}

{'=' * 50}
Printed by Jarvis Voice Assistant
"""
        
        # Create temp file (some printers work better with files)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(formatted)
            temp_path = f.name
        
        try:
            # Print the file
            result = subprocess.run(
                ['lp', '-d', printer, temp_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                # Parse job ID from output like "request id is Epson_ET4760-5 (1 file(s))"
                job_id = None
                if "request id is" in result.stdout:
                    parts = result.stdout.split("request id is")[1].split()[0]
                    job_id = parts
                
                return {
                    "ok": True,
                    "job_id": job_id,
                    "message": "Print job sent successfully"
                }
            else:
                return {
                    "ok": False,
                    "error": result.stderr or "Print failed"
                }
        finally:
            # Clean up temp file
            os.unlink(temp_path)
            
    except Exception as e:
        return {"ok": False, "error": str(e)}


def print_file(printer: str, file_path: str) -> dict:
    """Print a file to printer."""
    try:
        if not os.path.exists(file_path):
            return {"ok": False, "error": f"File not found: {file_path}"}
        
        result = subprocess.run(
            ['lp', '-d', printer, file_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            job_id = None
            if "request id is" in result.stdout:
                parts = result.stdout.split("request id is")[1].split()[0]
                job_id = parts
            
            return {
                "ok": True,
                "job_id": job_id,
                "message": f"File sent to printer"
            }
        else:
            return {"ok": False, "error": result.stderr or "Print failed"}
            
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cancel_job(printer: str, job_id: str = None) -> dict:
    """Cancel print job(s)."""
    try:
        if job_id:
            # Cancel specific job
            result = subprocess.run(
                ['cancel', job_id],
                capture_output=True,
                text=True,
                timeout=10
            )
        else:
            # Cancel all jobs for this printer
            result = subprocess.run(
                ['cancel', '-a', printer],
                capture_output=True,
                text=True,
                timeout=10
            )
        
        return {
            "ok": result.returncode == 0,
            "message": "Print job(s) cancelled" if result.returncode == 0 else result.stderr
        }
        
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Get parameters
        action = args.get('action', 'print').lower()
        text = args.get('text', '')
        title = args.get('title', '')
        file_path = args.get('file_path', '')
        job_id = args.get('job_id', '')
        
        # Get printer
        printer = get_printer_name()
        
        # Handle actions
        if action == 'status':
            status = get_printer_status(printer)
            
            if status.get('status') == 'error':
                print(json.dumps({
                    "ok": False,
                    "speech": "Couldn't get printer status",
                    "error": status.get('error')
                }))
                sys.exit(1)
            
            queue_msg = f"with {status['queue_length']} jobs in queue" if status['queue_length'] > 0 else "with no pending jobs"
            print(json.dumps({
                "ok": True,
                "speech": f"Printer is {status['status']} {queue_msg}",
                "data": status
            }))
            
        elif action == 'print':
            if file_path:
                result = print_file(printer, file_path)
            elif text:
                result = print_text(printer, text, title)
            else:
                raise ValueError("Either 'text' or 'file_path' is required for print action")
            
            if result.get('ok'):
                print(json.dumps({
                    "ok": True,
                    "speech": f"Sent to printer. Job ID: {result.get('job_id', 'unknown')}",
                    "data": result
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Failed to print",
                    "error": result.get('error')
                }))
                sys.exit(1)
                
        elif action == 'cancel':
            result = cancel_job(printer, job_id if job_id else None)
            
            if result.get('ok'):
                print(json.dumps({
                    "ok": True,
                    "speech": "Print job cancelled",
                    "data": result
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Couldn't cancel print job",
                    "error": result.get('error')
                }))
                sys.exit(1)
                
        else:
            raise ValueError(f"Unknown action: {action}. Use: print, status, cancel")
            
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Printer error: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

