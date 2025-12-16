#!/usr/bin/env python3
"""
Tool Name: Printer
Description: Print text, files, or canvas pages to the configured printer
Input: { "action": "print|status|cancel|print_canvas", "text": "...", "title": "..." }
Output: { "ok": bool, "speech": str, "data": { "job_id": str } }
"""

import sys
import os
import json
import subprocess
import tempfile
import re
import glob
from datetime import datetime
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from stash_helper import safe_resolve_file


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


def print_text(printer: str, text: str, title: str = None, compact: bool = False, color: bool = True) -> dict:
    """Print text content to printer.
    
    Args:
        printer: Printer name
        text: Content to print
        title: Optional header title
        compact: If True, use smaller text (more content per page)
        color: If True, print in color (default), False for grayscale
    """
    try:
        # Add header with timestamp if no title
        header = title or "Jarvis Print"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Adjust line width based on compact mode
        line_width = 70 if compact else 50
        
        # Format content with margins (add blank lines at top for margin)
        formatted = f"""

{'=' * line_width}
{header}
{timestamp}
{'=' * line_width}

{text}

{'=' * line_width}
Printed by Jarvis Voice Assistant
"""
        
        # Create temp file (some printers work better with files)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(formatted)
            temp_path = f.name
        
        try:
            # Build print command with options
            cmd = ['lp', '-d', printer]
            
            # Add compact mode options (smaller text)
            if compact:
                cmd.extend(['-o', 'cpi=14', '-o', 'lpi=8'])
            
            # Color mode
            if not color:
                cmd.extend(['-o', 'ColorModel=Gray'])
            
            cmd.append(temp_path)
            
            # Print the file
            result = subprocess.run(
                cmd,
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


def print_file(printer: str, file_path: str, color: bool = True, quality: str = "Normal") -> dict:
    """Print a file (text, PDF, or image) to printer.
    
    Args:
        printer: Printer name
        file_path: Path to file
        color: Color or grayscale
        quality: Draft, Normal, or High
    """
    try:
        if not os.path.exists(file_path):
            return {"ok": False, "error": f"File not found: {file_path}"}
        
        # Build command with options
        cmd = ['lp', '-d', printer]
        
        # Color mode
        if not color:
            cmd.extend(['-o', 'ColorModel=Gray'])
        
        # Quality
        if quality in ['Draft', 'Normal', 'High']:
            cmd.extend(['-o', f'cupsPrintQuality={quality}'])
        
        # For images, fit to page
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
            cmd.extend(['-o', 'fit-to-page'])
        
        cmd.append(file_path)
        
        result = subprocess.run(
            cmd,
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


def markdown_to_text(md: str) -> str:
    """Convert markdown to nicely formatted plain text for printing."""
    lines = []
    
    for line in md.split('\n'):
        # Headers - add underlines
        if line.startswith('# '):
            text = line[2:]
            lines.append('')
            lines.append('=' * 60)
            lines.append(text.upper())
            lines.append('=' * 60)
        elif line.startswith('## '):
            text = line[3:]
            lines.append('')
            lines.append('-' * 50)
            lines.append(text)
            lines.append('-' * 50)
        elif line.startswith('### '):
            text = line[4:]
            lines.append('')
            lines.append(f">>> {text}")
        # Code blocks - indent
        elif line.startswith('```'):
            if line == '```':
                lines.append('    ' + '-' * 40)
            else:
                lang = line[3:]
                lines.append(f'    [{lang}]')
                lines.append('    ' + '-' * 40)
        # Bold/italic - clean up
        elif '**' in line or '*' in line:
            # Remove markdown formatting
            clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)  # bold
            clean = re.sub(r'\*([^*]+)\*', r'\1', clean)  # italic
            lines.append(clean)
        # Lists - keep as-is but clean bullets
        elif line.strip().startswith('- '):
            lines.append('  • ' + line.strip()[2:])
        else:
            lines.append(line)
    
    return '\n'.join(lines)


def print_canvas(printer: str, canvas_id: str = None, compact: bool = True, color: bool = True) -> dict:
    """Print a canvas page by ID or most recent.
    
    Args:
        printer: Printer name
        canvas_id: Canvas ID or search term (None for most recent)
        compact: Use smaller text (default True for canvas)
        color: Color or grayscale
    """
    try:
        # Find canvas directory
        project_root = Path(__file__).parent.parent
        canvas_dir = project_root / "data" / "canvas"
        
        if not canvas_dir.exists():
            return {"ok": False, "error": "Canvas directory not found"}
        
        # Find the canvas file
        if canvas_id:
            # Look for specific canvas
            matches = list(canvas_dir.glob(f"*{canvas_id}*.json"))
            if not matches:
                return {"ok": False, "error": f"Canvas '{canvas_id}' not found"}
            canvas_file = matches[0]
        else:
            # Get most recent canvas
            canvas_files = sorted(canvas_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
            if not canvas_files:
                return {"ok": False, "error": "No canvas pages found"}
            canvas_file = canvas_files[0]
        
        # Load canvas
        with open(canvas_file, 'r') as f:
            canvas = json.load(f)
        
        title = canvas.get('title', 'Canvas Page')
        content = canvas.get('content', '')
        content_type = canvas.get('content_type', 'text')
        tags = canvas.get('tags', [])
        created = canvas.get('created', '')[:10]  # Just date
        
        # Convert markdown to printable text
        if content_type == 'markdown':
            formatted_content = markdown_to_text(content)
        else:
            formatted_content = content
        
        # Build printable document
        tag_str = ', '.join(tags) if tags else 'none'
        header = f"""


{'=' * 60}
JARVIS CANVAS: {title}
{'=' * 60}
Date: {created}
Tags: {tag_str}
{'=' * 60}

"""
        
        footer = f"""

{'=' * 60}
Printed from Jarvis Canvas
{datetime.now().strftime('%Y-%m-%d %H:%M')}
{'=' * 60}
"""
        
        full_document = header + formatted_content + footer
        
        # Print it (canvas defaults to compact mode)
        return print_text(printer, full_document, title=None, compact=compact, color=color)
        
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
        canvas_id = args.get('canvas_id', '')
        
        # Fix LLM escape sequences - convert literal \n to actual newlines
        if text:
            text = text.replace('\\n', '\n')
        
        # Print options
        compact = args.get('compact', False)  # Smaller text
        color = args.get('color', True)  # Color printing (default)
        quality = args.get('quality', 'Normal')  # Draft, Normal, High
        
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
            
        elif action == 'print_canvas':
            # Canvas defaults to compact mode
            result = print_canvas(printer, canvas_id if canvas_id else None, 
                                  compact=True, color=color)
            
            if result.get('ok'):
                print(json.dumps({
                    "ok": True,
                    "speech": f"Canvas page sent to printer in compact mode",
                    "data": result
                }))
            else:
                print(json.dumps({
                    "ok": False,
                    "speech": "Failed to print canvas",
                    "error": result.get('error')
                }))
                sys.exit(1)
            
        elif action == 'print':
            # Resolve stash:// references to actual file paths
            resolved_path = None
            if file_path:
                if file_path.startswith('stash://'):
                    # Resolve stash reference with graceful fallback
                    resolve_result = safe_resolve_file(stash_ref=file_path)
                    if resolve_result['found']:
                        resolved_path = resolve_result['path']
                    else:
                        raise ValueError(f"Could not resolve stash reference: {resolve_result['error']}")
                else:
                    resolved_path = file_path
            
            if resolved_path:
                result = print_file(printer, resolved_path, color=color, quality=quality)
            elif text:
                result = print_text(printer, text, title, compact=compact, color=color)
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

