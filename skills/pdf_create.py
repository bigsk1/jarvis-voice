#!/usr/bin/env python3
"""
Tool Name: PDF Create
Description: Create PDFs from stash files (images, text, or mixed content)
Input: { "action": "create", "files": [...], "output_name": "...", "template": "..." }
Output: { "ok": bool, "speech": str, "data": { stash_ref, path } }

This tool reads from stash and writes back to stash, enabling workflows like:
  stash.save(image) → pdf.create(image + text) → printer.print(pdf)
"""

import sys
import os
import json
from datetime import datetime, timezone

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from stash_helper import (
    get_space, open_space, StashFile, resolve_file_path
)

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


class JarvisPDF(FPDF):
    """Custom PDF class with Jarvis branding."""
    
    def __init__(self, title: str = "Jarvis Document"):
        super().__init__()
        self.doc_title = title
        self.set_auto_page_break(auto=True, margin=15)
    
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, self.doc_title, align='L')
        self.cell(0, 10, datetime.now().strftime('%Y-%m-%d'), align='R')
        self.ln(15)
    
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')
    
    def add_title(self, title: str):
        """Add a large title."""
        self.set_font('Helvetica', 'B', 24)
        self.set_text_color(0, 0, 0)
        self.cell(0, 20, title, align='C')
        self.ln(25)
    
    def add_heading(self, text: str, level: int = 1):
        """Add a heading."""
        sizes = {1: 18, 2: 14, 3: 12}
        self.set_font('Helvetica', 'B', sizes.get(level, 12))
        self.set_text_color(50, 50, 50)
        self.cell(0, 10, text)
        self.ln(12)
    
    def add_text(self, text: str):
        """Add body text."""
        self.set_font('Helvetica', '', 11)
        self.set_text_color(0, 0, 0)
        # Handle multi-line text
        self.multi_cell(0, 6, text)
        self.ln(5)
    
    def add_image_centered(self, image_path: str, max_width: int = 180):
        """Add an image centered on the page."""
        if not os.path.exists(image_path):
            self.add_text(f"[Image not found: {image_path}]")
            return
        
        # Get image dimensions and scale
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                img_width, img_height = img.size
        except ImportError:
            # Without PIL, just use max width
            img_width, img_height = max_width, max_width
        
        # Scale to fit
        aspect = img_height / img_width if img_width > 0 else 1
        width = min(max_width, img_width)
        height = width * aspect
        
        # Max height check
        if height > 200:
            height = 200
            width = height / aspect
        
        # Center horizontally
        x = (210 - width) / 2  # A4 width is 210mm
        
        self.image(image_path, x=x, w=width)
        self.ln(10)


def create_simple_pdf(title: str, content_items: list[dict], output_path: str) -> str:
    """
    Create a simple PDF with mixed content.
    
    content_items: List of {"type": "text"|"image"|"heading", "content": "..."}
    """
    if not HAS_FPDF:
        raise ImportError("fpdf2 required: pip install fpdf2")
    
    pdf = JarvisPDF(title=title)
    pdf.add_page()
    pdf.add_title(title)
    
    for item in content_items:
        item_type = item.get('type', 'text')
        content = item.get('content', '')
        
        if item_type == 'heading':
            level = item.get('level', 1)
            pdf.add_heading(content, level)
        elif item_type == 'text':
            pdf.add_text(content)
        elif item_type == 'image':
            pdf.add_image_centered(content)
    
    pdf.output(output_path)
    return output_path


