"""Public API module — no authentication required."""

from __future__ import annotations

from typing import Any, Dict, Optional

from dydx3.constants import DEFAULT_API_TIMEOUT
from dydx3.helpers.request_helpers import generate_query_path
from dydx3.helpers.requests import Response, request


class Public:
    """Client module for public (unauthenticated) API endpoints."""

    def __init__(
        self,
        host: str,
        api_timeout: Optional[int] = None,
    ) -> None:
        self.host = host
        self.api_timeout = api_timeout or DEFAULT_API_TIMEOUT

    # ============ Request Helpers ============

    def _get(
        self,
        request_path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Response:
        return request(
            generate_query_path(self.host + request_path, params or {}),
            'get',
            api_timeout=self.api_timeout,
        )

    def _put(self, endpoint: str, data: Dict[str, Any]) -> Response:
        return request(
            f'{self.host}/v3/{endpoint}',
            'put',
            {},
            data,
            self.api_timeout,
        )

    # ============ Requests ============

    def check_if_user_exists(self, ethereum_address: str) -> Response:
        """Check if a user exists by Ethereum address.

        :param ethereum_address: The Ethereum address to check.
        :returns: Bool
        :raises: DydxAPIError
        """
        return self._get(
            '/v3/users/exists',
            {'ethereumAddress': ethereum_address},
        )

    def check_if_username_exists(self, username: str) -> Response:
        """Check if a username exists.

        :param username: The username to check.
        :returns: Bool
        :raises: DydxAPIError
        """
        return self._get('/v3/usernames', {'username': username})

    def get_markets(self, market: Optional[str] = None) -> Response:
        """Get one or more markets.

        :param market: Optional market identifier (e.g. "BTC-USD").
        :returns: Market array
        :raises: DydxAPIError
        """
        return self._get('/v3/markets', {'market': market})

    def get_orderbook(self, market: str) -> Response:
        """Get the orderbook for a market.

        :param market: Market identifier (e.g. "BTC-USD").
        :returns: Object containing bid and ask arrays.
        :raises: DydxAPIError
        """
        return self._get(f'/v3/orderbook/{market}')

    def get_stats(
        self,
        market: Optional[str] = None,
        days: Optional[str] = None,
    ) -> Response:
        """Get statistics for a market.

        :param market: Optional market identifier.
        :param days: Optional period — "1", "7", or "30".
        :returns: Statistic information for a market.
        :raises: DydxAPIError
        """
        uri = f'/v3/stats/{market}' if market is not None else '/v3/stats'
        return self._get(uri, {'days': days})

    def get_trades(
        self,
        market: str,
        starting_before_or_at: Optional[str] = None,
    ) -> Response:
        """Get trades for a market.

        :param market: Market identifier (e.g. "BTC-USD").
        :param starting_before_or_at: Optional ISO timestamp filter.
        :returns: Trade array
        :raises: DydxAPIError
        """
        return self._get(
            f'/v3/trades/{market}',
            {'startingBeforeOrAt': starting_before_or_at},
        )

    def get_historical_funding(
        self,
        market: str,
        effective_before_or_at: Optional[str] = None,
    ) -> Response:
        """Get historical funding for a market.

        :param market: Market identifier (e.g. "BTC-USD").
        :param effective_before_or_at: Optional ISO timestamp filter.
        :returns: Array of historical funding.
        :raises: DydxAPIError
        """
        return self._get(
            f'/v3/historical-funding/{market}',
            {'effectiveBeforeOrAt': effective_before_or_at},
        )

    def get_fast_withdrawal(
        self,
        credit_asset: Optional[str] = None,
        credit_amount: Optional[str] = None,
        debit_amount: Optional[str] = None,
    ) -> Response:
        """Get all fast withdrawal account information.

        :param credit_asset: Optional credit asset filter.
        :param credit_amount: Optional credit amount filter.
        :param debit_amount: Optional debit amount filter.
        :returns: All fast withdrawal accounts.
        :raises: DydxAPIError
        """
        return self._get(
            '/v3/fast-withdrawals',
            {
                'creditAsset': credit_asset,
                'creditAmount': credit_amount,
                'debitAmount': debit_amount,
            },
        )

    def get_candles(
        self,
        market: str,
        resolution: Optional[str] = None,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[str] = None,
    ) -> Response:
        """Get candles for a market.

        :param market: Market identifier (e.g. "BTC-USD").
        :param resolution: Candle resolution (e.g. "1HOUR", "1DAY").
        :param from_iso: Optional start time as ISO string.
        :param to_iso: Optional end time as ISO string.
        :param limit: Optional max number of candles.
        :returns: Array of candles.
        :raises: DydxAPIError
        """
        return self._get(
            f'/v3/candles/{market}',
            {
                'resolution': resolution,
                'fromISO': from_iso,
                'toISO': to_iso,
                'limit': limit,
            },
        )

    def get_time(self) -> Response:
        """Get API server time as ISO and epoch seconds.

        :returns: ISO string and epoch number of server time.
        :raises: DydxAPIError
        """
        return self._get('/v3/time')

    def verify_email(self, token: str) -> Response:
        """Verify email with token.

        :param token: Verification token.
        :returns: Empty object.
        :raises: DydxAPIError
        """
        return self._put('emails/verify-email', {'token': token})

    def get_public_retroactive_mining_rewards(
        self,
        ethereum_address: str,
    ) -> Response:
        """Get public retroactive mining rewards.

        :param ethereum_address: Ethereum address to query.
        :returns: PublicRetroactiveMiningRewards
        :raises: DydxAPIError
        """
        return self._get(
            '/v3/rewards/public-retroactive-mining',
            {'ethereumAddress': ethereum_address},
        )

    def get_config(self) -> Response:
        """Get global config variables for the exchange.

        :returns: GlobalConfigVariables
        :raises: DydxAPIError
        """
        return self._get('/v3/config')

    def get_insurance_fund_balance(self) -> Response:
        """Get the balance of the dYdX insurance fund.

        :returns: Balance of the dYdX insurance fund in USD.
        :raises: DydxAPIError
        """
        return self._get('/v3/insurance-fund/balance')

    def get_profile(self, public_id: str) -> Response:
        """Get a public profile.

        :param public_id: Public profile ID.
        :returns: PublicProfile
        :raises: DydxAPIError
        """
        return self._get(f'/v3/profile/{public_id}')

    def get_historical_leaderboard_pnls(
        self,
        period: str,
        limit: Optional[str] = None,
    ) -> Response:
        """Get historical leaderboard PnLs.

        :param period: Period type (e.g. "LEAGUES", "DAILY").
        :param limit: Optional max number of results.
        :returns: HistoricalLeaderboardPnl
        :raises: DydxAPIError
        """
        return self._get(
            f'/v3/accounts/historical-leaderboard-pnls/{period}',
            {'limit': limit},
        )
