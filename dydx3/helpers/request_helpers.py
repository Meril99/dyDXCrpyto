"""Helpers for constructing and formatting HTTP requests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import json
import random

import dateutil.parser as dp


def generate_query_path(url: str, params: Dict[str, Any]) -> str:
    """Append query parameters to a URL, filtering out None values."""
    entries = params.items()
    if not entries:
        return url

    params_string = '&'.join(
        f'{key}={value}' for key, value in entries if value is not None
    )
    if params_string:
        return f'{url}?{params_string}'

    return url


def json_stringify(data: Any) -> str:
    """Serialize data to a compact JSON string."""
    return json.dumps(data, separators=(',', ':'))


def random_client_id() -> str:
    """Generate a random client ID string."""
    return str(int(float(str(random.random())[2:])))


def generate_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%S.%f',
    )[:-3] + 'Z'


def iso_to_epoch_seconds(iso: str) -> float:
    """Convert an ISO 8601 timestamp to epoch seconds."""
    return dp.parse(iso).timestamp()


def epoch_seconds_to_iso(epoch: float) -> str:
    """Convert epoch seconds to an ISO 8601 timestamp."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%S.%f',
    )[:-3] + 'Z'


def remove_nones(original: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the dict with all None-valued entries removed."""
    return {k: v for k, v in original.items() if v is not None}
