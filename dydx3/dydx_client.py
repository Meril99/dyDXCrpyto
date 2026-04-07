"""Main dYdX client — entry point for all API interactions."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from web3 import Web3

from dydx3.constants import DEFAULT_API_TIMEOUT, NETWORK_ID_MAINNET
from dydx3.eth_signing import SignWithWeb3
from dydx3.eth_signing import SignWithKey
from dydx3.modules.eth_private import EthPrivate
from dydx3.modules.eth import Eth
from dydx3.modules.private import Private
from dydx3.modules.public import Public
from dydx3.modules.onboarding import Onboarding
from dydx3.starkex.helpers import private_key_to_public_key_pair_hex
from dydx3.starkex.starkex_resources.cpp_signature import get_cpp_lib

logger = logging.getLogger(__name__)


class Client:
    """Client for interacting with the dYdX v3 API.

    Provides access to public endpoints, private endpoints (with API key auth),
    Ethereum-signed endpoints, and on-chain interactions.
    """

    def __init__(
        self,
        host: str,
        api_timeout: Optional[int] = None,
        default_ethereum_address: Optional[str] = None,
        eth_private_key: Optional[str] = None,
        eth_send_options: Optional[Dict[str, Any]] = None,
        network_id: Optional[int] = None,
        stark_private_key: Optional[str] = None,
        stark_public_key: Optional[str] = None,
        stark_public_key_y_coordinate: Optional[str] = None,
        web3: Optional[Web3] = None,
        web3_account: Optional[Any] = None,
        web3_provider: Optional[Any] = None,
        api_key_credentials: Optional[Dict[str, str]] = None,
        crypto_c_exports_path: Optional[str] = None,
    ) -> None:
        # Remove trailing '/' if present, from host.
        if host.endswith('/'):
            host = host[:-1]

        self.host = host
        self.api_timeout = api_timeout or DEFAULT_API_TIMEOUT
        self.eth_send_options = eth_send_options or {}
        self.stark_private_key = stark_private_key
        self.api_key_credentials = api_key_credentials
        self.stark_public_key_y_coordinate = stark_public_key_y_coordinate

        self.web3: Optional[Web3] = None
        self.eth_signer: Optional[Any] = None
        self.default_address: Optional[str] = None
        self.network_id: int = NETWORK_ID_MAINNET

        if crypto_c_exports_path is not None:
            get_cpp_lib(crypto_c_exports_path)

        if web3 is not None or web3_provider is not None:
            if isinstance(web3_provider, str):
                web3_provider = Web3.HTTPProvider(
                    web3_provider,
                    request_kwargs={'timeout': self.api_timeout},
                )
            self.web3 = web3 or Web3(web3_provider)
            self.eth_signer = SignWithWeb3(self.web3)
            self.default_address = self.web3.eth.defaultAccount or None
            self.network_id = int(self.web3.net.version)

        if eth_private_key is not None or web3_account is not None:
            # May override web3 or web3_provider configuration.
            key = eth_private_key or web3_account.key
            self.eth_signer = SignWithKey(key)
            self.default_address = self.eth_signer.address

        self.default_address = default_ethereum_address or self.default_address
        self.network_id = int(
            network_id or self.network_id or NETWORK_ID_MAINNET
        )

        # Initialize the public module. Other modules are initialized on
        # demand, if the necessary configuration options were provided.
        self._public = Public(host)
        self._private: Optional[Private] = None
        self._eth_private: Optional[EthPrivate] = None
        self._eth: Optional[Eth] = None
        self._onboarding: Optional[Onboarding] = None

        # Derive the public keys.
        if stark_private_key is not None:
            self.stark_public_key, self.stark_public_key_y_coordinate = (
                private_key_to_public_key_pair_hex(stark_private_key)
            )
            if (
                stark_public_key is not None
                and stark_public_key != self.stark_public_key
            ):
                raise ValueError('STARK public/private key mismatch')
            if (
                stark_public_key_y_coordinate is not None
                and stark_public_key_y_coordinate
                != self.stark_public_key_y_coordinate
            ):
                raise ValueError('STARK public/private key mismatch (y)')
        else:
            self.stark_public_key = stark_public_key
            self.stark_public_key_y_coordinate = stark_public_key_y_coordinate

        # Generate default API key credentials if needed and possible.
        if (
            self.eth_signer
            and self.default_address
            and not self.api_key_credentials
        ):
            try:
                self.api_key_credentials = (
                    self.onboarding.recover_default_api_key_credentials(
                        ethereum_address=self.default_address,
                    )
                )
            except Exception as e:
                logger.warning(
                    'Failed to derive default API key credentials: %s', e,
                )

    @property
    def public(self) -> Public:
        """Get the public module for unauthenticated endpoints."""
        return self._public

    @property
    def private(self) -> Private:
        """Get the private module for API-key authenticated endpoints."""
        if not self._private:
            if self.api_key_credentials:
                self._private = Private(
                    host=self.host,
                    network_id=self.network_id,
                    stark_private_key=self.stark_private_key,
                    default_address=self.default_address,
                    api_timeout=self.api_timeout,
                    api_key_credentials=self.api_key_credentials,
                )
            else:
                raise ValueError(
                    'Private endpoints not supported '
                    'since api_key_credentials were not specified'
                )
        return self._private

    @property
    def eth_private(self) -> EthPrivate:
        """Get the eth_private module for Ethereum-key authenticated endpoints."""
        if not self._eth_private:
            if self.eth_signer:
                self._eth_private = EthPrivate(
                    host=self.host,
                    eth_signer=self.eth_signer,
                    network_id=self.network_id,
                    default_address=self.default_address,
                    api_timeout=self.api_timeout,
                )
            else:
                raise ValueError(
                    'Eth private module is not supported since no Ethereum '
                    'signing method (web3, web3_account, web3_provider) was '
                    'provided'
                )
        return self._eth_private

    @property
    def onboarding(self) -> Onboarding:
        """Get the onboarding module for creating new users."""
        if not self._onboarding:
            if self.eth_signer:
                self._onboarding = Onboarding(
                    host=self.host,
                    eth_signer=self.eth_signer,
                    network_id=self.network_id,
                    default_address=self.default_address,
                    api_timeout=self.api_timeout,
                    stark_public_key=self.stark_public_key,
                    stark_public_key_y_coordinate=(
                        self.stark_public_key_y_coordinate
                    ),
                )
            else:
                raise ValueError(
                    'Onboarding is not supported since no Ethereum '
                    'signing method (web3, web3_account, web3_provider) was '
                    'provided'
                )
        return self._onboarding

    @property
    def eth(self) -> Eth:
        """Get the eth module for Ethereum smart contract interactions."""
        if not self._eth:
            eth_private_key = getattr(self.eth_signer, '_private_key', None)
            if self.web3 and eth_private_key:
                self._eth = Eth(
                    web3=self.web3,
                    network_id=self.network_id,
                    eth_private_key=eth_private_key,
                    default_address=self.default_address,
                    stark_public_key=self.stark_public_key,
                    send_options=self.eth_send_options,
                )
            else:
                raise ValueError(
                    'Eth module is not supported since neither web3 '
                    'nor web3_provider was provided OR since neither '
                    'eth_private_key nor web3_account was provided'
                )
        return self._eth
