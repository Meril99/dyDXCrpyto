"""Ethereum smart contract interaction module."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from web3 import Web3

from dydx3.constants import ASSET_RESOLUTION
from dydx3.constants import COLLATERAL_ASSET
from dydx3.constants import COLLATERAL_ASSET_ID_BY_NETWORK_ID
from dydx3.constants import DEFAULT_GAS_AMOUNT
from dydx3.constants import DEFAULT_GAS_MULTIPLIER
from dydx3.constants import DEFAULT_GAS_PRICE
from dydx3.constants import DEFAULT_GAS_PRICE_ADDITION
from dydx3.constants import MAX_SOLIDITY_UINT
from dydx3.constants import STARKWARE_PERPETUALS_CONTRACT
from dydx3.constants import TOKEN_CONTRACTS
from dydx3.errors import TransactionReverted

ERC20_ABI = 'abi/erc20.json'
STARKWARE_PERPETUALS_ABI = 'abi/starkware-perpetuals.json'
COLLATERAL_ASSET_RESOLUTION = float(ASSET_RESOLUTION[COLLATERAL_ASSET])


class Eth:
    """Module for interacting with Ethereum smart contracts."""

    def __init__(
        self,
        web3: Web3,
        network_id: int,
        eth_private_key: str,
        default_address: Optional[str],
        stark_public_key: Optional[str],
        send_options: Dict[str, Any],
    ) -> None:
        self.web3 = web3
        self.network_id = network_id
        self.eth_private_key = eth_private_key
        self.default_address = default_address
        self.stark_public_key = stark_public_key
        self.send_options = send_options

        self.cached_contracts: Dict[str, Any] = {}
        self._next_nonce_for_address: Dict[str, int] = {}

    # -----------------------------------------------------------
    # Helper Functions
    # -----------------------------------------------------------

    def create_contract(self, address: str, file_path: str) -> Any:
        """Create a web3 contract instance from an ABI file."""
        dydx_folder = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..',
        )
        abi_path = os.path.join(dydx_folder, file_path)
        with open(abi_path) as f:
            abi = json.load(f)
        return self.web3.eth.contract(address=address, abi=abi)

    def get_contract(self, address: str, file_path: str) -> Any:
        """Get a cached contract instance, creating it if needed."""
        if address not in self.cached_contracts:
            self.cached_contracts[address] = self.create_contract(
                address, file_path,
            )
        return self.cached_contracts[address]

    def get_exchange_contract(
        self,
        contract_address: Optional[str] = None,
    ) -> Any:
        """Get the Starkware perpetuals exchange contract."""
        if contract_address is None:
            contract_address = STARKWARE_PERPETUALS_CONTRACT.get(
                self.network_id,
            )
        if contract_address is None:
            raise ValueError(
                f'Perpetuals exchange contract on network {self.network_id}'
            )
        contract_address = Web3.toChecksumAddress(contract_address)
        return self.get_contract(contract_address, STARKWARE_PERPETUALS_ABI)

    def get_token_contract(
        self,
        asset: str,
        token_address: Optional[str],
    ) -> Any:
        """Get the ERC-20 token contract for an asset."""
        if token_address is None:
            token_address = TOKEN_CONTRACTS.get(asset, {}).get(self.network_id)
        if token_address is None:
            raise ValueError(
                f'Token address unknown for asset {asset} '
                f'on network {self.network_id}'
            )
        token_address = Web3.toChecksumAddress(token_address)
        return self.get_contract(token_address, ERC20_ABI)

    def send_eth_transaction(
        self,
        method: Optional[Any] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build, sign, and send an Ethereum transaction."""
        options = dict(self.send_options, **(options or {}))

        if 'from' not in options:
            options['from'] = self.default_address
        if options.get('from') is None:
            raise ValueError(
                "options['from'] is not set, and no default address is set",
            )
        auto_detect_nonce = 'nonce' not in options
        if auto_detect_nonce:
            options['nonce'] = self.get_next_nonce(options['from'])
        if 'gasPrice' not in options:
            try:
                options['gasPrice'] = (
                    self.web3.eth.gasPrice + DEFAULT_GAS_PRICE_ADDITION
                )
            except Exception:
                options['gasPrice'] = DEFAULT_GAS_PRICE
        if 'value' not in options:
            options['value'] = 0
        gas_multiplier = options.pop('gasMultiplier', DEFAULT_GAS_MULTIPLIER)
        if 'gas' not in options:
            try:
                options['gas'] = int(
                    method.estimateGas(options) * gas_multiplier
                )
            except Exception:
                options['gas'] = DEFAULT_GAS_AMOUNT

        signed = self.sign_tx(method, options)
        try:
            tx_hash = self.web3.eth.sendRawTransaction(signed.rawTransaction)
        except ValueError as error:
            while (
                auto_detect_nonce
                and (
                    'nonce too low' in str(error)
                    or 'replacement transaction underpriced' in str(error)
                )
            ):
                try:
                    options['nonce'] += 1
                    signed = self.sign_tx(method, options)
                    tx_hash = self.web3.eth.sendRawTransaction(
                        signed.rawTransaction,
                    )
                except ValueError as inner_error:
                    error = inner_error
                else:
                    break
            else:
                raise error

        # Update next nonce for the account.
        self._next_nonce_for_address[options['from']] = options['nonce'] + 1

        return tx_hash.hex()

    def get_next_nonce(self, ethereum_address: str) -> int:
        """Get the next nonce for a given address, auto-detecting if needed."""
        if self._next_nonce_for_address.get(ethereum_address) is None:
            self._next_nonce_for_address[ethereum_address] = (
                self.web3.eth.getTransactionCount(ethereum_address)
            )
        return self._next_nonce_for_address[ethereum_address]

    def sign_tx(
        self,
        method: Optional[Any],
        options: Dict[str, Any],
    ) -> Any:
        """Sign a transaction using the Ethereum private key."""
        if method is None:
            tx = options
        else:
            tx = method.buildTransaction(options)
        return self.web3.eth.account.sign_transaction(
            tx, self.eth_private_key,
        )

    def wait_for_tx(self, tx_hash: str) -> None:
        """Wait for a transaction to be mined and raise on revert.

        :param tx_hash: Transaction hash.
        :raises: TransactionReverted
        """
        tx_receipt = self.web3.eth.waitForTransactionReceipt(tx_hash)
        if tx_receipt['status'] == 0:
            raise TransactionReverted(tx_receipt)

    # -----------------------------------------------------------
    # Transactions
    # -----------------------------------------------------------

    def register_user(
        self,
        registration_signature: str,
        stark_public_key: Optional[str] = None,
        ethereum_address: Optional[str] = None,
        send_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a STARK key using a signature provided by dYdX.

        :param registration_signature: Registration signature from dYdX.
        :param stark_public_key: Optional STARK public key override.
        :param ethereum_address: Optional Ethereum address override.
        :param send_options: Optional transaction options.
        :returns: Transaction hash.
        :raises: ValueError
        """
        stark_public_key = stark_public_key or self.stark_public_key
        if stark_public_key is None:
            raise ValueError('No stark_public_key was provided')

        ethereum_address = ethereum_address or self.default_address
        if ethereum_address is None:
            raise ValueError(
                'ethereum_address was not provided, '
                'and no default address is set',
            )

        contract = self.get_exchange_contract()
        return self.send_eth_transaction(
            method=contract.functions.registerUser(
                ethereum_address,
                int(stark_public_key, 16),
                registration_signature,
            ),
            options=send_options,
        )

    def deposit_to_exchange(
        self,
        position_id: int | str,
        human_amount: float | str,
        stark_public_key: Optional[str] = None,
        send_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Deposit collateral to the L2 perpetuals exchange.

        :param position_id: Position ID.
        :param human_amount: Amount in human-readable units.
        :param stark_public_key: Optional STARK public key override.
        :param send_options: Optional transaction options.
        :returns: Transaction hash.
        :raises: ValueError
        """
        stark_public_key = stark_public_key or self.stark_public_key
        if stark_public_key is None:
            raise ValueError('No stark_public_key was provided')

        contract = self.get_exchange_contract()
        return self.send_eth_transaction(
            method=contract.functions.deposit(
                int(stark_public_key, 16),
                COLLATERAL_ASSET_ID_BY_NETWORK_ID[self.network_id],
                int(position_id),
                int(float(human_amount) * COLLATERAL_ASSET_RESOLUTION),
            ),
            options=send_options,
        )

    def withdraw(
        self,
        stark_public_key: Optional[str] = None,
        send_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Withdraw from exchange.

        :param stark_public_key: Optional STARK public key override.
        :param send_options: Optional transaction options.
        :returns: Transaction hash.
        :raises: ValueError
        """
        stark_public_key = stark_public_key or self.stark_public_key
        if stark_public_key is None:
            raise ValueError('No stark_public_key was provided')

        contract = self.get_exchange_contract()
        return self.send_eth_transaction(
            method=contract.functions.withdraw(
                int(stark_public_key, 16),
                COLLATERAL_ASSET_ID_BY_NETWORK_ID[self.network_id],
            ),
            options=send_options,
        )

    def withdraw_to(
        self,
        recipient: str,
        stark_public_key: Optional[str] = None,
        send_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Withdraw from exchange to a specific address.

        :param recipient: Destination Ethereum address.
        :param stark_public_key: Optional STARK public key override.
        :param send_options: Optional transaction options.
        :returns: Transaction hash.
        :raises: ValueError
        """
        stark_public_key = stark_public_key or self.stark_public_key
        if stark_public_key is None:
            raise ValueError('No stark_public_key was provided')

        contract = self.get_exchange_contract()
        return self.send_eth_transaction(
            method=contract.functions.withdrawTo(
                int(stark_public_key, 16),
                COLLATERAL_ASSET_ID_BY_NETWORK_ID[self.network_id],
                recipient,
            ),
            options=send_options,
        )

    def transfer_eth(
        self,
        to_address: Optional[str] = None,
        human_amount: Optional[str | float] = None,
        send_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send Ethereum.

        :param to_address: Destination address.
        :param human_amount: Amount in ETH.
        :param send_options: Optional transaction options.
        :returns: Transaction hash.
        :raises: ValueError
        """
        if to_address is None:
            raise ValueError('to_address is required')
        if human_amount is None:
            raise ValueError('human_amount is required')

        return self.send_eth_transaction(
            options=dict(
                send_options or {},
                to=to_address,
                value=Web3.toWei(human_amount, 'ether'),
            ),
        )

    def transfer_token(
        self,
        to_address: Optional[str] = None,
        human_amount: Optional[str | float] = None,
        asset: str = COLLATERAL_ASSET,
        token_address: Optional[str] = None,
        send_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send an ERC-20 token.

        :param to_address: Destination address.
        :param human_amount: Amount in human-readable units.
        :param asset: Asset identifier.
        :param token_address: Optional token contract address override.
        :param send_options: Optional transaction options.
        :returns: Transaction hash.
        :raises: ValueError
        """
        if to_address is None:
            raise ValueError('to_address is required')
        if human_amount is None:
            raise ValueError('human_amount is required')
        if asset not in ASSET_RESOLUTION:
            raise ValueError(f'Unknown asset {asset}')

        asset_resolution = ASSET_RESOLUTION[asset]
        contract = self.get_token_contract(asset, token_address)
        return self.send_eth_transaction(
            method=contract.functions.transfer(
                to_address,
                int(float(human_amount) * float(asset_resolution)),
            ),
            options=send_options,
        )

    def set_token_max_allowance(
        self,
        spender: str,
        asset: str = COLLATERAL_ASSET,
        token_address: Optional[str] = None,
        send_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Set max allowance for a spender on an ERC-20 token.

        :param spender: Spender address.
        :param asset: Asset identifier.
        :param token_address: Optional token contract address override.
        :param send_options: Optional transaction options.
        :returns: Transaction hash.
        :raises: ValueError
        """
        contract = self.get_token_contract(asset, token_address)
        return self.send_eth_transaction(
            method=contract.functions.approve(spender, MAX_SOLIDITY_UINT),
            options=send_options,
        )

    # -----------------------------------------------------------
    # Getters
    # -----------------------------------------------------------

    def get_eth_balance(self, owner: Optional[str] = None) -> Any:
        """Get the owner's ETH balance in human-readable units.

        :param owner: Optional address override.
        :returns: Balance in ETH.
        :raises: ValueError
        """
        owner = owner or self.default_address
        if owner is None:
            raise ValueError(
                'owner was not provided, and no default address is set',
            )

        wei_balance = self.web3.eth.getBalance(owner)
        return Web3.fromWei(wei_balance, 'ether')

    def get_token_balance(
        self,
        owner: Optional[str] = None,
        asset: str = COLLATERAL_ASSET,
        token_address: Optional[str] = None,
    ) -> int:
        """Get the owner's token balance.

        :param owner: Optional address override.
        :param asset: Asset identifier.
        :param token_address: Optional token contract address override.
        :returns: Token balance in base units.
        """
        owner = owner or self.default_address
        if owner is None:
            raise ValueError(
                'owner was not provided, and no default address is set',
            )

        contract = self.get_token_contract(asset, token_address)
        return contract.functions.balanceOf(owner).call()

    def get_token_allowance(
        self,
        spender: str,
        owner: Optional[str] = None,
        asset: str = COLLATERAL_ASSET,
        token_address: Optional[str] = None,
    ) -> int:
        """Get the token allowance for a spender.

        :param spender: Spender address.
        :param owner: Optional owner address override.
        :param asset: Asset identifier.
        :param token_address: Optional token contract address override.
        :returns: Allowance in base units.
        :raises: ValueError
        """
        owner = owner or self.default_address
        if owner is None:
            raise ValueError(
                'owner was not provided, and no default address is set',
            )

        contract = self.get_token_contract(asset, token_address)
        return contract.functions.allowance(owner, spender).call()
