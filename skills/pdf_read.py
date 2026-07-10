#!/usr/bin/env python3
"""
Tool Name: PDF Read
Description: Read and manipulate PDF files: extract text/images, merge, split, convert to images
Input: { "action": "extract_text|extract_images|merge|split|to_images|info", ... }
Output: { "ok": bool, "speech": str, "data": {...} }

Reads from stash refs or local paths, writes back to stash.
Complements pdf_create for full PDF workflow support.
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from paths import resolve_local_file_tool_path, validate_tool_output_filename
from stash_helper import (
    get_space, open_space, StashFile, resolve_file_path, safe_resolve_file
)

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


def format_size(bytes_size: int) -> str:
    """Format bytes to human-readable size."""
    if bytes_size < 1024:
        return f"{bytes_size}B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f}KB"
    else:
        return f"{bytes_size / (1024 * 1024):.1f}MB"


def resolve_pdf_path(args: dict) -> str:
    """Resolve PDF path from stash_ref, space_id+file_id, or file_path."""
    stash_ref = args.get('stash_ref')
    space_id = args.get('space_id')
    file_id = args.get('file_id')
    file_path = args.get('file_path')
    
    if file_path:
        resolved = resolve_local_file_tool_path(file_path, include_pictures=False)
        if resolved.exists():
            return str(resolved)
    
    if stash_ref:
        result = safe_resolve_file(stash_ref=stash_ref)
        if result['found']:
            return result['path']
        raise ValueError(f"Stash file not found: {stash_ref}")
    
    if space_id and file_id:
        return resolve_file_path(space_id=space_id, file_id=file_id)
    
    raise ValueError("Provide stash_ref, space_id+file_id, or file_path")


def action_info(args: dict) -> dict:
    """Get PDF metadata and info."""
    if not HAS_PYMUPDF:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_path = resolve_pdf_path(args)
    
    doc = fitz.open(pdf_path)
    
    info = {
        "page_count": doc.page_count,
        "metadata": doc.metadata,
        "is_encrypted": doc.is_encrypted,
        "is_pdf": doc.is_pdf,
        "file_size": os.path.getsize(pdf_path),
        "file_size_human": format_size(os.path.getsize(pdf_path)),
    }
    
    # Get page dimensions from first page
    if doc.page_count > 0:
        page = doc[0]
        info["page_width"] = page.rect.width
        info["page_height"] = page.rect.height
    
    doc.close()
    
    return {
        "ok": True,
        "speech": f"PDF has {info['page_count']} pages, {info['file_size_human']}",
        "data": info
    }


def action_extract_text(args: dict) -> dict:
    """Extract text from PDF pages."""
    if not HAS_PYMUPDF:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_path = resolve_pdf_path(args)
    pages = args.get('pages')  # None = all, or list like [0, 1, 2] or "1-5"
    save_to_stash = args.get('save_to_stash', False)
    output_name = args.get('output_name')
    
    doc = fitz.open(pdf_path)
    
    # Parse page range
    if pages is None:
        page_nums = range(doc.page_count)
    elif isinstance(pages, str) and '-' in pages:
        start, end = pages.split('-')
        page_nums = range(int(start) - 1, int(end))  # 1-indexed input
    elif isinstance(pages, list):
        page_nums = [p - 1 if p > 0 else p for p in pages]  # Convert to 0-indexed
    else:
        page_nums = range(doc.page_count)
    
    # Extract text
    text_parts = []
    for page_num in page_nums:
        if 0 <= page_num < doc.page_count:
            page = doc[page_num]
            text = page.get_text()
            text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
    
    full_text = "\n\n".join(text_parts)
    doc.close()
    
    result = {
        "text": full_text,
        "page_count": len(text_parts),
        "char_count": len(full_text)
    }
    
    # Optionally save to stash
    if save_to_stash:
        space_id = args.get('output_space_id')
        if space_id:
            space = get_space(space_id)
        else:
            space, _ = open_space(labels=['pdf_extract'])
        
        if not output_name:
            base_name = Path(pdf_path).stem
            output_name = f"{base_name}_text.txt"
        
        stash_file = StashFile(space)
        save_result = stash_file.save_text(
            content=full_text,
            name=output_name,
            on_conflict='overwrite',
            tags=['pdf_extract', 'text'],
            tool_origin='pdf_read'
        )
        result['stash_ref'] = save_result['ref']
        result['space_id'] = space.space_id
    
    return {
        "ok": True,
        "speech": f"Extracted {len(full_text)} characters from {len(text_parts)} pages",
        "data": result
    }


def action_extract_images(args: dict) -> dict:
    """Extract images from PDF."""
    if not HAS_PYMUPDF:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_path = resolve_pdf_path(args)
    pages = args.get('pages')
    min_size = args.get('min_size', 100)  # Minimum dimension to extract
    
    doc = fitz.open(pdf_path)
    
    # Parse page range
    if pages is None:
        page_nums = range(doc.page_count)
    elif isinstance(pages, str) and '-' in pages:
        start, end = pages.split('-')
        page_nums = range(int(start) - 1, int(end))  # 1-indexed input
    elif isinstance(pages, list):
        page_nums = [p - 1 if p > 0 else p for p in pages]
    else:
        page_nums = range(doc.page_count)
    
    # Get or create output space
    space_id = args.get('output_space_id')
    if space_id:
        space = get_space(space_id)
    else:
        space, _ = open_space(labels=['pdf_images'])
    
    extracted = []
    img_count = 0
    
    for page_num in page_nums:
        if 0 <= page_num < doc.page_count:
            page = doc[page_num]
            image_list = page.get_images()
            
            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue
                    
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    
                    # Skip small images (likely icons/bullets)
                    if width < min_size or height < min_size:
                        continue
                    
                    img_count += 1
                    img_name = f"page{page_num + 1}_img{img_index + 1}.{image_ext}"
                    
                    stash_file = StashFile(space)
                    save_result = stash_file.save_binary(
                        data=image_bytes,
                        name=img_name,
                        mime_type=f"image/{image_ext}",
                        on_conflict='version',
                        tags=['pdf_extract', 'image', f'page_{page_num + 1}'],
                        tool_origin='pdf_read'
                    )
                    
                    extracted.append({
                        "name": img_name,
                        "page": page_num + 1,
                        "width": width,
                        "height": height,
                        "stash_ref": save_result['ref']
                    })
                except Exception:
                    continue
    
    doc.close()
    
    return {
        "ok": True,
        "speech": f"Extracted {len(extracted)} images to stash",
        "data": {
            "images": extracted,
            "count": len(extracted),
            "space_id": space.space_id
        }
    }


def action_merge(args: dict) -> dict:
    """Merge multiple PDFs into one."""
    if not HAS_PYMUPDF:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_refs = args.get('pdfs', [])  # List of stash_refs or file_paths
    output_name = validate_tool_output_filename(
        args.get('output_name', f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"),
        label="PDF output name",
    )
    
    if len(pdf_refs) < 2:
        raise ValueError("Need at least 2 PDFs to merge")
    
    resolved_paths = []
    for ref in pdf_refs:
        if isinstance(ref, str):
            if ref.startswith('stash://'):
                path = resolve_file_path(stash_ref=ref)
            else:
                path = resolve_pdf_path({'file_path': ref})
        elif isinstance(ref, dict):
            path = resolve_pdf_path(ref)
        else:
            continue

        if os.path.exists(path):
            resolved_paths.append(path)

    # Create output PDF only after every local source has passed policy checks.
    merged = fitz.open()
    for path in resolved_paths:
        doc = fitz.open(path)
        merged.insert_pdf(doc)
        doc.close()
    
    # Save to stash
    space_id = args.get('output_space_id')
    if space_id:
        space = get_space(space_id)
    else:
        space, _ = open_space(labels=['pdf_merge'])
    
    # Write to bytes
    pdf_bytes = merged.tobytes()
    merged.close()
    
    stash_file = StashFile(space)
    save_result = stash_file.save_binary(
        data=pdf_bytes,
        name=output_name,
        mime_type='application/pdf',
        on_conflict='overwrite',
        tags=['pdf_merge', 'merged'],
        tool_origin='pdf_read'
    )
    
    return {
        "ok": True,
        "speech": f"Merged {len(pdf_refs)} PDFs into {output_name}",
        "data": {
            "stash_ref": save_result['ref'],
            "space_id": space.space_id,
            "file_name": output_name,
            "size_bytes": len(pdf_bytes)
        }
    }


def action_split(args: dict) -> dict:
    """Split PDF into separate files."""
    if not HAS_PYMUPDF:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_path = resolve_pdf_path(args)
    split_at = args.get('split_at')  # Page number(s) to split at, or 'each' for every page
    
    doc = fitz.open(pdf_path)
    base_name = Path(pdf_path).stem
    
    # Get or create output space
    space_id = args.get('output_space_id')
    if space_id:
        space = get_space(space_id)
    else:
        space, _ = open_space(labels=['pdf_split'])
    
    outputs = []
    
    if split_at == 'each':
        # Split into individual pages
        for i in range(doc.page_count):
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=i, to_page=i)
            
            output_name = f"{base_name}_page{i + 1}.pdf"
            pdf_bytes = new_doc.tobytes()
            new_doc.close()
            
            stash_file = StashFile(space)
            save_result = stash_file.save_binary(
                data=pdf_bytes,
                name=output_name,
                mime_type='application/pdf',
                on_conflict='overwrite',
                tags=['pdf_split', f'page_{i + 1}'],
                tool_origin='pdf_read'
            )
            outputs.append({
                "name": output_name,
                "pages": [i + 1],
                "stash_ref": save_result['ref']
            })
    else:
        # Split at specific page(s)
        if isinstance(split_at, int):
            split_points = [split_at]
        elif isinstance(split_at, list):
            split_points = sorted(split_at)
        else:
            split_points = [doc.page_count // 2]  # Default: split in half
        
        # Add start and end
        ranges = []
        prev = 0
        for point in split_points:
            if 0 < point <= doc.page_count:
                ranges.append((prev, point - 1))
                prev = point
        ranges.append((prev, doc.page_count - 1))
        
        for idx, (start, end) in enumerate(ranges):
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start, to_page=end)
            
            output_name = f"{base_name}_part{idx + 1}.pdf"
            pdf_bytes = new_doc.tobytes()
            new_doc.close()
            
            stash_file = StashFile(space)
            save_result = stash_file.save_binary(
                data=pdf_bytes,
                name=output_name,
                mime_type='application/pdf',
                on_conflict='overwrite',
                tags=['pdf_split', f'part_{idx + 1}'],
                tool_origin='pdf_read'
            )
            outputs.append({
                "name": output_name,
                "pages": list(range(start + 1, end + 2)),
                "stash_ref": save_result['ref']
            })
    
    doc.close()
    
    return {
        "ok": True,
        "speech": f"Split PDF into {len(outputs)} parts",
        "data": {
            "outputs": outputs,
            "count": len(outputs),
            "space_id": space.space_id
        }
    }


def action_to_images(args: dict) -> dict:
    """Convert PDF pages to images."""
    if not HAS_PYMUPDF:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_path = resolve_pdf_path(args)
    pages = args.get('pages')
    dpi = args.get('dpi', 150)
    image_format = args.get('format', 'png')
    
    doc = fitz.open(pdf_path)
    base_name = Path(pdf_path).stem
    
    # Parse page range
    if pages is None:
        page_nums = range(doc.page_count)
    elif isinstance(pages, str) and '-' in pages:
        start, end = pages.split('-')
        page_nums = range(int(start) - 1, int(end))  # 1-indexed input
    elif isinstance(pages, list):
        page_nums = [p - 1 if p > 0 else p for p in pages]
    else:
        page_nums = range(doc.page_count)
    
    # Get or create output space
    space_id = args.get('output_space_id')
    if space_id:
        space = get_space(space_id)
    else:
        space, _ = open_space(labels=['pdf_images'])
    
    outputs = []
    zoom = dpi / 72  # 72 is default PDF DPI
    matrix = fitz.Matrix(zoom, zoom)
    
    for page_num in page_nums:
        if 0 <= page_num < doc.page_count:
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)
            
            img_name = f"{base_name}_page{page_num + 1}.{image_format}"
            
            if image_format == 'png':
                img_bytes = pix.tobytes("png")
                mime_type = 'image/png'
            else:
                img_bytes = pix.tobytes("jpeg")
                mime_type = 'image/jpeg'
            
            stash_file = StashFile(space)
            save_result = stash_file.save_binary(
                data=img_bytes,
                name=img_name,
                mime_type=mime_type,
                on_conflict='overwrite',
                tags=['pdf_to_image', f'page_{page_num + 1}'],
                tool_origin='pdf_read'
            )
            
            outputs.append({
                "name": img_name,
                "page": page_num + 1,
                "width": pix.width,
                "height": pix.height,
                "stash_ref": save_result['ref']
            })
    
    doc.close()
    
    return {
        "ok": True,
        "speech": f"Converted {len(outputs)} pages to {image_format.upper()} images",
        "data": {
            "images": outputs,
            "count": len(outputs),
            "space_id": space.space_id
        }
    }


def action_search(args: dict) -> dict:
    """Search for text in PDF."""
    if not HAS_PYMUPDF:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_path = resolve_pdf_path(args)
    query = args.get('query')
    
    if not query:
        raise ValueError("query is required for search")
    
    doc = fitz.open(pdf_path)
    
    results = []
    for page_num in range(doc.page_count):
        page = doc[page_num]
        text_instances = page.search_for(query)
        
        if text_instances:
            # Get surrounding context
            full_text = page.get_text()
            query_lower = query.lower()
            text_lower = full_text.lower()
            
            contexts = []
            start = 0
            while True:
                idx = text_lower.find(query_lower, start)
                if idx == -1:
                    break
                # Get context (50 chars before and after)
                ctx_start = max(0, idx - 50)
                ctx_end = min(len(full_text), idx + len(query) + 50)
                context = full_text[ctx_start:ctx_end].replace('\n', ' ').strip()
                contexts.append(f"...{context}...")
                start = idx + 1
            
            results.append({
                "page": page_num + 1,
                "match_count": len(text_instances),
                "contexts": contexts[:3]  # Limit to 3 contexts per page
            })
    
    doc.close()
    
    total_matches = sum(r['match_count'] for r in results)
    
    return {
        "ok": True,
        "speech": f"Found '{query}' {total_matches} times across {len(results)} pages",
        "data": {
            "query": query,
            "total_matches": total_matches,
            "pages_with_matches": len(results),
            "results": results
        }
    }


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()

        if args.get('output_name') is not None:
            args['output_name'] = validate_tool_output_filename(
                args['output_name'],
                label="PDF output name",
            )
        
        # Get action
        action = args.get('action', 'info').lower()
        
        # Dispatch to action handler
        handlers = {
            'info': action_info,
            'extract_text': action_extract_text,
            'extract_images': action_extract_images,
            'merge': action_merge,
            'split': action_split,
            'to_images': action_to_images,
            'search': action_search,
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