def action_create(args: dict) -> dict:
    """Create a PDF from stash files."""
    space_id = args.get('space_id')
    files = args.get('files', [])
    text = args.get('text', '')
    title = args.get('title', 'Jarvis Document')
    output_name = args.get('output_name', f'document_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf')
    args.get('template', 'simple')
    
    if not files and not text:
        raise ValueError("Provide 'files' (stash file_ids) or 'text' content")
    
    # Get or create space
    if space_id:
        space = get_space(space_id)
    else:
        space, _ = open_space(scope='session', labels=['pdf'])
    
    # Ensure meta is loaded
    _ = space.meta
    
    # Build content items
    content_items = []
    
    # Add text content if provided
    if text:
        # Split into paragraphs
        for para in text.split('\n\n'):
            para = para.strip()
            if para:
                # Check for markdown-style headers
                if para.startswith('# '):
                    content_items.append({'type': 'heading', 'level': 1, 'content': para[2:]})
                elif para.startswith('## '):
                    content_items.append({'type': 'heading', 'level': 2, 'content': para[3:]})
                elif para.startswith('### '):
                    content_items.append({'type': 'heading', 'level': 3, 'content': para[4:]})
                else:
                    content_items.append({'type': 'text', 'content': para})
    
    # Add files from stash
    for file_ref in files:
        # Resolve file path (handles file_id or name)
        try:
            if '://' in str(file_ref):
                # stash:// reference
                file_path = resolve_file_path(stash_ref=file_ref)
            else:
                # file_id or name in current space
                file_path = resolve_file_path(space_id=space.space_id, file_id=file_ref)
            
            # Determine type from extension
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                content_items.append({'type': 'image', 'content': file_path})
            elif ext in ['.txt', '.md', '.json']:
                with open(file_path, 'r') as f:
                    file_text = f.read()
                content_items.append({'type': 'text', 'content': file_text})
            else:
                content_items.append({'type': 'text', 'content': f'[File: {file_ref}]'})
                
        except Exception as e:
            content_items.append({'type': 'text', 'content': f'[Error loading {file_ref}: {e}]'})
    
    if not content_items:
        raise ValueError("No content to include in PDF")
    
    # Create PDF in stash space
    output_path = str(space.space_path / output_name)
    create_simple_pdf(title, content_items, output_path)
    
    # Register in stash metadata
    StashFile(space)
    
    # Get file size
    file_size = os.path.getsize(output_path)
    
    # Compute hash
    import hashlib
    with open(output_path, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    
    # Generate file_id
    from stash_helper import generate_file_id
    file_id = generate_file_id(output_name)
    
    # Add to space metadata
    file_meta = {
        'file_id': file_id,
        'name': output_name,
        'stored_name': output_name,
        'mime_type': 'application/pdf',
        'size_bytes': file_size,
        'hash_sha256': file_hash,
        'tags': ['pdf', 'generated'],
        'tool_origin': 'pdf_create',
        'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    }
    space._meta['files'].append(file_meta)
    space._save_meta()
    
    ref = f"stash://{space.space_id}/{file_id}"
    
    # Save to memory for cross-session discovery
    try:
        from memory_db import MemoryDB
        db = MemoryDB()
        
        memory_key = f"stash_pdf_{space.space_id}"
        memory_value = f"Created PDF: {title}. FILE: {output_name}. STASH: {ref}. Size: {file_size // 1024}KB"
        
        db.remember(
            key=memory_key,
            value=memory_value,
            category="stash_artifact",
            importance=6
        )
    except Exception:
        pass  # Don't fail if memory save fails
    
    return {
        "ok": True,
        "speech": f"Created {output_name} ({file_size // 1024}KB)",
        "data": {
            "space_id": space.space_id,
            "file_id": file_id,
            "name": output_name,
            "ref": ref,
            "path": output_path,
            "size_bytes": file_size
        }
    }


def action_from_text(args: dict) -> dict:
    """Create a PDF from plain text (convenience action)."""
    text = args.get('text')
    title = args.get('title', 'Document')
    
    if not text:
        raise ValueError("'text' is required")
    
    # Build create args, only include output_name if provided
    create_args = {
        'text': text,
        'title': title,
    }
    if args.get('space_id'):
        create_args['space_id'] = args['space_id']
    if args.get('output_name'):
        create_args['output_name'] = args['output_name']
    
    return action_create(create_args)


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Check fpdf2
        if not HAS_FPDF:
            raise ImportError("fpdf2 library required. Install with: pip install fpdf2")
        
        # Get action
        action = args.get('action', 'create').lower()
        
        handlers = {
            'create': action_create,
            'from_text': action_from_text,
        }
        
        if action not in handlers:
            raise ValueError(f"Unknown action: {action}. Use: {', '.join(handlers.keys())}")
        
        result = handlers[action](args)
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"PDF error: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

