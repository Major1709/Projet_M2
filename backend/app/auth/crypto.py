"""Encryption for the delegated grants, at rest.

AES-256-GCM, one random nonce per encryption, and the row's identity bound in as
associated data. Three choices worth stating, because each one closes a hole that
a plainer implementation leaves open.

**Authenticated encryption, not just encryption.** A refresh token that decrypts
to whatever an attacker chose is worse than one they can read: they could swap a
ciphertext for one of their own and have the process present it to Atlassian. GCM
refuses a modified ciphertext instead of returning garbage.

**A fresh nonce every time.** Reusing a nonce under one key breaks GCM
catastrophically -- it leaks the authentication key, not merely the plaintext. So
the nonce is drawn at random per call and stored beside the ciphertext, never
derived from anything that repeats.

**The tenant and user as associated data.** Without it, a ciphertext lifted from
one row and written into another still decrypts, and whoever owns the second row
inherits the first one's Atlassian access. Bound in, the move fails to
authenticate.
"""

import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 96 bits, the size GCM is specified for. Longer nonces are hashed internally,
# which loses the guarantee that distinct nonces stay distinct.
NONCE_BYTES: Final = 12
KEY_BYTES: Final = 32
# Stamped on every row. A key rotation writes rows at the new version while the
# old ones stay readable, so the migration can be gradual instead of a flag day
# that invalidates every grant at once.
CURRENT_KEY_VERSION: Final = 1


class GrantCipherError(RuntimeError):
    """The stored grant could not be decrypted."""

    code = "GRANT_CIPHER_FAILED"


def load_key(material: str) -> bytes:
    """Read a 32-byte key from its hexadecimal form.

    Hexadecimal rather than raw bytes because the key travels as a file a human
    creates, and a raw binary file invites a trailing newline that silently
    becomes part of the key.
    """

    cleaned = material.strip()
    try:
        key = bytes.fromhex(cleaned)
    except ValueError as error:
        raise GrantCipherError("The token encryption key must be hexadecimal") from error
    if len(key) != KEY_BYTES:
        raise GrantCipherError(
            f"The token encryption key must be {KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def _associated_data(tenant_id: str, user_id: str) -> bytes:
    # The unit separator, so ("ab", "c") and ("a", "bc") cannot produce the same
    # binding -- the same reason the identity fingerprint uses one.
    return f"{tenant_id}\x1f{user_id}".encode()


class GrantCipher:
    """Encrypts and decrypts one secret at a time, bound to a row's identity."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise GrantCipherError(f"The token encryption key must be {KEY_BYTES} bytes")
        self._aead = AESGCM(key)

    def encrypt(self, secret: str, *, tenant_id: str, user_id: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(
            nonce, secret.encode("utf-8"), _associated_data(tenant_id, user_id)
        )
        # The nonce is not secret and must travel with the ciphertext; prefixing it
        # keeps the pair in one column, so no schema change can separate them.
        return nonce + sealed

    def decrypt(self, blob: bytes, *, tenant_id: str, user_id: str) -> str:
        if len(blob) <= NONCE_BYTES:
            raise GrantCipherError("The stored grant is too short to contain a nonce")
        nonce, sealed = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        try:
            plain = self._aead.decrypt(nonce, sealed, _associated_data(tenant_id, user_id))
        except InvalidTag as error:
            # Wrong key, altered ciphertext, or a row moved between identities.
            # Indistinguishable on purpose: telling them apart would tell an
            # attacker which of the three they achieved.
            raise GrantCipherError("The stored grant failed to authenticate") from error
        return plain.decode("utf-8")
