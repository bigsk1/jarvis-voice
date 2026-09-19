"""Explicit bootstrap, non-reversible bearer verifiers and versioned HMAC keys."""
import hmac
import json
import re
import secrets
import uuid

from lib.background_tasks.models import TaskError

from .contracts import CallbackError, secret_hash, signature
from .crypto import KeyStore


class CredentialStore:
    def initialize_key(self):
        with self.store._connection(write=True) as conn:
            if self.keys.path.exists():
                self.keys.read()
            else:
                if conn.execute('SELECT 1 FROM task_credentials LIMIT 1').fetchone():
                    raise TaskError('Credentials exist: restore the original key instead of initializing another')
                self.keys.write(KeyStore.new_ring(), exclusive=True)
        return {'ready': True}

    def rotate_key(self):
        # First persist both keys. If interrupted at any later step, every
        # ciphertext remains decryptable. No key is retired before DB commit.
        with self.store._connection(write=True) as conn:
            ring = self.keys.read()
            # Prune only unreferenced keys before adding a version. Repeated
            # interrupted rotations must not grow an unreadable keyring.
            used = {json.loads(row[0])['key'] for row in conn.execute(
                'SELECT encrypted FROM task_credentials WHERE encrypted IS NOT NULL')}
            ring['keys'] = {key: value for key, value in ring['keys'].items() if key in used}
            if len(ring['keys']) >= 16:
                raise TaskError('Too many live key versions; finish the interrupted rotation before adding another')
            replacement = KeyStore.new_ring()
            ring['keys'].update(replacement['keys'])
            ring['active'] = replacement['active']
            self.keys.write(ring)
            for row in conn.execute('SELECT * FROM task_credentials WHERE encrypted IS NOT NULL'):
                plain = self.keys.decrypt(row['encrypted'], row['source_id'], row['id'], row['version'], ring=ring)
                value = self.keys.encrypt(plain, row['source_id'], row['id'], row['version'], ring=ring)
                if self.keys.decrypt(value, row['source_id'], row['id'], row['version'], ring=ring) != plain:
                    raise TaskError('Replacement credential verification failed')
                conn.execute('UPDATE task_credentials SET encrypted=? WHERE id=?', (value, row['id']))
        # A separate transaction prevents a concurrent credential write/rotation
        # from selecting a key while it is being retired.
        with self.store._connection(write=True) as conn:
            ring = self.keys.read()
            used = {json.loads(row[0])['key'] for row in conn.execute(
                'SELECT encrypted FROM task_credentials WHERE encrypted IS NOT NULL')}
            used.add(ring['active'])
            ring['keys'] = {key: value for key, value in ring['keys'].items() if key in used}
            self.keys.write(ring)
        return {'ready': True}

    def create_credential(self, source_id, *, scheme='bearer', expires_in=86400 * 90,
                          replace_id=None, overlap_seconds=300, probe=False):
        if scheme not in {'bearer', 'hmac-sha256'}:
            raise TaskError('Unsupported authentication scheme')
        if (type(expires_in) is not int or not 60 <= expires_in <= 86400 * 365
                or type(overlap_seconds) is not int or not 0 <= overlap_seconds <= 3600):
            raise TaskError('Invalid credential lifetime/rotation overlap')
        with self.store._connection(write=True) as conn:
            source = self._source(conn, source_id)
            if source['revoked']:
                raise TaskError('Revoked integrations cannot receive credentials')
            self.keys.read()  # Explicit bootstrap is required even for bearer credentials.
            now, cid, secret = self.store._time(), uuid.uuid4().hex, secrets.token_urlsafe(32)
            version = conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM task_credentials WHERE source_id=?',
                                   (source_id,)).fetchone()[0]
            if conn.execute('SELECT COUNT(*) FROM task_credentials WHERE source_id=? AND revoked_at IS NULL AND expires_at>?',
                            (source_id, now)).fetchone()[0] >= 32:
                raise TaskError('Revoke unused credentials before adding more')
            if replace_id:
                old = conn.execute('SELECT * FROM task_credentials WHERE id=? AND source_id=?',
                                   (replace_id, source_id)).fetchone()
                if not old or old['revoked_at'] is not None:
                    raise TaskError('Credential cannot be rotated')
                conn.execute('UPDATE task_credentials SET expires_at=MIN(expires_at,?) WHERE id=?',
                             (now + overlap_seconds, replace_id))
            encrypted = self.keys.encrypt(secret, source_id, cid, version) if scheme == 'hmac-sha256' else None
            conn.execute('''INSERT INTO task_credentials(id,source_id,version,scheme,verifier,encrypted,
                created_at,expires_at,probe,probe_revision) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                         (cid, source_id, version, scheme, secret_hash(secret) if not encrypted else None,
                          encrypted, now, now + expires_in, int(probe), source['revision'] if probe else None))
        return {'id': cid, 'version': version, 'scheme': scheme, 'secret': secret,
                'expires_at': now + expires_in, 'authorization': f'Bearer {cid}.{secret}' if scheme == 'bearer' else None}

    def revoke_credential(self, source_id, credential_id):
        with self.store._connection(write=True) as conn:
            updated = conn.execute('UPDATE task_credentials SET revoked_at=? WHERE id=? AND source_id=?',
                                   (self.store._time(), credential_id, source_id)).rowcount
            if not updated:
                raise TaskError('Credential not found')
            conn.execute("UPDATE task_callback_inbox SET state='held',reason='credential_revoked' WHERE credential_id=? AND state='pending'",
                         (credential_id,))

    def _authenticate(self, conn, source_id, headers, raw):
        now = self.store._time()
        timestamp = headers.get('x-jarvis-timestamp', '')
        try:
            if not timestamp.isascii() or not timestamp.isdecimal() or abs(now - int(timestamp)) > 300:
                raise ValueError()
        except (ValueError, TypeError):
            raise CallbackError('Invalid callback credentials or timestamp', 401) from None
        bearer = headers.get('authorization', '')
        if bearer.startswith('Bearer '):
            cid, _, secret = bearer[7:].partition('.')
            scheme = 'bearer'
        else:
            cid, secret, scheme = headers.get('x-jarvis-key-id', ''), '', 'hmac-sha256'
        row = conn.execute('SELECT * FROM task_credentials WHERE id=? AND source_id=?', (cid, source_id)).fetchone()
        if (not row or row['scheme'] != scheme or row['revoked_at'] is not None or row['expires_at'] <= now):
            raise CallbackError('Invalid callback credentials or timestamp', 401)
        if scheme == 'bearer':
            valid = hmac.compare_digest(row['verifier'], secret_hash(secret))
        else:
            key = self.keys.decrypt(row['encrypted'], source_id, row['id'], row['version'])
            received = headers.get('x-jarvis-signature', '')
            valid_format = bool(re.fullmatch('[a-f0-9]{64}', received))
            matched = hmac.compare_digest(signature(key, source_id, timestamp, raw),
                                          received if valid_format else '0' * 64)
            valid = matched and valid_format
        if not valid:
            raise CallbackError('Invalid callback credentials or timestamp', 401)
        return row
