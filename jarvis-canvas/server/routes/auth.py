"""
Authentication routes for Jarvis Canvas
"""
from flask import Blueprint, request, jsonify
import sys
from pathlib import Path

# Add lib to path
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from webui_auth import (
    verify_password,
    create_token,
    verify_token,
    get_token_from_request,
    is_auth_enabled,
    get_auth_status
)

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/status', methods=['GET'])
def auth_status():
    """Check if auth is enabled and get config"""
    return jsonify({
        'ok': True,
        **get_auth_status()
    })


@auth_bp.route('/login', methods=['POST'])
def login():
    """Login with password, returns JWT token"""
    if not is_auth_enabled():
        return jsonify({
            'ok': False,
            'error': 'Authentication not configured. Set WEBUI_PASSWORD in env.'
        }), 400
    
    data = request.get_json() or {}
    password = data.get('password', '')
    
    if not password:
        return jsonify({'ok': False, 'error': 'Password required'}), 400
    
    if verify_password(password):
        token = create_token()
        status = get_auth_status()
        return jsonify({
            'ok': True,
            'token': token,
            'expires_in_days': status['token_expiry_days']
        })
    else:
        return jsonify({'ok': False, 'error': 'Invalid password'}), 401


@auth_bp.route('/verify', methods=['GET'])
def verify():
    """Verify if current token is valid"""
    token = get_token_from_request(request)
    payload = verify_token(token)
    
    if payload:
        return jsonify({
            'ok': True,
            'expires_at': payload.get('exp'),
            'issued_at': payload.get('iat')
        })
    else:
        return jsonify({'ok': False, 'error': 'Invalid or expired token'}), 401


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout - client should clear stored token"""
    return jsonify({
        'ok': True,
        'message': 'Logged out. Clear token from localStorage.'
    })
