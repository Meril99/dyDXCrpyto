"""Signal pipeline with concrete signal implementations.

Each signal produces a normalized score in [-1, 1]:
    -1 = strong sell conviction
     0 = neutral
    +1 = strong buy conviction
"""

from __future__ import annotations

import abc
import time
from typing import Dict, List, Optional

import numpy as np

from quant.types import Orderbook, Signal
from quant.utils import clip_signal, realized_volatility


class BaseSignal(abc.ABC):
    """Abstract base for all signal generators."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique signal identifier."""
        ...

    @abc.abstractmethod
    def compute(self, **kwargs: object) -> Signal:
        """Compute the signal value."""
        ...


# ============================================================
# Signal 1: Orderbook Imbalance
# ============================================================

class OrderbookImbalance(BaseSignal):
    """Bid/ask volume imbalance from the L2 orderbook.

    imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)

    Ranges naturally from -1 (all asks, selling pressure) to
    +1 (all bids, buying pressure). Depth parameter controls
    how many levels to include.
    """

    def __init__(self, market: str, depth: int = 10) -> None:
        self._market = market
        self._depth = depth

    @property
    def name(self) -> str:
        return f"ob_imbalance_{self._market}"

    def compute(self, orderbook: Optional[Orderbook] = None, **kwargs: object) -> Signal:
        if orderbook is None:
            return Signal(
                name=self.name, market=self._market,
                value=0.0, timestamp=time.time(),
            )

        bids = orderbook.bids[:self._depth]
        asks = orderbook.asks[:self._depth]

        bid_vol = sum(level.size for level in bids)
        ask_vol = sum(level.size for level in asks)
        total = bid_vol + ask_vol

        value = (bid_vol - ask_vol) / total if total > 1e-12 else 0.0

        return Signal(
            name=self.name,
            market=self._market,
            value=clip_signal(value),
            timestamp=orderbook.timestamp,
            metadata={
                'bid_vol': bid_vol,
                'ask_vol': ask_vol,
                'depth': float(self._depth),
            },
        )


# ============================================================
# Signal 2: Funding Rate Mean Reversion
# ============================================================

class FundingRateMeanReversion(BaseSignal):
    """Mean-reversion signal based on funding rate extremes.

    When funding is very positive (longs pay shorts), the market is
    overheated long -- expect reversion down => negative signal.
    When funding is very negative, expect reversion up => positive signal.

    signal = -tanh(avg_funding_rate / threshold)

    The tanh provides smooth saturation to [-1, 1].
    """

    def __init__(
        self,
        market: str,
        threshold: float = 0.0001,
        lookback: int = 8,
    ) -> None:
        self._market = market
        self._threshold = threshold
        self._lookback = lookback
        self._history: List[float] = []

    @property
    def name(self) -> str:
        return f"funding_mr_{self._market}"

    def update(self, funding_rate: float) -> None:
        """Append a new funding rate observation."""
        self._history.append(funding_rate)
        if len(self._history) > self._lookback * 3:
            self._history = self._history[-self._lookback * 3:]

    def compute(self, funding_rate: Optional[float] = None, **kwargs: object) -> Signal:
        if funding_rate is not None:
            self.update(funding_rate)

        if len(self._history) < 1:
            return Signal(
                name=self.name, market=self._market,
                value=0.0, timestamp=time.time(),
            )

        recent = self._history[-self._lookback:]
        avg_rate = float(np.mean(recent))

        # Negative sign: high positive funding => expect DOWN => sell
        value = -float(np.tanh(avg_rate / self._threshold))

        return Signal(
            name=self.name,
            market=self._market,
            value=clip_signal(value),
            timestamp=time.time(),
            metadata={'avg_funding': avg_rate, 'raw_rate': self._history[-1]},
        )


# ============================================================
# Signal 3: Cross-Asset Momentum
# ============================================================

