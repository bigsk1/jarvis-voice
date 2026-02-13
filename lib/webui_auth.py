"""
Shared WebUI Authentication Library

JWT-based auth that works across all Jarvis web UIs:
- jarvis-web (5001)
- jarvis-canvas (8890)
- jarvis-intelligence (5002)
- jarvis-memory (5003)

Usage:
    from lib.webui_auth import create_token, verify_token, get_password_from_env

Environment variables:
    WEBUI_PASSWORD - Required password to access web UIs
    WEBUI_SECRET - JWT signing secret (auto-generated if not set)
"""

import os
import hashlib
import secrets
import time
import json
import base64
from datetime import datetime
from functools import wraps
from pathlib import Path

# Auth log file
LOG_DIR = Path(__file__).parent.parent / 'logs' / 'auth'
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_auth_event(event: str, details: dict = None, success: bool = True):
    """Log authentication events for debugging."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = LOG_DIR / f"auth-{today}.jsonl"
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "success": success,
            **(details or {})
        }
        
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass  # Don't let logging failures break auth

# JWT expiry - default 30 days, configurable via WEBUI_TOKEN_EXPIRY_DAYS
def _get_token_expiry() -> int:
    """Get token expiry in seconds from env or default (30 days)"""
    days = int(os.environ.get('WEBUI_TOKEN_EXPIRY_DAYS', '30'))
    return days * 86400

TOKEN_EXPIRY_SECONDS = 30 * 86400  # Default 30 days (can be overridden at runtime)

# Auto-generate secret if not in env (stored in data/)
SECRET_FILE = Path(__file__).parent.parent / 'data' / '.webui_secret'


def _get_secret() -> str:
    """Get or generate the JWT signing secret"""
    # First check env
    secret = os.environ.get('WEBUI_SECRET')
    if secret:
        return secret
    
    # Check/create secret file
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip()
    
    # Generate new secret
    secret = secrets.token_hex(32)
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(secret)
    return secret


def get_password_from_env() -> str | None:
    """Get the WebUI password from environment"""
    return os.environ.get('WEBUI_PASSWORD')


def is_auth_enabled() -> bool:
    """Check if auth is enabled (password is set)"""
    password = get_password_from_env()
    return password is not None and len(password) > 0


def verify_password(password: str) -> bool:
    """Verify the provided password matches"""
    correct = get_password_from_env()
    if not correct:
        _log_auth_event("password_verify", {"reason": "no_password_configured"}, success=False)
        return False
    
    result = secrets.compare_digest(password, correct)
    if not result:
        _log_auth_event("password_verify", {"reason": "invalid_password"}, success=False)
    else:
        _log_auth_event("login_success", {}, success=True)
    return result


def create_token(extra_claims: dict = None) -> str:
    """
    Create a JWT token for authenticated session
    
    Simple JWT implementation (no external deps):
    - Header: {"alg": "HS256", "typ": "JWT"}
    - Payload: {"exp": timestamp, "iat": timestamp, ...extra_claims}
    - Signature: HMAC-SHA256
    """
    secret = _get_secret()
    now = int(time.time())
    expiry = _get_token_expiry()
    
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iat": now,
        "exp": now + expiry,
        "iss": "jarvis-webui"
    }
    if extra_claims:
        payload.update(extra_claims)
    
    # Encode
    def b64_encode(data: dict) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(data, separators=(',', ':')).encode()
        ).rstrip(b'=').decode()
    
    header_b64 = b64_encode(header)
    payload_b64 = b64_encode(payload)
    
    # Sign
    message = f"{header_b64}.{payload_b64}"
    signature = hashlib.sha256(
        (message + secret).encode()
    ).hexdigest()
    
    return f"{header_b64}.{payload_b64}.{signature}"


def verify_token(token: str) -> dict | None:
    """
    Verify a JWT token and return the payload if valid
    Returns None if invalid or expired
    """
    if not token:
        return None
    
    try:
        parts = token.split('.')
        if len(parts) != 3:
            _log_auth_event("token_verify", {"reason": "malformed_token"}, success=False)
            return None
        
        header_b64, payload_b64, signature = parts
        secret = _get_secret()
        
        # Verify signature
        message = f"{header_b64}.{payload_b64}"
        expected_sig = hashlib.sha256(
            (message + secret).encode()
        ).hexdigest()
        
        if not secrets.compare_digest(signature, expected_sig):
            _log_auth_event("token_verify", {"reason": "invalid_signature"}, success=False)
            return None
        
        # Decode payload
        def b64_decode(data: str) -> dict:
            # Add padding if needed
            padding = 4 - len(data) % 4
            if padding != 4:
                data += '=' * padding
            return json.loads(base64.urlsafe_b64decode(data))
        
        payload = b64_decode(payload_b64)
        
        # Check expiry
        if payload.get('exp', 0) < time.time():
            _log_auth_event("token_verify", {"reason": "token_expired"}, success=False)
            return None
        
        return payload
    
    except Exception as e:
        _log_auth_event("token_verify", {"reason": "exception", "error": str(e)}, success=False)
        return None


def get_token_from_request(request) -> str | None:
    """
    Extract token from Flask/FastAPI request
    Checks: Authorization header, cookie, query param
    """
    # Authorization header: Bearer <token>
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    
    # Cookie
    token = request.cookies.get('jarvis_auth')
    if token:
        return token
    
    # Query param (for redirects)
    token = request.args.get('auth_token') if hasattr(request, 'args') else None
    if token:
        return token
    
    return None


# Flask decorator for protected routes
def require_auth(f):
    """
    Flask route decorator that requires valid auth token
    Usage:
        @app.route('/protected')
        @require_auth
        def protected_route():
            return "Secret stuff"
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import request, redirect, url_for, jsonify
        
        # Skip if auth not enabled
        if not is_auth_enabled():
            return f(*args, **kwargs)
        
        token = get_token_from_request(request)
        payload = verify_token(token)
        
        if not payload:
            # API request - return 401
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'ok': False, 'error': 'Authentication required'}), 401
            # Page request - redirect to login
            return redirect('/login')
        
        return f(*args, **kwargs)
    
    return decorated_function


def log_auth_blocked(path: str, reason: str = "no_token"):
    """Log when a request is blocked by auth middleware."""
    _log_auth_event("request_blocked", {"path": path, "reason": reason}, success=False)


# For checking auth status in templates/JS
def get_auth_status() -> dict:
    """Get current auth configuration status"""
    expiry = _get_token_expiry()
    return {
        'enabled': is_auth_enabled(),
        'token_expiry_days': expiry // 86400,
        'token_expiry_hours': expiry // 3600
    }
