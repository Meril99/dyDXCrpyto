"""Ethereum signing implementations using Web3 or a raw private key."""

from __future__ import annotations

from typing import Any, Dict, Optional

import eth_account

from dydx3.constants import SIGNATURE_TYPE_NO_PREPEND
from dydx3.eth_signing import util


class Signer:
    """Base class for Ethereum signers."""

    def sign(
        self,
        eip712_message: Dict[str, Any],
        message_hash: bytes,
        opt_signer_address: Optional[str],
    ) -> str:
        """Sign an EIP-712 message and return a typed signature.

        :param eip712_message: The structured EIP-712 message.
        :param message_hash: The hash of the message.
        :param opt_signer_address: Optional signer address override.
        :returns: Typed signature string.
        """
        raise NotImplementedError()


class SignWithWeb3(Signer):
    """Sign messages using a Web3 provider (e.g. MetaMask, hardware wallet)."""

    def __init__(self, web3: Any) -> None:
        self.web3 = web3

    def sign(
        self,
        eip712_message: Dict[str, Any],
        message_hash: bytes,  # Ignored when signing via Web3.
        opt_signer_address: Optional[str],
    ) -> str:
        signer_address = opt_signer_address or self.web3.eth.defaultAccount
        if not signer_address:
            raise ValueError(
                'Must set ethereum_address or web3.eth.defaultAccount',
            )
        raw_signature = self.web3.eth.signTypedData(
            signer_address,
            eip712_message,
        )
        return util.create_typed_signature(
            raw_signature.hex(),
            SIGNATURE_TYPE_NO_PREPEND,
        )


class SignWithKey(Signer):
    """Sign messages using a raw Ethereum private key."""

    def __init__(self, private_key: str) -> None:
        self.address: str = eth_account.Account.from_key(private_key).address
        self._private_key = private_key

    def sign(
        self,
        eip712_message: Dict[str, Any],  # Ignored when signing with key.
        message_hash: bytes,
        opt_signer_address: Optional[str],
    ) -> str:
        if (
            opt_signer_address is not None
            and opt_signer_address != self.address
        ):
            raise ValueError(
                f'signer_address is {opt_signer_address} but Ethereum key '
                f'(eth_private_key / web3_account) corresponds to address '
                f'{self.address}',
            )
        signed_message = eth_account.Account._sign_hash(
            message_hash.hex(),
            self._private_key,
        )
        return util.create_typed_signature(
            signed_message.signature.hex(),
            SIGNATURE_TYPE_NO_PREPEND,
        )
