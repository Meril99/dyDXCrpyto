from __future__ import annotations

from typing import Any, Optional

import requests


class DydxError(Exception):
    """Base error class for all exceptions raised in this library.

    Will never be raised naked; more specific subclasses of this exception will
    be raised when appropriate.
    """


class DydxApiError(DydxError):
    """Raised when the dYdX API returns a non-2xx response."""

    def __init__(self, response: requests.Response) -> None:
        self.status_code: int = response.status_code
        try:
            self.msg: Any = response.json()
        except ValueError:
            self.msg = response.text
        self.response = response
        self.request: Optional[requests.PreparedRequest] = getattr(
            response, 'request', None,
        )

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        return f'DydxApiError(status_code={self.status_code}, response={self.msg})'


class TransactionReverted(DydxError):
    """Raised when an Ethereum transaction is reverted."""

    def __init__(self, tx_receipt: dict) -> None:
        self.tx_receipt = tx_receipt
