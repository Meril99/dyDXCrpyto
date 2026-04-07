"""Ethereum-authenticated private API module for API key management."""

from __future__ import annotations

from typing import Any, Dict, Optional

from dydx3.helpers.request_helpers import generate_now_iso
from dydx3.helpers.request_helpers import generate_query_path
from dydx3.helpers.request_helpers import json_stringify
from dydx3.eth_signing import SignEthPrivateAction
from dydx3.helpers.requests import Response, request


class EthPrivate:
    """Module for managing API keys and recovery via Ethereum key auth."""

    def __init__(
        self,
        host: str,
        eth_signer: Any,
        network_id: int,
        default_address: Optional[str],
        api_timeout: int,
    ) -> None:
        self.host = host
        self.default_address = default_address
        self.api_timeout = api_timeout

        self.signer = SignEthPrivateAction(eth_signer, network_id)

    # ============ Request Helpers ============

    def _request(
        self,
        method: str,
        endpoint: str,
        opt_ethereum_address: Optional[str],
        data: Optional[Dict[str, Any]] = None,
    ) -> Response:
        if data is None:
            data = {}
        ethereum_address = opt_ethereum_address or self.default_address

        request_path = f'/v3/{endpoint}'
        timestamp = generate_now_iso()
        signature = self.signer.sign(
            ethereum_address,
            method=method.upper(),
            request_path=request_path,
            body=json_stringify(data) if data else '{}',
            timestamp=timestamp,
        )

        return request(
            self.host + request_path,
            method,
            {
                'DYDX-SIGNATURE': signature,
                'DYDX-TIMESTAMP': timestamp,
                'DYDX-ETHEREUM-ADDRESS': ethereum_address,
            },
            data,
            self.api_timeout,
        )

    def _post(
        self,
        endpoint: str,
        opt_ethereum_address: Optional[str],
    ) -> Response:
        return self._request('post', endpoint, opt_ethereum_address)

    def _delete(
        self,
        endpoint: str,
        opt_ethereum_address: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Response:
        url = generate_query_path(endpoint, params or {})
        return self._request('delete', url, opt_ethereum_address)

    def _get(
        self,
        endpoint: str,
        opt_ethereum_address: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Response:
        url = generate_query_path(endpoint, params or {})
        return self._request('get', url, opt_ethereum_address)

    # ============ Requests ============

    def create_api_key(
        self,
        ethereum_address: Optional[str] = None,
    ) -> Response:
        """Register an API key.

        :param ethereum_address: Optional Ethereum address.
        :returns: Object containing an apiKey.
        :raises: DydxAPIError
        """
        return self._post('api-keys', ethereum_address)

    def delete_api_key(
        self,
        api_key: str,
        ethereum_address: Optional[str] = None,
    ) -> Response:
        """Delete an API key.

        :param api_key: The API key to delete.
        :param ethereum_address: Optional Ethereum address.
        :returns: None
        :raises: DydxAPIError
        """
        return self._delete(
            'api-keys',
            ethereum_address,
            {'apiKey': api_key},
        )

    def recovery(
        self,
        ethereum_address: Optional[str] = None,
    ) -> Response:
        """Recover STARK key and balance information.

        Use this if you can't recover your starkKey or apiKey and need
        to call the L1 solidity function for fund recovery.

        :param ethereum_address: Optional Ethereum address.
        :returns: Recovery information including starkKey, positionId, etc.
        :raises: DydxAPIError
        """
        return self._get('recovery', ethereum_address)
