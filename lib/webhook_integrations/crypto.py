"""Versioned AES-GCM keys. Callers serialize key changes with the control DB.

The keyring is separate from database exports. Keeping both keys before a DB
rotation commit makes a crash recoverable; retirement happens only after commit.
"""
import base64
import json
import os
import stat
import tempfile
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lib.background_tasks.models import TaskError


class KeyStore:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                        or info.st_uid != os.geteuid()):
                    raise TaskError('Integration key requires an owner-only regular file')
                data = json.loads(handle.read(65537))
            if set(data) != {'active', 'keys'} or not 1 <= len(data['keys']) <= 16:
                raise ValueError()
            if data['active'] not in data['keys']:
                raise ValueError()
            for key in data['keys'].values():
                if len(base64.b64decode(key, validate=True)) != 32:
                    raise ValueError()
            return data
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise TaskError('Integration key is missing or invalid; restore it, never regenerate over credentials') from exc

    def write(self, ring, *, exclusive=False):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        encoded = json.dumps(ring).encode()
        if exclusive:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            self.read()  # Never silently replace a missing/unsafe keyring.
            fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix='.task-key-')
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, self.path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    @staticmethod
    def new_ring():
        version = uuid.uuid4().hex
        return {'active': version, 'keys': {version: base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()}}

    @staticmethod
    def aad(source, credential, version):
        return json.dumps(['jarvis-task-credential-v1', source, credential, version], separators=(',', ':')).encode()

    def encrypt(self, secret, source, credential, version, *, ring=None):
        ring = ring or self.read()
        key_id, nonce = ring['active'], os.urandom(12)
        ciphertext = AESGCM(base64.b64decode(ring['keys'][key_id])).encrypt(
            nonce, secret.encode(), self.aad(source, credential, version))
        return json.dumps({'key': key_id, 'value': base64.b64encode(nonce + ciphertext).decode()})

    def decrypt(self, encoded, source, credential, version, *, ring=None):
        try:
            ring = ring or self.read()
            envelope = json.loads(encoded)
            value = base64.b64decode(envelope['value'], validate=True)
            return AESGCM(base64.b64decode(ring['keys'][envelope['key']])).decrypt(
                value[:12], value[12:], self.aad(source, credential, version)).decode()
        except (InvalidTag, KeyError, ValueError, TypeError) as exc:
            raise TaskError('Integration credential authentication failed; restore the matching key') from exc
