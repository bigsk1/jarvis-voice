#!/usr/bin/env python3
"""
QR Code Generator - Generate QR codes for URLs, text, WiFi config, etc.
Outputs PNG to stash for printing, canvas, or email.
"""
import sys
import os
import json
import io
from importlib.util import find_spec

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config
from stash_helper import open_space, StashFile
from memory_db import MemoryDB

def build_wifi_string(ssid, password='', security='WPA', hidden=False):
    """Build WiFi QR code string in standard format."""
    # Escape special chars: backslash, semicolon, comma, quote, colon
    def escape(s):
        for ch in ['\\', ';', ',', '"', ':']:
            s = s.replace(ch, '\\' + ch)
        return s
    
    ssid_escaped = escape(ssid)
    password_escaped = escape(password) if password else ''
    security = security.upper() if security else 'nopass'
    if security not in ['WPA', 'WEP', 'nopass']:
        security = 'WPA'
    
    hidden_str = 'true' if hidden else 'false'
    if security == 'nopass' or not password:
        return f'WIFI:T:nopass;S:{ssid_escaped};;H:{hidden_str};'
    else:
        return f'WIFI:T:{security};S:{ssid_escaped};P:{password_escaped};;H:{hidden_str};'

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        # Import qrcode
        try:
            import qrcode
            from qrcode.image.pure import PyPNGImage
        except ImportError:
            # Try alternative
            try:
                import qrcode
            except ImportError:
                print(json.dumps({
                    "ok": False,
                    "error": "qrcode package not installed. Run: pip install qrcode[pil]",
                    "speech": "QR code package is not installed. Please install qrcode with PIL support."
                }))
                sys.exit(1)
        
        # Prefer PIL rendering when qrcode was installed with image support.
        has_pil = find_spec("PIL") is not None
        
        # Extract parameters
        qr_type = args.get('type', 'text').lower()  # text, url, wifi, email
        content = args.get('content', '')            # raw content (for text/url)
        filename = args.get('filename', '')           # optional custom filename
        
        # Size params
        box_size = int(args.get('box_size', 10))      # pixels per box
        border = int(args.get('border', 4))           # boxes for border
        
        # WiFi specific params
        wifi_ssid = args.get('ssid', args.get('wifi_ssid', ''))
        wifi_password = args.get('password', args.get('wifi_password', ''))
        wifi_security = args.get('security', args.get('wifi_security', 'WPA'))
        wifi_hidden = args.get('hidden', args.get('wifi_hidden', False))
        
        # Build the QR content string
        if qr_type == 'wifi':
            if not wifi_ssid:
                # Try to parse from content field
                if content:
                    wifi_ssid = content
                else:
                    print(json.dumps({
                        "ok": False,
                        "error": "WiFi QR code requires 'ssid' parameter",
                        "speech": "Please provide the WiFi network name (SSID) to generate a WiFi QR code."
                    }))
                    sys.exit(1)
            qr_data = build_wifi_string(wifi_ssid, wifi_password, wifi_security, wifi_hidden)
            label = f"WiFi: {wifi_ssid}"
            default_filename = f"wifi_{wifi_ssid.replace(' ', '_')}.png"
            speech_desc = f"WiFi QR code for network {wifi_ssid}"
        elif qr_type == 'email':
            email = content
            if not email.startswith('mailto:'):
                qr_data = f'mailto:{email}'
            else:
                qr_data = email
            label = f"Email: {email}"
            default_filename = "email_qr.png"
            speech_desc = f"Email QR code for {email}"
        elif qr_type == 'url':
            qr_data = content
            if not qr_data:
                print(json.dumps({"ok": False, "error": "URL content is required", "speech": "Please provide a URL to generate a QR code."}))
                sys.exit(1)
            # Auto-add https if missing
            if not qr_data.startswith('http://') and not qr_data.startswith('https://'):
                qr_data = 'https://' + qr_data
            label = qr_data
            # Create a safe filename from URL
            url_part = qr_data.replace('https://', '').replace('http://', '').replace('/', '_').replace('?', '_')[:40]
            default_filename = f"url_{url_part}.png"
            speech_desc = f"URL QR code for {qr_data}"
        else:
            # Plain text (default)
            qr_data = content
            if not qr_data:
                print(json.dumps({"ok": False, "error": "Content is required", "speech": "Please provide text content to generate a QR code."}))
                sys.exit(1)
            label = content[:50]
            safe_name = content[:20].replace(' ', '_').replace('/', '_')
            default_filename = f"text_{safe_name}.png"
            speech_desc = f"QR code for: {content[:50]}"
        
        final_filename = filename if filename else default_filename
        if not final_filename.endswith('.png'):
            final_filename += '.png'
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=None,  # Auto-size
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=box_size,
            border=border,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Render to bytes
        img_bytes = io.BytesIO()
        
        if has_pil:
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(img_bytes, format='PNG')
        else:
            # Use pure PNG fallback
            try:
                img = qr.make_image(image_factory=PyPNGImage)
                img.save(img_bytes)
            except Exception:
                # Last resort: basic PIL-free approach
                img = qr.make_image()
                img.save(img_bytes, format='PNG')
        
        img_bytes.seek(0)
        png_data = img_bytes.read()
        
        if not png_data:
            raise ValueError("Failed to generate QR code image")
        
        # Save to stash
        space, _ = open_space(scope='session', labels=['qr_codes'])
        stash_file = StashFile(space)
        result = stash_file.save_binary(
            data=png_data,
            name=final_filename,
            mime_type='image/png',
            on_conflict='version',
            tool_origin='qr_code_generator'
        )
        
        success = bool(result.get('file_id'))
        stash_ref = result.get('ref')
        file_path = result.get('path', '')
        
        if not success:
            raise ValueError(f"Failed to save QR code to stash: {result}")
        
        # Save to memory for follow-up queries
        db = MemoryDB()
        db.remember(
            key=f"qr_code_{space.space_id}",
            value=f"QR code generated: {speech_desc}. Filename: {final_filename}. STASH: {stash_ref}",
            category="stash_artifact",
            importance=6,
            source="qr_code_generator",
            metadata={
                "stash_ref": stash_ref,
                "space_id": space.space_id,
                "filename": final_filename,
                "qr_type": qr_type,
                "qr_data": qr_data[:100],
                "tags": ["qr_code", qr_type],
                "type": "qr_code"
            }
        )
        
        # Get image dimensions for info
        qr_matrix = qr.get_matrix()
        qr_size = len(qr_matrix)
        pixel_size = qr_size * box_size + 2 * border * box_size
        
        print(json.dumps({
            "ok": True,
            "speech": f"Generated {speech_desc}. Saved as {final_filename}. The QR code is {pixel_size} by {pixel_size} pixels and ready to print or share.",
            "data": {
                "stash_ref": stash_ref,
                "filename": final_filename,
                "path": file_path,
                "qr_type": qr_type,
                "content_encoded": qr_data[:200],
                "size_bytes": result.get('size_bytes'),
                "pixel_dimensions": f"{pixel_size}x{pixel_size}",
                "qr_modules": qr_size,
                "label": label
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to generate QR code: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()