class CrossAssetMomentum(BaseSignal):
    """Detects lagged correlation between a leader and follower asset.

    If BTC moved up significantly in the last N periods and ETH
    hasn't caught up, the signal is positive for ETH (expect follow).

    signal = clip((leader_z - follower_z) / 4)
    """

    def __init__(
        self,
        leader_market: str = "BTC-USD",
        follower_market: str = "ETH-USD",
        lookback: int = 20,
        lag: int = 1,
    ) -> None:
        self._leader = leader_market
        self._follower = follower_market
        self._lookback = lookback
        self._lag = lag
        self._leader_prices: List[float] = []
        self._follower_prices: List[float] = []

    @property
    def name(self) -> str:
        return f"cross_momentum_{self._leader}_{self._follower}"

    def update(self, leader_price: float, follower_price: float) -> None:
        """Append new price observations for both assets."""
        self._leader_prices.append(leader_price)
        self._follower_prices.append(follower_price)

    def compute(self, **kwargs: object) -> Signal:
        n = self._lookback + self._lag + 1
        if len(self._leader_prices) < n or len(self._follower_prices) < n:
            return Signal(
                name=self.name, market=self._follower,
                value=0.0, timestamp=time.time(),
            )

        leader = np.array(self._leader_prices[-n:])
        follower = np.array(self._follower_prices[-n:])

        leader_rets = np.diff(np.log(leader))
        follower_rets = np.diff(np.log(follower))

        leader_std = np.std(leader_rets)
        follower_std = np.std(follower_rets)

        if leader_std < 1e-12 or follower_std < 1e-12:
            return Signal(
                name=self.name, market=self._follower,
                value=0.0, timestamp=time.time(),
            )

        # Z-score of the lagged leader return vs current follower return
        leader_z = (
            (leader_rets[-1 - self._lag] - np.mean(leader_rets)) / leader_std
        )
        follower_z = (
            (follower_rets[-1] - np.mean(follower_rets)) / follower_std
        )

        # Divergence: leader moved but follower hasn't caught up
        value = float(leader_z - follower_z) / 4.0

        return Signal(
            name=self.name,
            market=self._follower,
            value=clip_signal(value),
            timestamp=time.time(),
            metadata={
                'leader_z': float(leader_z),
                'follower_z': float(follower_z),
            },
        )


# ============================================================
# Signal 4: Volatility Regime Detection
# ============================================================

class VolatilityRegime(BaseSignal):
    """Classifies current volatility into regimes.

    Uses percentile rank of rolling realized vol vs. its own
    longer-term distribution.

    Regimes:
        LOW    (< 25th pct):  signal = +0.5  (favorable for MM)
        NORMAL (25-75th pct): signal =  0.0
        HIGH   (75-95th pct): signal = -0.5  (widen spreads)
        CRISIS (> 95th pct):  signal = -1.0  (shut down)
    """

    def __init__(
        self,
        market: str,
        short_window: int = 20,
        long_window: int = 200,
    ) -> None:
        self._market = market
        self._short = short_window
        self._long = long_window
        self._prices: List[float] = []

    @property
    def name(self) -> str:
        return f"vol_regime_{self._market}"

    def update(self, price: float) -> None:
        """Append a new price observation."""
        self._prices.append(price)

    def compute(self, **kwargs: object) -> Signal:
        needed = self._long + self._short + 1
        if len(self._prices) < needed:
            return Signal(
                name=self.name, market=self._market,
                value=0.0, timestamp=time.time(),
                metadata={'regime': 'INSUFFICIENT_DATA'},
            )

        prices = np.array(self._prices[-needed:])
        vol_series = realized_volatility(
            prices, window=self._short, annualize=False,
        )
        vol_valid = vol_series[~np.isnan(vol_series)]
        if len(vol_valid) < 2:
            return Signal(
                name=self.name, market=self._market,
                value=0.0, timestamp=time.time(),
            )

        current_vol = vol_valid[-1]
        pct = float(
            np.searchsorted(np.sort(vol_valid), current_vol) / len(vol_valid)
        )

        if pct >= 0.95:
            regime, value = 'CRISIS', -1.0
        elif pct >= 0.75:
            regime, value = 'HIGH', -0.5
        elif pct >= 0.25:
            regime, value = 'NORMAL', 0.0
        else:
            regime, value = 'LOW', 0.5

        return Signal(
            name=self.name,
            market=self._market,
            value=clip_signal(value),
            timestamp=time.time(),
            metadata={
                'regime': regime,
                'current_vol': float(current_vol),
                'percentile': pct,
            },
        )


# ============================================================
# Signal Combiner
# ============================================================

class SignalCombiner:
    """Weighted combination of multiple signals into a composite.

    composite = clip(sum(w_i * signal_i) / sum(|w_i|))
    """

    def __init__(self, weights: Dict[str, float]) -> None:
        self._weights = weights

    def combine(self, signals: List[Signal]) -> Signal:
        """Combine multiple signals into a single composite signal."""
        total_weight = sum(abs(w) for w in self._weights.values()) or 1.0
        composite = 0.0
        metadata: Dict[str, float] = {}

        for sig in signals:
            w = self._weights.get(sig.name, 0.0)
            composite += w * sig.value
            metadata[sig.name] = sig.value

        composite /= total_weight
        market = signals[0].market if signals else "UNKNOWN"

        return Signal(
            name="composite",
            market=market,
            value=clip_signal(composite),
            timestamp=time.time(),
            metadata=metadata,
        )
