"""Encryption of the delegated grants.

Cryptographic mistakes do not announce themselves: a wrong construction still
encrypts, still decrypts, and still passes a round-trip test. So the assertions
here are mostly about what must FAIL -- a moved ciphertext, a flipped byte, a
wrong key -- because those are the properties that a plainer implementation
silently lacks.
"""

import pytest

from app.auth.crypto import (
    CURRENT_KEY_VERSION,
    KEY_BYTES,
    NONCE_BYTES,
    GrantCipher,
    GrantCipherError,
    load_key,
)

KEY_A = bytes(range(KEY_BYTES))
KEY_B = bytes(range(1, KEY_BYTES + 1))
SECRET = "rt-un-jeton-de-rafraichissement"


def cipher(key: bytes = KEY_A) -> GrantCipher:
    return GrantCipher(key)


def test_a_sealed_secret_comes_back_unchanged() -> None:
    sealed = cipher().encrypt(SECRET, tenant_id="t-1", user_id="u-1")

    assert cipher().decrypt(sealed, tenant_id="t-1", user_id="u-1") == SECRET


def test_the_ciphertext_does_not_contain_the_secret() -> None:
    sealed = cipher().encrypt(SECRET, tenant_id="t-1", user_id="u-1")

    assert SECRET.encode() not in sealed


def test_two_sealings_of_one_secret_differ() -> None:
    """A fresh nonce every time, and this is how you can tell.

    Reusing a nonce under one key does not merely leak the plaintext -- for GCM
    it leaks the authentication key, after which any ciphertext can be forged.
    Identical outputs here would be the visible symptom of that.
    """

    premier = cipher().encrypt(SECRET, tenant_id="t-1", user_id="u-1")
    second = cipher().encrypt(SECRET, tenant_id="t-1", user_id="u-1")

    assert premier != second
    assert premier[:NONCE_BYTES] != second[:NONCE_BYTES]


def test_a_row_moved_to_another_identity_refuses_to_open() -> None:
    """The property that makes the associated data worth having.

    Without it, a ciphertext lifted from one row and written into another still
    decrypts, and whoever owns the second row inherits the first one's Atlassian
    access -- a privilege escalation performed with an UPDATE statement.
    """

    sealed = cipher().encrypt(SECRET, tenant_id="t-1", user_id="u-1")

    with pytest.raises(GrantCipherError):
        cipher().decrypt(sealed, tenant_id="t-1", user_id="u-2")
    with pytest.raises(GrantCipherError):
        cipher().decrypt(sealed, tenant_id="t-2", user_id="u-1")


def test_the_identity_binding_cannot_be_confused_by_a_shifted_boundary() -> None:
    # ("ab", "c") and ("a", "bc") must not produce the same binding, or the
    # protection above can be sidestepped by choosing names.
    sealed = cipher().encrypt(SECRET, tenant_id="ab", user_id="c")

    with pytest.raises(GrantCipherError):
        cipher().decrypt(sealed, tenant_id="a", user_id="bc")


def test_a_tampered_ciphertext_is_refused_rather_than_decoded() -> None:
    """Authenticated encryption, not merely encryption.

    A grant that decrypts to whatever an attacker chose is worse than one they
    can read: they could substitute a token of their own and have the process
    present it to Atlassian.
    """

    sealed = bytearray(cipher().encrypt(SECRET, tenant_id="t-1", user_id="u-1"))
    sealed[-1] ^= 0x01

    with pytest.raises(GrantCipherError):
        cipher().decrypt(bytes(sealed), tenant_id="t-1", user_id="u-1")


def test_a_tampered_nonce_is_refused_too() -> None:
    sealed = bytearray(cipher().encrypt(SECRET, tenant_id="t-1", user_id="u-1"))
    sealed[0] ^= 0x01

    with pytest.raises(GrantCipherError):
        cipher().decrypt(bytes(sealed), tenant_id="t-1", user_id="u-1")


def test_another_key_cannot_open_the_row() -> None:
    sealed = cipher(KEY_A).encrypt(SECRET, tenant_id="t-1", user_id="u-1")

    with pytest.raises(GrantCipherError):
        cipher(KEY_B).decrypt(sealed, tenant_id="t-1", user_id="u-1")


def test_a_truncated_row_is_refused_before_it_reaches_the_cipher() -> None:
    with pytest.raises(GrantCipherError):
        cipher().decrypt(b"court", tenant_id="t-1", user_id="u-1")


@pytest.mark.parametrize(
    "material",
    [
        "",
        "pas-de-l-hexadecimal",
        "00" * (KEY_BYTES - 1),  # too short
        "00" * (KEY_BYTES + 1),  # too long
    ],
)
def test_a_key_of_the_wrong_shape_is_refused_at_load(material: str) -> None:
    # Refused when it is read, not when the first grant fails to open: a
    # deployment holding an unusable key should learn it at startup.
    with pytest.raises(GrantCipherError):
        load_key(material)


def test_a_key_file_may_carry_a_trailing_newline() -> None:
    # Editors add one, and a key that stopped working because of it would send
    # someone hunting through the cryptography instead of the file.
    key = load_key("00" * KEY_BYTES + "\n")

    assert len(key) == KEY_BYTES


def test_the_key_version_is_recorded_so_rotation_can_be_gradual() -> None:
    assert CURRENT_KEY_VERSION >= 1
