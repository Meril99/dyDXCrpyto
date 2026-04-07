"""HTTP request abstraction for the dYdX API."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from dydx3.errors import DydxApiError
from dydx3.helpers.request_helpers import remove_nones


def _create_session() -> requests.Session:
    """Create a new requests session with default headers."""
    s = requests.Session()
    s.headers.update({
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': 'dydx/python',
    })
    return s


# Module-level session for connection pooling.
_session = _create_session()


class Response:
    """Wrapper around an API response containing parsed data and headers."""

    def __init__(
        self,
        data: Any = None,
        headers: Optional[Any] = None,
    ) -> None:
        self.data = data if data is not None else {}
        self.headers = headers


def request(
    uri: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    data_values: Optional[Dict[str, Any]] = None,
    api_timeout: Optional[int] = None,
) -> Response:
    """Make an HTTP request to the dYdX API and return a Response."""
    response = _send_request(
        uri,
        method,
        headers,
        data=json.dumps(
            remove_nones(data_values or {})
        ),
        timeout=api_timeout,
    )
    if not str(response.status_code).startswith('2'):
        raise DydxApiError(response)

    if response.content:
        return Response(response.json(), response.headers)
    else:
        return Response('{}', response.headers)


def _send_request(
    uri: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> requests.Response:
    """Dispatch an HTTP request via the module-level session."""
    return getattr(_session, method)(uri, headers=headers, **kwargs)
