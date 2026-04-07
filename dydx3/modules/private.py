"""Private API module — requires API key authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Dict, Optional, Union

from dydx3.constants import COLLATERAL_ASSET
from dydx3.constants import COLLATERAL_TOKEN_DECIMALS
from dydx3.constants import FACT_REGISTRY_CONTRACT
from dydx3.constants import NETWORK_ID_SEPOLIA
from dydx3.constants import TIME_IN_FORCE_GTT
from dydx3.constants import TOKEN_CONTRACTS
from dydx3.helpers.db import get_account_id
from dydx3.helpers.request_helpers import epoch_seconds_to_iso
from dydx3.helpers.request_helpers import generate_now_iso
from dydx3.helpers.request_helpers import generate_query_path
from dydx3.helpers.request_helpers import random_client_id
from dydx3.helpers.request_helpers import iso_to_epoch_seconds
from dydx3.helpers.request_helpers import json_stringify
from dydx3.helpers.request_helpers import remove_nones
from dydx3.helpers.requests import Response, request
from dydx3.starkex.helpers import get_transfer_erc20_fact
from dydx3.starkex.helpers import nonce_from_client_id
from dydx3.starkex.order import SignableOrder
from dydx3.starkex.withdrawal import SignableWithdrawal
from dydx3.starkex.conditional_transfer import SignableConditionalTransfer
from dydx3.starkex.transfer import SignableTransfer


class Private:
    """Client module for private (API key authenticated) endpoints."""

    def __init__(
        self,
        host: str,
        network_id: int,
        stark_private_key: Optional[str],
        default_address: Optional[str],
        api_timeout: int,
        api_key_credentials: Dict[str, str],
    ) -> None:
        self.host = host
        self.network_id = network_id
        self.stark_private_key = stark_private_key
        self.default_address = default_address
        self.api_timeout = api_timeout
        self.api_key_credentials = api_key_credentials

    # ============ Request Helpers ============

    def _private_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Response:
        if data is None:
            data = {}
        now_iso_string = generate_now_iso()
        request_path = f'/v3/{endpoint}'
        signature = self.sign(
            request_path=request_path,
            method=method.upper(),
            iso_timestamp=now_iso_string,
            data=remove_nones(data),
        )
        headers = {
            'DYDX-SIGNATURE': signature,
            'DYDX-API-KEY': self.api_key_credentials['key'],
            'DYDX-TIMESTAMP': now_iso_string,
            'DYDX-PASSPHRASE': self.api_key_credentials['passphrase'],
        }
        return request(
            self.host + request_path,
            method,
            headers,
            data,
            self.api_timeout,
        )

    def _get(self, endpoint: str, params: Dict[str, Any]) -> Response:
        return self._private_request(
            'get',
            generate_query_path(endpoint, params),
        )

    def _post(self, endpoint: str, data: Dict[str, Any]) -> Response:
        return self._private_request('post', endpoint, data)

    def _put(self, endpoint: str, data: Dict[str, Any]) -> Response:
        return self._private_request('put', endpoint, data)

    def _delete(self, endpoint: str, params: Dict[str, Any]) -> Response:
        return self._private_request(
            'delete',
            generate_query_path(endpoint, params),
        )

    # ============ Requests ============

    def get_api_keys(self) -> Response:
        """Get API keys.

        :returns: Object containing an array of apiKeys.
        :raises: DydxAPIError
        """
        return self._get('api-keys', {})

    def get_registration(self) -> Response:
        """Get signature for registration.

        :returns: str
        :raises: DydxAPIError
        """
        return self._get('registration', {})

    def get_user(self) -> Response:
        """Get user information.

        :returns: User
        :raises: DydxAPIError
        """
        return self._get('users', {})

    def update_user(
        self,
        user_data: Optional[Dict[str, Any]] = None,
        email: Optional[str] = None,
        username: Optional[str] = None,
        is_sharing_username: Optional[bool] = None,
        is_sharing_address: Optional[bool] = None,
        country: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> Response:
        """Update user information.

        :param user_data: Optional user data dict.
        :param email: Optional email address.
        :param username: Optional username.
        :param is_sharing_username: Optional sharing preference.
        :param is_sharing_address: Optional sharing preference.
        :param country: Optional ISO 3166-1 Alpha-2 country code.
        :param language_code: Optional ISO 639-1 language code.
        :returns: User
        :raises: DydxAPIError
        """
        return self._put(
            'users',
            {
                'email': email,
                'username': username,
                'isSharingUsername': is_sharing_username,
                'isSharingAddress': is_sharing_address,
                'userData': json_stringify(user_data or {}),
                'country': country,
            },
        )

    def create_account(
        self,
        stark_public_key: str,
        stark_public_key_y_coordinate: str,
    ) -> Response:
        """Create an account.

        :param stark_public_key: STARK public key.
        :param stark_public_key_y_coordinate: STARK public key Y coordinate.
        :returns: Account
        :raises: DydxAPIError
        """
        return self._post(
            'accounts',
            {
                'starkKey': stark_public_key,
                'starkKeyYCoordinate': stark_public_key_y_coordinate,
            },
        )

    def get_account(
        self,
        ethereum_address: Optional[str] = None,
    ) -> Response:
        """Get an account.

        :param ethereum_address: Optional Ethereum address.
        :returns: Account
        :raises: DydxAPIError
        """
        address = ethereum_address or self.default_address
        if address is None:
            raise ValueError('ethereum_address was not set')
        return self._get(
            f'accounts/{get_account_id(address)}',
            {},
        )

    def get_accounts(self) -> Response:
        """Get all accounts for the user.

        :returns: Array of accounts.
        :raises: DydxAPIError
        """
        return self._get('accounts', {})

    def get_positions(
        self,
        market: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[str] = None,
        created_before_or_at: Optional[str] = None,
    ) -> Response:
        """Get positions.

        :param market: Optional market filter (e.g. "BTC-USD").
        :param status: Optional status filter ("OPEN", "CLOSED", "LIQUIDATED").
        :param limit: Optional max results.
        :param created_before_or_at: Optional ISO timestamp filter.
        :returns: Array of positions.
        :raises: DydxAPIError
        """
        return self._get(
            'positions',
            {
                'market': market,
                'limit': limit,
                'status': status,
                'createdBeforeOrAt': created_before_or_at,
            },
        )

    def get_orders(
        self,
        market: Optional[str] = None,
        status: Optional[str] = None,
        side: Optional[str] = None,
        order_type: Optional[str] = None,
        limit: Optional[str] = None,
        created_before_or_at: Optional[str] = None,
        return_latest_orders: Optional[bool] = None,
    ) -> Response:
        """Get orders.

        :param market: Optional market filter.
        :param status: Optional status filter.
        :param side: Optional side filter ("BUY" or "SELL").
        :param order_type: Optional type filter ("LIMIT", "STOP", etc.).
        :param limit: Optional max results.
        :param created_before_or_at: Optional ISO timestamp filter.
        :param return_latest_orders: Optional flag to return latest orders.
        :returns: Array of orders.
        :raises: DydxAPIError
        """
        return self._get(
            'orders',
            {
                'market': market,
                'status': status,
                'side': side,
                'type': order_type,
                'limit': limit,
                'createdBeforeOrAt': created_before_or_at,
                'returnLatestOrders': return_latest_orders,
            },
        )

    def get_active_orders(
        self,
        market: str,
        side: Optional[str] = None,
        id: Optional[str] = None,
    ) -> Response:
        """Get active orders.

        :param market: Market identifier.
        :param side: Optional side filter (required if id is passed).
        :param id: Optional order ID.
        :returns: Array of active orders.
        :raises: DydxAPIError
        """
        return self._get(
            'active-orders',
            {'market': market, 'side': side, 'id': id},
        )

    def get_order_by_id(self, order_id: str) -> Response:
        """Get an order by its ID.

        :param order_id: The order ID.
        :returns: Order
        :raises: DydxAPIError
        """
        return self._get(f'orders/{order_id}', {})

    def get_order_by_client_id(self, client_id: str) -> Response:
        """Get an order by its client ID.

        :param client_id: The client-assigned order ID.
        :returns: Order
        :raises: DydxAPIError
        """
        return self._get(f'orders/client/{client_id}', {})

    def create_order(
        self,
        position_id: Union[str, int],
        market: str,
        side: str,
        order_type: str,
        post_only: bool,
        size: str,
        price: str,
        limit_fee: str,
        time_in_force: Optional[str] = None,
        cancel_id: Optional[str] = None,
        trigger_price: Optional[str] = None,
        trailing_percent: Optional[str] = None,
        client_id: Optional[str] = None,
        expiration: Optional[str] = None,
        expiration_epoch_seconds: Optional[int] = None,
        signature: Optional[str] = None,
        reduce_only: Optional[bool] = None,
    ) -> Response:
        """Post an order.

        :param position_id: Position ID.
        :param market: Market (e.g. "BTC-USD").
        :param side: "BUY" or "SELL".
        :param order_type: "LIMIT", "STOP", "TRAILING_STOP", "TAKE_PROFIT".
        :param post_only: Whether the order is post-only.
        :param size: Order size.
        :param price: Order price.
        :param limit_fee: Maximum fee as a fraction (e.g. "0.01" for 1%).
        :param time_in_force: Optional ("GTT", "FOK", "IOC").
        :param cancel_id: Optional order ID to cancel.
        :param trigger_price: Optional trigger price.
        :param trailing_percent: Optional trailing percent.
        :param client_id: Optional client-assigned ID.
        :param expiration: Optional expiration as ISO string.
        :param expiration_epoch_seconds: Optional expiration as epoch seconds.
        :param signature: Optional pre-computed STARK signature.
        :param reduce_only: Optional reduce-only flag.
        :returns: Order
        :raises: DydxAPIError
        """
        client_id = client_id or random_client_id()
        if bool(expiration) == bool(expiration_epoch_seconds):
            raise ValueError(
                'Exactly one of expiration and expiration_epoch_seconds must '
                'be specified',
            )
        expiration = expiration or epoch_seconds_to_iso(
            expiration_epoch_seconds,
        )
        expiration_epoch_seconds = (
            expiration_epoch_seconds or iso_to_epoch_seconds(expiration)
        )

        order_signature = signature
        if not order_signature:
            if not self.stark_private_key:
                raise ValueError(
                    'No signature provided and client was not '
                    'initialized with stark_private_key'
                )
            order_to_sign = SignableOrder(
                network_id=self.network_id,
                position_id=position_id,
                client_id=client_id,
                market=market,
                side=side,
                human_size=size,
                human_price=price,
                limit_fee=limit_fee,
                expiration_epoch_seconds=expiration_epoch_seconds,
            )
            order_signature = order_to_sign.sign(self.stark_private_key)

        order = {
            'market': market,
            'side': side,
            'type': order_type,
            'timeInForce': time_in_force or TIME_IN_FORCE_GTT,
            'size': size,
            'price': price,
            'limitFee': limit_fee,
            'expiration': expiration,
            'cancelId': cancel_id,
            'triggerPrice': trigger_price,
            'trailingPercent': trailing_percent,
            'postOnly': post_only,
            'clientId': client_id,
            'signature': order_signature,
            'reduceOnly': reduce_only,
        }

        return self._post('orders', order)

    def cancel_order(self, order_id: str) -> Response:
        """Cancel an order.

        :param order_id: The order ID to cancel.
        :returns: Order
        :raises: DydxAPIError
        """
        return self._delete(f'orders/{order_id}', {})

    def cancel_all_orders(
        self,
        market: Optional[str] = None,
    ) -> Response:
        """Cancel all orders, optionally filtered by market.

        :param market: Optional market filter.
        :returns: Array of cancelled orders.
        :raises: DydxAPIError
        """
        params = {'market': market} if market else {}
        return self._delete('orders', params)

    def cancel_active_orders(
        self,
        market: str,
        side: Optional[str] = None,
        id: Optional[str] = None,
    ) -> Response:
        """Cancel active orders.

        :param market: Market identifier.
        :param side: Optional side filter (required if id is passed).
        :param id: Optional order ID.
        :returns: Array of cancelled active orders.
        :raises: DydxAPIError
        """
        return self._delete(
            'active-orders',
            {'market': market, 'side': side, 'id': id},
        )

    def get_fills(
        self,
        market: Optional[str] = None,
        order_id: Optional[str] = None,
        limit: Optional[str] = None,
        created_before_or_at: Optional[str] = None,
    ) -> Response:
        """Get fills.

        :param market: Optional market filter.
        :param order_id: Optional order ID filter.
        :param limit: Optional max results.
        :param created_before_or_at: Optional ISO timestamp filter.
        :returns: Array of fills.
        :raises: DydxAPIError
        """
        return self._get(
            'fills',
            {
                'market': market,
                'orderId': order_id,
                'limit': limit,
                'createdBeforeOrAt': created_before_or_at,
            },
        )

    def get_transfers(
        self,
        transfer_type: Optional[str] = None,
        limit: Optional[str] = None,
        created_before_or_at: Optional[str] = None,
    ) -> Response:
        """Get transfers.

        :param transfer_type: Optional type filter ("DEPOSIT", "WITHDRAWAL", etc.).
        :param limit: Optional max results.
        :param created_before_or_at: Optional ISO timestamp filter.
        :returns: Array of transfers.
        :raises: DydxAPIError
        """
        return self._get(
            'transfers',
            {
                'type': transfer_type,
                'limit': limit,
                'createdBeforeOrAt': created_before_or_at,
            },
        )

    def create_withdrawal(
        self,
        position_id: Union[str, int],
        amount: str,
        asset: str,
        to_address: str,
        client_id: Optional[str] = None,
        expiration: Optional[str] = None,
        expiration_epoch_seconds: Optional[int] = None,
        signature: Optional[str] = None,
    ) -> Response:
        """Post a withdrawal.

        :param position_id: Position ID.
        :param amount: Withdrawal amount.
        :param asset: Asset type (e.g. "USDC").
        :param to_address: Destination Ethereum address.
        :param client_id: Optional client-assigned ID.
        :param expiration: Optional expiration as ISO string.
        :param expiration_epoch_seconds: Optional expiration as epoch seconds.
        :param signature: Optional pre-computed STARK signature.
        :returns: Transfer
        :raises: DydxAPIError
        """
        client_id = client_id or random_client_id()
        if bool(expiration) == bool(expiration_epoch_seconds):
            raise ValueError(
                'Exactly one of expiration and expiration_epoch_seconds must '
                'be specified',
            )
        expiration = expiration or epoch_seconds_to_iso(
            expiration_epoch_seconds,
        )
        expiration_epoch_seconds = (
            expiration_epoch_seconds or iso_to_epoch_seconds(expiration)
        )

        if not signature:
            if not self.stark_private_key:
                raise ValueError(
                    'No signature provided and client was not '
                    'initialized with stark_private_key'
                )
            withdrawal_to_sign = SignableWithdrawal(
                network_id=self.network_id,
                position_id=position_id,
                client_id=client_id,
                human_amount=amount,
                expiration_epoch_seconds=expiration_epoch_seconds,
            )
            signature = withdrawal_to_sign.sign(self.stark_private_key)

        params = {
            'amount': amount,
            'asset': asset,
            'expiration': expiration,
            'clientId': client_id,
            'signature': signature,
        }
        return self._post('withdrawals', params)

    def create_transfer(
        self,
        amount: str,
        position_id: Union[str, int],
        receiver_account_id: str,
        receiver_public_key: str,
        receiver_position_id: Union[str, int],
        client_id: Optional[str] = None,
        expiration: Optional[str] = None,
        expiration_epoch_seconds: Optional[int] = None,
        signature: Optional[str] = None,
    ) -> Response:
        """Create a L2 transfer.

        :param amount: Transfer amount.
        :param position_id: Sender position ID.
        :param receiver_account_id: Receiver account ID.
        :param receiver_public_key: Receiver STARK public key.
        :param receiver_position_id: Receiver position ID.
        :param client_id: Optional client-assigned ID.
        :param expiration: Optional expiration as ISO string.
        :param expiration_epoch_seconds: Optional expiration as epoch seconds.
        :param signature: Optional pre-computed STARK signature.
        :returns: Transfer
        :raises: DydxAPIError
        """
        client_id = client_id or random_client_id()

        if bool(expiration) == bool(expiration_epoch_seconds):
            raise ValueError(
                'Exactly one of expiration and expiration_epoch_seconds must '
                'be specified',
            )
        expiration = expiration or epoch_seconds_to_iso(
            expiration_epoch_seconds,
        )
        expiration_epoch_seconds = (
            expiration_epoch_seconds or iso_to_epoch_seconds(expiration)
        )

        transfer_signature = signature
        if not transfer_signature:
            if not self.stark_private_key:
                raise ValueError(
                    'No signature provided and client was not '
                    'initialized with stark_private_key'
                )
            transfer_to_sign = SignableTransfer(
                network_id=self.network_id,
                sender_position_id=int(position_id),
                receiver_position_id=int(receiver_position_id),
                receiver_public_key=receiver_public_key,
                human_amount=amount,
                client_id=client_id,
                expiration_epoch_seconds=expiration_epoch_seconds,
            )
            transfer_signature = transfer_to_sign.sign(self.stark_private_key)

        params = {
            'amount': amount,
            'receiverAccountId': receiver_account_id,
            'clientId': client_id,
            'signature': transfer_signature,
            'expiration': expiration,
        }
        return self._post('transfers', params)

    def create_fast_withdrawal(
        self,
        position_id: Union[str, int],
        credit_asset: str,
        credit_amount: Union[str, int],
        debit_amount: Union[str, int],
        to_address: str,
        lp_position_id: Union[str, int],
        lp_stark_public_key: str,
        slippage_tolerance: Optional[str] = None,
        client_id: Optional[str] = None,
        expiration: Optional[str] = None,
        expiration_epoch_seconds: Optional[int] = None,
        signature: Optional[str] = None,
    ) -> Response:
        """Post a fast withdrawal.

        :param position_id: Position ID.
        :param credit_asset: Credit asset ("USDC" or "USDT").
        :param credit_amount: Credit amount.
        :param debit_amount: Debit amount.
        :param to_address: Destination Ethereum address.
        :param lp_position_id: LP position ID.
        :param lp_stark_public_key: LP STARK public key.
        :param slippage_tolerance: Optional slippage tolerance.
        :param client_id: Optional client-assigned ID.
        :param expiration: Optional expiration as ISO string.
        :param expiration_epoch_seconds: Optional expiration as epoch seconds.
        :param signature: Optional pre-computed STARK signature.
        :returns: Transfer
        :raises: DydxAPIError
        """
        client_id = client_id or random_client_id()
        if bool(expiration) == bool(expiration_epoch_seconds):
            raise ValueError(
                'Exactly one of expiration and expiration_epoch_seconds must '
                'be specified',
            )
        expiration = expiration or epoch_seconds_to_iso(
            expiration_epoch_seconds,
        )
        expiration_epoch_seconds = (
            expiration_epoch_seconds or iso_to_epoch_seconds(expiration)
        )

        if not signature:
            if not self.stark_private_key:
                raise ValueError(
                    'No signature provided and client was not '
                    'initialized with stark_private_key'
                )
            fact = get_transfer_erc20_fact(
                recipient=to_address,
                token_decimals=COLLATERAL_TOKEN_DECIMALS,
                human_amount=credit_amount,
                token_address=(
                    TOKEN_CONTRACTS[COLLATERAL_ASSET][self.network_id]
                ),
                salt=nonce_from_client_id(client_id),
            )
            transfer_to_sign = SignableConditionalTransfer(
                network_id=self.network_id,
                sender_position_id=position_id,
                receiver_position_id=lp_position_id,
                receiver_public_key=lp_stark_public_key,
                fact_registry_address=FACT_REGISTRY_CONTRACT[self.network_id],
                fact=fact,
                human_amount=debit_amount,
                client_id=client_id,
                expiration_epoch_seconds=expiration_epoch_seconds,
            )
            signature = transfer_to_sign.sign(self.stark_private_key)

        params = {
            'creditAsset': credit_asset,
            'creditAmount': credit_amount,
            'debitAmount': debit_amount,
            'slippageTolerance': slippage_tolerance,
            'toAddress': to_address.lower(),
            'lpPositionId': lp_position_id,
            'expiration': expiration,
            'clientId': client_id,
            'signature': signature,
        }
        return self._post('fast-withdrawals', params)

    def get_funding_payments(
        self,
        market: Optional[str] = None,
        limit: Optional[str] = None,
        effective_before_or_at: Optional[str] = None,
    ) -> Response:
        """Get funding payments.

        :param market: Optional market filter.
        :param limit: Optional max results.
        :param effective_before_or_at: Optional ISO timestamp filter.
        :returns: Array of funding payments.
        :raises: DydxAPIError
        """
        return self._get(
            'funding',
            {
                'market': market,
                'limit': limit,
                'effectiveBeforeOrAt': effective_before_or_at,
            },
        )

    def get_historical_pnl(
        self,
        created_before_or_at: Optional[str] = None,
        created_on_or_after: Optional[str] = None,
    ) -> Response:
        """Get historical PnL ticks.

        :param created_before_or_at: Optional ISO timestamp filter.
        :param created_on_or_after: Optional ISO timestamp filter.
        :returns: Array of historical PnL ticks.
        :raises: DydxAPIError
        """
        return self._get(
            'historical-pnl',
            {
                'createdBeforeOrAt': created_before_or_at,
                'createdOnOrAfter': created_on_or_after,
            },
        )

    def send_verification_email(self) -> Response:
        """Send verification email.

        :returns: Empty object.
        :raises: DydxAPIError
        """
        return self._put('emails/send-verification-email', {})

    def get_trading_rewards(
        self,
        epoch: Optional[int] = None,
    ) -> Response:
        """Get trading rewards.

        :param epoch: Optional epoch number.
        :returns: TradingRewards
        :raises: DydxAPIError
        """
        return self._get('rewards/weight', {'epoch': epoch})

    def get_liquidity_provider_rewards_v2(
        self,
        epoch: Optional[int] = None,
    ) -> Response:
        """Get liquidity provider rewards (v2).

        :param epoch: Optional epoch number.
        :returns: LiquidityProviderRewards
        :raises: DydxAPIError
        """
        return self._get('rewards/liquidity-provider', {'epoch': epoch})

    def get_liquidity_provider_rewards(
        self,
        epoch: Optional[int] = None,
    ) -> Response:
        """Get liquidity rewards (deprecated, use get_liquidity_provider_rewards_v2).

        :param epoch: Optional epoch number.
        :returns: LiquidityRewards
        :raises: DydxAPIError
        """
        return self._get('rewards/liquidity', {'epoch': epoch})

    def get_retroactive_mining_rewards(self) -> Response:
        """Get retroactive mining rewards.

        :returns: RetroactiveMiningRewards
        :raises: DydxAPIError
        """
        return self._get('rewards/retroactive-mining', {})

    def request_testnet_tokens(self) -> Response:
        """Request tokens on dYdX's staging server (Sepolia only).

        :returns: Transfer
        :raises: DydxAPIError, ValueError
        """
        if self.network_id != NETWORK_ID_SEPOLIA:
            raise ValueError('network_id is not Sepolia')
        return self._post('testnet/tokens', {})

    def get_profile(self) -> Response:
        """Get private profile.

        :returns: PrivateProfile
        :raises: DydxAPIError
        """
        return self._get('profile/private', {})

    def get_user_links(self) -> Response:
        """Get active linked users.

        :returns: UserLinks
        :raises: DydxAPIError
        """
        return self._get('users/links', {})

    def send_link_request(
        self,
        action: str,
        address: str,
    ) -> Response:
        """Send a link request action.

        :param action: Link action type.
        :param address: Target Ethereum address.
        :returns: Empty object.
        :raises: DydxAPIError
        """
        return self._post(
            'users/links',
            {'action': action, 'address': address},
        )

    def get_user_pending_link_requests(self) -> Response:
        """Get pending linked user requests.

        :returns: UserLinkRequests
        :raises: DydxAPIError
        """
        return self._get('users/links/requests', {})

    # ============ Signing ============

    def sign(
        self,
        request_path: str,
        method: str,
        iso_timestamp: str,
        data: Dict[str, Any],
    ) -> str:
        """Sign a private API request using HMAC-SHA256."""
        message_string = (
            iso_timestamp
            + method
            + request_path
            + (json_stringify(data) if data else '')
        )

        hashed = hmac.new(
            base64.urlsafe_b64decode(
                self.api_key_credentials['secret'].encode('utf-8'),
            ),
            msg=message_string.encode('utf-8'),
            digestmod=hashlib.sha256,
        )
        return base64.urlsafe_b64encode(hashed.digest()).decode()
