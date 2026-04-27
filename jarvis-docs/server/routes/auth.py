"""
Authentication routes for Jarvis Docs.
"""
from flask import Blueprint, jsonify, request

from webui_auth import (
    create_token,
    get_auth_status,
    get_token_from_request,
    is_auth_enabled,
    verify_password,
    verify_token,
)


auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/status', methods=['GET'])
def auth_status():
    return jsonify({'ok': True, **get_auth_status()})


@auth_bp.route('/login', methods=['POST'])
def login():
    if not is_auth_enabled():
        return jsonify({'ok': False, 'error': 'Auth not configured'}), 400

    data = request.get_json() or {}
    password = data.get('password', '')
    if not password:
        return jsonify({'ok': False, 'error': 'Password required'}), 400

    if verify_password(password):
        token = create_token()
        status = get_auth_status()
        return jsonify({'ok': True, 'token': token, 'expires_in_days': status['token_expiry_days']})
    return jsonify({'ok': False, 'error': 'Invalid password'}), 401


@auth_bp.route('/verify', methods=['GET'])
def verify():
    token = get_token_from_request(request)
    payload = verify_token(token)
    if payload:
        return jsonify({'ok': True, 'expires_at': payload.get('exp')})
    return jsonify({'ok': False, 'error': 'Invalid token'}), 401


@auth_bp.route('/logout', methods=['POST'])
def logout():
    return jsonify({'ok': True, 'message': 'Logged out'})
