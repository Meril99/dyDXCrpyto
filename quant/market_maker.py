"""Avellaneda-Stoikov market-making engine for dYdX v3 perpetual futures.

Implements the optimal quoting strategy from:
    Avellaneda, M. & Stoikov, S. (2008).
    "High-frequency trading in a limit order book."
    Quantitative Finance, 8(3), 217-224.

Core formulas:
    reservation_price = mid - q * gamma * sigma^2 * tau
    optimal_spread = gamma * sigma^2 * tau + (2/gamma) * ln(1 + gamma/k)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from quant.types import Orderbook, OrderbookLevel, QuoteOrder, Signal, Side
from quant.utils import mid_price_from_orderbook, realized_volatility

logger = logging.getLogger(__name__)


@dataclass
class MarketMakerConfig:
    """Configuration for the Avellaneda-Stoikov market maker."""
    market: str                        # e.g. "BTC-USD"
    order_size: float                  # size per quote side
    max_inventory: float               # absolute max position size
    gamma: float = 0.1                 # inventory risk aversion
    k: float = 1.5                     # order arrival intensity
    session_duration_s: float = 3600   # rolling time horizon (seconds)
    min_spread_bps: float = 5.0        # minimum spread floor (basis points)
    max_spread_bps: float = 100.0      # maximum spread cap
    refresh_interval_s: float = 5.0    # quote refresh interval
    vol_window: int = 20               # lookback for vol estimation
    position_id: str = ""              # dYdX position ID
    limit_fee: str = "0.0005"          # max fee as fraction


class MarketMaker:
    """Avellaneda-Stoikov market maker for a single perpetual market.

    Lifecycle:
        mm = MarketMaker(client, config)
        mm.update_orderbook(orderbook)    # or let run_once() fetch
        mm.update_volatility(sigma)       # or auto-estimate
        mm.update_inventory(position)     # or let run_once() fetch
        bid, ask = mm.compute_quotes()    # pure math
        mm.place_quotes(bid, ask)         # sends to exchange
    """

    def __init__(
        self,
        client: Optional[object] = None,
        config: Optional[MarketMakerConfig] = None,
    ) -> None:
        self._client = client
        self._config = config or MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=0.01,
        )
        self._inventory: float = 0.0
        self._sigma: float = 0.0
        self._mid_price: float = 0.0
        self._session_start: float = time.time()
        self._active_orders: Dict[str, QuoteOrder] = {}
        self._price_history: List[float] = []
        self._signal_skew: float = 0.0

    # --- State updates ---

    def update_orderbook(self, orderbook: Orderbook) -> None:
        """Update internal mid-price from a fresh orderbook snapshot."""
        self._mid_price = mid_price_from_orderbook(
            orderbook.bids, orderbook.asks,
        )
        self._price_history.append(self._mid_price)

    def update_volatility(self, sigma: Optional[float] = None) -> None:
        """Update volatility estimate.

        If sigma is None, auto-estimate from accumulated price history.
        """
        if sigma is not None:
            self._sigma = sigma
        elif len(self._price_history) >= self._config.vol_window + 1:
            prices = np.array(
                self._price_history[-self._config.vol_window - 1:]
            )
            vol_arr = realized_volatility(
                prices, window=self._config.vol_window,
            )
            valid = vol_arr[~np.isnan(vol_arr)]
            if len(valid) > 0:
                self._sigma = float(valid[-1])

    def update_inventory(self, position_size: float) -> None:
        """Update current inventory from exchange position data."""
        self._inventory = position_size

    def apply_signal(self, signal: Signal) -> None:
        """Skew quotes based on an external signal.

        Positive signal => shift reservation price up (expect price increase).
        """
        self._signal_skew = (
            signal.value
            * self._config.min_spread_bps
            * 1e-4
            * self._mid_price
        )

    # --- Core Avellaneda-Stoikov computation ---

    def _time_remaining(self) -> float:
        """Fraction of session remaining, clamped to [0.01, 1.0].

        Uses a rolling horizon to avoid the tau->0 singularity.
        """
        elapsed = time.time() - self._session_start
        remaining = max(
            0.01, 1.0 - elapsed / self._config.session_duration_s,
        )
        if remaining <= 0.01:
            self._session_start = time.time()
            remaining = 1.0
        return remaining

    def compute_reservation_price(self) -> float:
        """Compute the reservation (indifference) price.

        r(s,t) = s - q * gamma * sigma^2 * tau + signal_skew

        Where:
            s = mid-price
            q = current inventory
            gamma = risk aversion
            sigma = volatility
            tau = time remaining
        """
        cfg = self._config
        tau = self._time_remaining()
        return (
            self._mid_price
            - self._inventory * cfg.gamma * (self._sigma ** 2) * tau
            + self._signal_skew
        )

    def compute_optimal_spread(self) -> float:
        """Compute the optimal bid-ask spread.

        delta = gamma * sigma^2 * tau + (2/gamma) * ln(1 + gamma/k)

        Clamped to [min_spread_bps, max_spread_bps] in absolute terms.
        """
        cfg = self._config
        tau = self._time_remaining()

        if cfg.gamma < 1e-12:
            spread = self._mid_price * cfg.min_spread_bps * 1e-4
        else:
            spread = (
                cfg.gamma * (self._sigma ** 2) * tau
                + (2.0 / cfg.gamma) * np.log(1.0 + cfg.gamma / cfg.k)
            )

        min_spread = self._mid_price * cfg.min_spread_bps * 1e-4
        max_spread = self._mid_price * cfg.max_spread_bps * 1e-4
        return float(np.clip(spread, min_spread, max_spread))

    def compute_quotes(self) -> Tuple[QuoteOrder, QuoteOrder]:
        """Compute bid and ask quotes.

        Returns (bid_quote, ask_quote). Size is set to zero on a side
        if placing would exceed max_inventory.
        """
        reservation = self.compute_reservation_price()
        half_spread = self.compute_optimal_spread() / 2.0

        bid_price = reservation - half_spread
        ask_price = reservation + half_spread

        cfg = self._config
        bid_size = (
            cfg.order_size if self._inventory < cfg.max_inventory else 0.0
        )
        ask_size = (
            cfg.order_size if self._inventory > -cfg.max_inventory else 0.0
        )

        bid = QuoteOrder(
            market=cfg.market, side=Side.BUY,
            price=round(bid_price, 2), size=bid_size,
        )
        ask = QuoteOrder(
            market=cfg.market, side=Side.SELL,
            price=round(ask_price, 2), size=ask_size,
        )
        return bid, ask

    # --- Exchange interaction ---

    def place_quotes(self, bid: QuoteOrder, ask: QuoteOrder) -> None:
        """Cancel existing orders and place new bid/ask pair."""
        if self._client is None:
            logger.debug(
                "No client: quotes computed but not placed "
                "(bid=%.2f, ask=%.2f)",
                bid.price, ask.price,
            )
            return

        self.cancel_stale_orders()

        for quote in (bid, ask):
            if quote.size < 1e-12:
                continue
            side_str = 'BUY' if quote.side == Side.BUY else 'SELL'
            try:
                resp = self._client.private.create_order(
                    position_id=self._config.position_id,
                    market=self._config.market,
                    side=side_str,
                    order_type='LIMIT',
                    post_only=True,
                    size=str(quote.size),
                    price=str(quote.price),
                    limit_fee=self._config.limit_fee,
                    expiration_epoch_seconds=int(time.time()) + 120,
                )
                order_id = resp.data.get('order', {}).get('id', '')
                quote.order_id = order_id
                self._active_orders[order_id] = quote
                logger.info(
                    "Placed %s %.4f @ %.2f [%s]",
                    side_str, quote.size, quote.price, order_id,
                )
            except Exception as e:
                logger.error("Failed to place %s order: %s", side_str, e)

    def cancel_stale_orders(self) -> None:
        """Cancel all active orders for this market."""
        if self._client is None:
            return
        try:
            self._client.private.cancel_all_orders(
                market=self._config.market,
            )
        except Exception as e:
            logger.error("Failed to cancel orders: %s", e)
        self._active_orders.clear()

    # --- Main loop ---

    def run_once(self) -> Tuple[QuoteOrder, QuoteOrder]:
        """Execute one full cycle: fetch state, compute, and place quotes.

        Returns the computed quotes (for logging/testing).
        """
        if self._client is None:
            raise ValueError("Client required for run_once()")

        # 1. Fetch orderbook
        ob_resp = self._client.public.get_orderbook(self._config.market)
        orderbook = parse_orderbook(ob_resp.data)
        self.update_orderbook(orderbook)

        # 2. Fetch position
        pos_resp = self._client.private.get_positions(
            market=self._config.market, status='OPEN',
        )
        raw_positions = pos_resp.data.get('positions', [])
        inv = float(raw_positions[0]['size']) if raw_positions else 0.0
        self.update_inventory(inv)

        # 3. Update volatility
        self.update_volatility()

        # 4. Compute and place
        bid, ask = self.compute_quotes()
        self.place_quotes(bid, ask)

        logger.info(
            "[%s] mid=%.2f inv=%.4f sigma=%.6f bid=%.2f ask=%.2f "
            "spread=%.1fbps",
            self._config.market,
            self._mid_price,
            self._inventory,
            self._sigma,
            bid.price,
            ask.price,
            (ask.price - bid.price) / self._mid_price * 1e4
            if self._mid_price > 0 else 0,
        )
        return bid, ask

    @property
    def mid_price(self) -> float:
        return self._mid_price

    @property
    def inventory(self) -> float:
        return self._inventory

    @property
    def sigma(self) -> float:
        return self._sigma


def parse_orderbook(data: dict) -> Orderbook:
    """Convert API response dict to an Orderbook dataclass."""
    bids = [
        OrderbookLevel(price=float(b['price']), size=float(b['size']))
        for b in data.get('bids', [])
    ]
    asks = [
        OrderbookLevel(price=float(a['price']), size=float(a['size']))
        for a in data.get('asks', [])
    ]
    return Orderbook(bids=bids, asks=asks, timestamp=time.time())
