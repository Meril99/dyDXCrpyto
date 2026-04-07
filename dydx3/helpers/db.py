"""Helpers for generating deterministic user and account IDs."""

from __future__ import annotations

import uuid

NAMESPACE = uuid.UUID('0f9da948-a6fb-4c45-9edc-4685c3f3317d')


def get_user_id(address: str) -> str:
    """Generate a deterministic user ID from an Ethereum address."""
    return str(uuid.uuid5(NAMESPACE, address))


def get_account_id(
    address: str,
    account_number: int = 0,
) -> str:
    """Generate a deterministic account ID from an address and account number."""
    return str(
        uuid.uuid5(
            NAMESPACE,
            get_user_id(address.lower()) + str(account_number),
        ),
    )
