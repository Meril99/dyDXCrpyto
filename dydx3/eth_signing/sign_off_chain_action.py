"""Base class for signing off-chain actions using EIP-712 typed data."""

from __future__ import annotations

from typing import Any, Dict, List

from web3 import Web3

from dydx3.eth_signing import util

DOMAIN = 'dYdX'
VERSION = '1.0'
EIP712_DOMAIN_STRING_NO_CONTRACT = (
    'EIP712Domain('
    'string name,'
    'string version,'
    'uint256 chainId'
    ')'
)


class SignOffChainAction:
    """Base class for off-chain EIP-712 message signing."""

    def __init__(self, signer: Any, network_id: int) -> None:
        self.signer = signer
        self.network_id = network_id

    def get_hash(self, **message: Any) -> bytes:
        """Compute the hash of the off-chain action message."""
        raise NotImplementedError

    def get_eip712_struct(self) -> List[Dict[str, str]]:
        """Return the EIP-712 type struct for this action."""
        raise NotImplementedError

    def get_eip712_struct_name(self) -> str:
        """Return the EIP-712 struct name for this action."""
        raise NotImplementedError

    def sign(
        self,
        signer_address: str,
        **message: Any,
    ) -> str:
        """Sign the off-chain action and return a typed signature."""
        eip712_message = self.get_eip712_message(**message)
        message_hash = self.get_hash(**message)
        return self.signer.sign(
            eip712_message,
            message_hash,
            signer_address,
        )

    def verify(
        self,
        typed_signature: str,
        expected_signer_address: str,
        **message: Any,
    ) -> bool:
        """Verify that a typed signature was signed by the expected address."""
        message_hash = self.get_hash(**message)
        signer = util.ec_recover_typed_signature(message_hash, typed_signature)
        return util.addresses_are_equal(signer, expected_signer_address)

    def get_eip712_message(
        self,
        **message: Any,
    ) -> Dict[str, Any]:
        """Construct the full EIP-712 typed data message."""
        struct_name = self.get_eip712_struct_name()
        return {
            'types': {
                'EIP712Domain': [
                    {'name': 'name', 'type': 'string'},
                    {'name': 'version', 'type': 'string'},
                    {'name': 'chainId', 'type': 'uint256'},
                ],
                struct_name: self.get_eip712_struct(),
            },
            'domain': {
                'name': DOMAIN,
                'version': VERSION,
                'chainId': self.network_id,
            },
            'primaryType': struct_name,
            'message': message,
        }

    def get_eip712_hash(self, struct_hash: bytes) -> bytes:
        """Compute the final EIP-712 hash from the struct hash."""
        return Web3.solidityKeccak(
            ['bytes2', 'bytes32', 'bytes32'],
            ['0x1901', self.get_domain_hash(), struct_hash],
        )

    def get_domain_hash(self) -> bytes:
        """Compute the EIP-712 domain separator hash."""
        return Web3.solidityKeccak(
            ['bytes32', 'bytes32', 'bytes32', 'uint256'],
            [
                util.hash_string(EIP712_DOMAIN_STRING_NO_CONTRACT),
                util.hash_string(DOMAIN),
                util.hash_string(VERSION),
                self.network_id,
            ],
        )
