"""Signable transfer for STARK-signed L2 transfers."""

from __future__ import annotations

import math
from collections import namedtuple
from typing import Union

from dydx3.constants import COLLATERAL_ASSET
from dydx3.constants import COLLATERAL_ASSET_ID_BY_NETWORK_ID
from dydx3.starkex.constants import ONE_HOUR_IN_SECONDS
from dydx3.starkex.constants import TRANSFER_FIELD_BIT_LENGTHS
from dydx3.starkex.constants import TRANSFER_PADDING_BITS
from dydx3.starkex.constants import TRANSFER_PREFIX
from dydx3.starkex.constants import TRANSFER_FEE_ASSET_ID
from dydx3.starkex.constants import TRANSFER_MAX_AMOUNT_FEE
from dydx3.starkex.helpers import nonce_from_client_id
from dydx3.starkex.helpers import to_quantums_exact
from dydx3.starkex.signable import Signable
from dydx3.starkex.starkex_resources.proxy import get_hash

StarkwareTransfer = namedtuple(
    'StarkwareTransfer',
    [
        'sender_position_id',
        'receiver_position_id',
        'receiver_public_key',
        'quantums_amount',
        'nonce',
        'expiration_epoch_hours',
    ],
)


class SignableTransfer(Signable):
    """Wrapper to convert a transfer, and hash, sign, and verify its signature."""

    def __init__(
        self,
        sender_position_id: Union[str, int],
        receiver_position_id: Union[str, int],
        receiver_public_key: Union[str, int],
        human_amount: Union[str, int, float],
        client_id: str,
        expiration_epoch_seconds: Union[str, int, float],
        network_id: int,
    ) -> None:
        nonce = nonce_from_client_id(client_id)

        quantums_amount = to_quantums_exact(
            human_amount,
            COLLATERAL_ASSET,
        )

        expiration_epoch_hours = math.ceil(
            float(expiration_epoch_seconds) / ONE_HOUR_IN_SECONDS,
        )

        receiver_public_key = (
            receiver_public_key
            if isinstance(receiver_public_key, int)
            else int(receiver_public_key, 16)
        )

        message = StarkwareTransfer(
            sender_position_id=int(sender_position_id),
            receiver_position_id=int(receiver_position_id),
            receiver_public_key=receiver_public_key,
            quantums_amount=quantums_amount,
            nonce=nonce,
            expiration_epoch_hours=expiration_epoch_hours,
        )

        super().__init__(network_id, message)

    def to_starkware(self) -> StarkwareTransfer:
        return self._message

    def _calculate_hash(self) -> int:
        """Calculate the hash of the Starkware transfer."""
        asset_ids = get_hash(
            COLLATERAL_ASSET_ID_BY_NETWORK_ID[self.network_id],
            TRANSFER_FEE_ASSET_ID,
        )

        part1 = get_hash(
            asset_ids,
            self._message.receiver_public_key,
        )

        part2 = self._message.sender_position_id
        part2 <<= TRANSFER_FIELD_BIT_LENGTHS['position_id']
        part2 += self._message.receiver_position_id
        part2 <<= TRANSFER_FIELD_BIT_LENGTHS['position_id']
        part2 += self._message.sender_position_id
        part2 <<= TRANSFER_FIELD_BIT_LENGTHS['nonce']
        part2 += self._message.nonce

        part3 = TRANSFER_PREFIX
        part3 <<= TRANSFER_FIELD_BIT_LENGTHS['quantums_amount']
        part3 += self._message.quantums_amount
        part3 <<= TRANSFER_FIELD_BIT_LENGTHS['quantums_amount']
        part3 += TRANSFER_MAX_AMOUNT_FEE
        part3 <<= TRANSFER_FIELD_BIT_LENGTHS['expiration_epoch_hours']
        part3 += self._message.expiration_epoch_hours
        part3 <<= TRANSFER_PADDING_BITS

        return get_hash(
            get_hash(part1, part2),
            part3,
        )
