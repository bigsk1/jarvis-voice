"""
Intel File Manager API Routes
Manage files in jarvis-intel/ folder
"""
import os
import sys
from pathlib import Path
from flask import Blueprint, jsonify, request

intel_bp = Blueprint('intel', __name__, url_prefix='/api/intel')

JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
INTEL_PATH = JARVIS_ROOT / 'jarvis-intel'
SKILLS_PATH = JARVIS_ROOT / 'skills'

if str(SKILLS_PATH) not in sys.path:
    sys.path.insert(0, str(SKILLS_PATH))

from manage_intel import auto_ingest, format_ingest_summary
from intel_content import normalize_intel_document_eof
from intel_filename import validate_create_filename


@intel_bp.route('/files', methods=['GET'])
def list_files():
    """List all intel files"""
    if not INTEL_PATH.exists():
        return jsonify({
            'ok': True,
            'files': [],
            'message': 'Intel folder does not exist'
        })
    
    files = []
    for filepath in INTEL_PATH.glob('*'):
        if filepath.is_file() and filepath.suffix.lower() in ['.md', '.txt']:
            if filepath.name == 'README.md':
                continue  # Skip README
            
            stat = filepath.stat()
            files.append({
                'name': filepath.name,
                'size': stat.st_size,
                'modified': stat.st_mtime,
                'extension': filepath.suffix.lower()
            })
    
    # Sort by modified time (newest first)
    files.sort(key=lambda x: x['modified'], reverse=True)
    
    return jsonify({
        'ok': True,
        'count': len(files),
        'files': files
    })


@intel_bp.route('/files/<filename>', methods=['GET'])
def get_file(filename: str):
    """Get contents of a specific intel file"""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    
    filepath = INTEL_PATH / filename
    
    if not filepath.exists():
        return jsonify({'ok': False, 'error': f'File not found: {filename}'}), 404
    
    if filepath.suffix.lower() not in ['.md', '.txt']:
        return jsonify({'ok': False, 'error': 'Only .md and .txt files allowed'}), 400
    
    try:
        content = filepath.read_text(encoding='utf-8')
        stat = filepath.stat()
        
        return jsonify({
            'ok': True,
            'file': {
                'name': filename,
                'content': content,
                'size': stat.st_size,
                'modified': stat.st_mtime
            }
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@intel_bp.route('/files/<filename>', methods=['PUT'])
def update_file(filename: str):
    """Update contents of an intel file"""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    
    filepath = INTEL_PATH / filename

    # Preserve update access to existing legacy files, but do not let PUT act
    # as a back door for creating a new noncanonical filename.
    if not filepath.exists():
        try:
            validate_create_filename(filename)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
    
    if filepath.suffix.lower() not in ['.md', '.txt']:
        return jsonify({'ok': False, 'error': 'Only .md and .txt files allowed'}), 400
    
    data = request.get_json() or {}
    content = data.get('content', '')
    content, _ = normalize_intel_document_eof(content)
    
    try:
        # Create intel folder if it doesn't exist
        INTEL_PATH.mkdir(exist_ok=True)
        
        filepath.write_text(content, encoding='utf-8')
        
        return jsonify({
            'ok': True,
            'message': f'File saved: {filename}',
            'size': len(content.encode('utf-8'))
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@intel_bp.route('/files', methods=['POST'])
def create_file():
    """Create a new intel file"""
    data = request.get_json() or {}
    
    filename = data.get('filename', '').strip()
    content = data.get('content', '')
    content, _ = normalize_intel_document_eof(content)
    
    if not filename:
        return jsonify({'ok': False, 'error': 'Filename is required'}), 400
    
    # Ensure proper extension
    if not filename.endswith(('.md', '.txt')):
        filename += '.md'
    
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400

    try:
        validate_create_filename(filename)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    
    filepath = INTEL_PATH / filename
    
    if filepath.exists():
        return jsonify({'ok': False, 'error': f'File already exists: {filename}'}), 409
    
    try:
        INTEL_PATH.mkdir(exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        
        return jsonify({
            'ok': True,
            'message': f'File created: {filename}',
            'filename': filename
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@intel_bp.route('/files/<filename>', methods=['DELETE'])
def delete_file(filename: str):
    """Delete an intel file"""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    
    filepath = INTEL_PATH / filename
    
    if not filepath.exists():
        return jsonify({'ok': False, 'error': f'File not found: {filename}'}), 404
    
    if filename == 'README.md':
        return jsonify({'ok': False, 'error': 'Cannot delete README.md'}), 400
    
    try:
        filepath.unlink()
        return jsonify({
            'ok': True,
            'message': f'File deleted: {filename}'
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@intel_bp.route('/upload', methods=['POST'])
def upload_file():
    """Upload a new intel file"""
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'ok': False, 'error': 'No file selected'}), 400
    
    filename = file.filename
    
    # Only allow .md and .txt
    if not filename.endswith(('.md', '.txt')):
        return jsonify({'ok': False, 'error': 'Only .md and .txt files allowed'}), 400
    
    # Security: use only the filename, not any path
    filename = os.path.basename(filename)
    
    # Sanitize filename
    if '..' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    
    filepath = INTEL_PATH / filename
    
    # Handle overwrite option
    overwrite = request.form.get('overwrite', 'false').lower() == 'true'
    if not filepath.exists():
        try:
            validate_create_filename(filename)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
    if filepath.exists() and not overwrite:
        return jsonify({
            'ok': False,
            'error': f'File already exists: {filename}. Set overwrite=true to replace.'
        }), 409
    
    try:
        INTEL_PATH.mkdir(exist_ok=True)
        file.save(str(filepath))
        
        return jsonify({
            'ok': True,
            'message': f'File uploaded: {filename}',
            'filename': filename,
            'size': filepath.stat().st_size
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@intel_bp.route('/ingest', methods=['POST'])
def ingest_intel():
    """
    Trigger the ingest_intel tool to process all intel files
    This adds the content to the knowledge_base
    """
    mode = request.args.get('mode', 'cloud').lower()

    if mode not in {'cloud', 'local'}:
        return jsonify({'ok': False, 'error': f'Invalid mode: {mode}'}), 400

    try:
        result = auto_ingest(JARVIS_ROOT, mode)
        if not result.get('ingested'):
            error = result.get('error', 'Ingest failed')
            status = 504 if 'timeout' in error.lower() else 500
            return jsonify({
                'ok': False,
                'mode': mode,
                'error': error,
                'data': result,
            }), status

        speech = format_ingest_summary(result)

        return jsonify({
            'ok': True,
            'mode': mode,
            'speech': speech,
            'data': result,
            'error': None,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
