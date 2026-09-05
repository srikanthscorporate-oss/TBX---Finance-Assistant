"""Field encryption for account numbers and UTRs.

AES-256-GCM with a random 96-bit nonce per value; the stored form is base64 of
nonce || ciphertext || tag. Equality search on an encrypted column is impossible,
so each searchable field also stores an HMAC-SHA256 blind index under a key
derived from the same master key. The key never reaches ClickHouse: the loader
encrypts before insert and the API decrypts after select.

The master key is TBX_DATA_KEY, 32 bytes as 64 hex characters. This module has
no dependency on the rest of the app so the loader can import it directly.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENV_KEY = "TBX_DATA_KEY"
_NONCE_BYTES = 12


class KeyError_(RuntimeError):
    """The data key is missing or malformed."""


def load_key(value: str | None = None) -> bytes:
    raw = value if value is not None else os.getenv(ENV_KEY, "")
    raw = raw.strip()
    if len(raw) != 64:
        raise KeyError_(f"{ENV_KEY} must be 64 hex characters (32 bytes); got {len(raw)}")
    try:
        return bytes.fromhex(raw)
    except ValueError as e:
        raise KeyError_(f"{ENV_KEY} is not valid hex") from e


class FieldCipher:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise KeyError_("key must be 32 bytes")
        self._aead = AESGCM(key)
        self._index_key = hashlib.sha256(b"tbx-blind-index|" + key).digest()

    @classmethod
    def from_env(cls) -> "FieldCipher":
        return cls(load_key())

    def encrypt(self, plaintext: str) -> str:
        if plaintext == "":
            return ""
        nonce = os.urandom(_NONCE_BYTES)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        if token == "":
            return ""
        try:
            blob = base64.b64decode(token, validate=True)
            return self._aead.decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], None).decode("utf-8")
        except (InvalidTag, ValueError) as e:
            raise ValueError("ciphertext did not authenticate under this key") from e

    def blind_index(self, value: str) -> str:
        """Deterministic keyed hash for equality lookup. Normalised so a UTR typed with
        different case or stray spaces still matches."""
        norm = "".join(value.split()).upper()
        if not norm:
            return ""
        return hmac.new(self._index_key, norm.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_account(number: str) -> str:
    """Show the last four digits only. Applied after decryption, before anything leaves the API."""
    digits = number.strip()
    if len(digits) <= 4:
        return "X" * len(digits)
    return "X" * (len(digits) - 4) + digits[-4:]
