"""Utilities for Ethereum signature creation and verification."""

from __future__ import annotations

from web3 import Web3
from web3.auto import w3

from dydx3 import constants

PREPEND_DEC = '\x19Ethereum Signed Message:\n32'
PREPEND_HEX = '\x19Ethereum Signed Message:\n\x20'


def is_valid_sig_type(sig_type: int) -> bool:
    """Check whether the given signature type is supported."""
    return sig_type in [
        constants.SIGNATURE_TYPE_DECIMAL,
        constants.SIGNATURE_TYPE_HEXADECIMAL,
        constants.SIGNATURE_TYPE_NO_PREPEND,
    ]


def ec_recover_typed_signature(
    hash_val: bytes,
    typed_signature: str,
) -> str:
    """Recover the signer address from a typed EIP-712 signature."""
    if len(strip_hex_prefix(typed_signature)) != 66 * 2:
        raise ValueError(
            f'Unable to ecrecover signature: {typed_signature}'
        )

    sig_type = int(typed_signature[-2:], 16)
    prepended_hash: bytes = b''
    if sig_type == constants.SIGNATURE_TYPE_NO_PREPEND:
        prepended_hash = hash_val
    elif sig_type == constants.SIGNATURE_TYPE_DECIMAL:
        prepended_hash = Web3.solidityKeccak(
            ['string', 'bytes32'],
            [PREPEND_DEC, hash_val],
        )
    elif sig_type == constants.SIGNATURE_TYPE_HEXADECIMAL:
        prepended_hash = Web3.solidityKeccak(
            ['string', 'bytes32'],
            [PREPEND_HEX, hash_val],
        )
    else:
        raise ValueError(f'Invalid signature type: {sig_type}')

    if not prepended_hash:
        raise ValueError(f'Invalid hash: {hash_val}')

    signature = typed_signature[:-2]
    address: str = w3.eth.account.recoverHash(
        prepended_hash, signature=signature,
    )
    return address


def create_typed_signature(signature: str, sig_type: int) -> str:
    """Append a signature type byte to a raw signature."""
    if not is_valid_sig_type(sig_type):
        raise ValueError(f'Invalid signature type: {sig_type}')

    return f'{fix_raw_signature(signature)}0{sig_type}'


def fix_raw_signature(signature: str) -> str:
    """Normalize a raw Ethereum signature's v value."""
    stripped = strip_hex_prefix(signature)

    if len(stripped) != 130:
        raise ValueError(f'Invalid raw signature: {signature}')

    rs = stripped[:128]
    v = stripped[128:130]

    if v == '00':
        return f'0x{rs}1b'
    if v == '01':
        return f'0x{rs}1c'
    if v in ('1b', '1c'):
        return f'0x{stripped}'

    raise ValueError(f'Invalid v value: {v}')


# ============ Byte Helpers ============


def strip_hex_prefix(input_hex: str) -> str:
    """Remove a '0x' prefix from a hex string if present."""
    if input_hex.startswith('0x'):
        return input_hex[2:]
    return input_hex


def addresses_are_equal(
    address_one: str | None,
    address_two: str | None,
) -> bool:
    """Compare two Ethereum addresses case-insensitively."""
    if not address_one or not address_two:
        return False

    return (
        strip_hex_prefix(address_one).lower()
        == strip_hex_prefix(address_two).lower()
    )


def hash_string(input_str: str) -> bytes:
    """Compute the Keccak-256 hash of a string."""
    return Web3.solidityKeccak(['string'], [input_str])
