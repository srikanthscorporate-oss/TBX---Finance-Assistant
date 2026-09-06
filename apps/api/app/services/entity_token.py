"""Entity ids never leave the API in plaintext.

The browser holds an AES-256-GCM token of the id and a masked label; every request
carries the token back and the API decrypts it before scoping a query. Without a data
key (offline tests) the token is the plaintext, so nothing else changes shape.
"""
from __future__ import annotations

from .crypto import FieldCipher, KeyError_

_cipher: FieldCipher | None
try:
    _cipher = FieldCipher.from_env()
except KeyError_:
    _cipher = None


class BadEntityToken(ValueError):
    """The token did not decrypt under this server's key."""


def encode(entity_id: str) -> str:
    return _cipher.encrypt(entity_id) if _cipher else entity_id


def decode(token: str) -> str:
    token = token.strip()
    if not token:
        raise BadEntityToken("empty entity token")
    if _cipher is None:
        return token
    try:
        return _cipher.decrypt(token)
    except ValueError as e:
        raise BadEntityToken("entity token did not decrypt") from e


def mask(entity_id: str | None) -> str | None:
    if not entity_id:
        return entity_id
    if len(entity_id) <= 4:
        return "*" * len(entity_id)
    return "*" * (len(entity_id) - 4) + entity_id[-4:]
