"""Real-time risk monitoring and circuit breakers for perpetual futures."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np

from quant.types import Position, RiskSnapshot

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Circuit breaker thresholds."""
    max_drawdown: float = 0.10
    max_position_size: float = 100.0
    max_total_exposure: float = 50_000.0
    max_margin_utilization: float = 0.8
    max_single_loss: float = 500.0
    var_limit_95: float = 2_000.0


@dataclass
class CircuitBreakerEvent:
    """Record of a circuit breaker trigger."""
    timestamp: float
    reason: str
    metric_value: float
    threshold: float


class RiskMonitor:
    """Portfolio risk tracker with circuit breakers.

    Works in two modes:
    - Live: calls dYdX API via update()
    - Backtest: pure computation via compute_snapshot()
    """

    def __init__(
        self,
        client: Optional[object] = None,
        limits: Optional[RiskLimits] = None,
        on_breaker: Optional[Callable[[CircuitBreakerEvent], None]] = None,
    ) -> None:
        self._client = client
        self._limits = limits or RiskLimits()
        self._on_breaker = on_breaker
        self._peak_equity: float = 0.0
        self._equity_history: List[float] = []
        self._return_history: List[float] = []
        self._breaker_events: List[CircuitBreakerEvent] = []

    # --- Live update ---

    def update(self) -> RiskSnapshot:
        """Fetch account state from dYdX API and compute risk snapshot."""
        if self._client is None:
            raise ValueError("Client required for live updates")

        account_resp = self._client.private.get_account()
        account = account_resp.data['account']
        equity = float(account['equity'])

        pos_resp = self._client.private.get_positions(status='OPEN')
        raw_positions = pos_resp.data.get('positions', [])

        positions: Dict[str, Position] = {}
        for p in raw_positions:
            market = p['market']
            positions[market] = Position(
                market=market,
                size=float(p['size']),
                entry_price=float(p['entryPrice']),
                unrealized_pnl=float(p.get('unrealizedPnl', 0)),
            )

        prices: Dict[str, float] = {}
        for market in positions:
            ob = self._client.public.get_orderbook(market)
            bids = ob.data.get('bids', [])
            asks = ob.data.get('asks', [])
            if bids and asks:
                prices[market] = (
                    float(bids[0]['price']) + float(asks[0]['price'])
                ) / 2

        return self.compute_snapshot(positions, equity, prices)

    # --- Core computation ---

    def compute_snapshot(
        self,
        positions: Dict[str, Position],
        equity: float,
        prices: Optional[Dict[str, float]] = None,
    ) -> RiskSnapshot:
        """Compute a complete risk snapshot from provided data.

        Pure computation — no API calls. Usable from backtester.
        """
        prices = prices or {}

        # Track equity history
        self._equity_history.append(equity)
        if len(self._equity_history) > 1:
            prev = self._equity_history[-2]
            if abs(prev) > 1e-12:
                self._return_history.append((equity - prev) / prev)
        self._peak_equity = max(self._peak_equity, equity)

        # Position-level metrics
        total_exposure = 0.0
        net_delta = 0.0
        for mkt, pos in positions.items():
            price = prices.get(mkt, pos.entry_price)
            notional = abs(pos.size) * price
            total_exposure += notional
            net_delta += pos.size * price

        # Margin utilization
        margin_util = (
            total_exposure / equity if equity > 1e-12 else float('inf')
        )

        # Drawdown from peak
        dd = (
            (self._peak_equity - equity) / self._peak_equity
            if self._peak_equity > 1e-12
            else 0.0
        )

        # VaR estimation
        var_95 = self._compute_var(equity)

        # Circuit breaker checks
        breaker_triggered = False
        breaker_reason: Optional[str] = None
        limits = self._limits

        checks = [
            (
                dd > limits.max_drawdown,
                f"Drawdown {dd:.2%} exceeds {limits.max_drawdown:.2%}",
                dd,
                limits.max_drawdown,
            ),
            (
                total_exposure > limits.max_total_exposure,
                f"Exposure ${total_exposure:,.0f} exceeds "
                f"${limits.max_total_exposure:,.0f}",
                total_exposure,
                limits.max_total_exposure,
            ),
            (
                margin_util > limits.max_margin_utilization,
                f"Margin util {margin_util:.2%} exceeds "
                f"{limits.max_margin_utilization:.2%}",
                margin_util,
                limits.max_margin_utilization,
            ),
            (
                var_95 > limits.var_limit_95,
                f"VaR ${var_95:,.0f} exceeds ${limits.var_limit_95:,.0f}",
                var_95,
                limits.var_limit_95,
            ),
        ]

        # Per-position checks
        for mkt, pos in positions.items():
            if abs(pos.size) > limits.max_position_size:
                checks.append((
                    True,
                    f"{mkt} size {pos.size} exceeds {limits.max_position_size}",
                    abs(pos.size),
                    limits.max_position_size,
                ))
            if pos.unrealized_pnl < -limits.max_single_loss:
                checks.append((
                    True,
                    f"{mkt} loss ${pos.unrealized_pnl:,.0f} exceeds "
                    f"${limits.max_single_loss:,.0f}",
                    abs(pos.unrealized_pnl),
                    limits.max_single_loss,
                ))

        for triggered, reason, value, threshold in checks:
            if triggered:
                breaker_triggered = True
                breaker_reason = reason
                event = CircuitBreakerEvent(
                    timestamp=time.time(),
                    reason=reason,
                    metric_value=value,
                    threshold=threshold,
                )
                self._breaker_events.append(event)
                logger.warning("CIRCUIT BREAKER: %s", reason)
                if self._on_breaker:
                    self._on_breaker(event)
                break

        return RiskSnapshot(
            timestamp=time.time(),
            total_equity=equity,
            total_exposure=total_exposure,
            net_delta=net_delta,
            margin_utilization=margin_util,
            var_95=var_95,
            max_drawdown=dd,
            positions=positions,
            breaker_triggered=breaker_triggered,
            breaker_reason=breaker_reason,
        )

    def _compute_var(self, current_equity: float) -> float:
        """Historical simulation VaR at 95% confidence.

        Falls back to parametric (normal) VaR if insufficient history.
        """
        if len(self._return_history) < 20:
            return current_equity * 0.02 * 1.645

        returns = np.array(self._return_history[-252:])
        var_pct = np.percentile(returns, 5)
        return abs(var_pct * current_equity)

    # --- Emergency actions ---

    def emergency_flatten(self) -> None:
        """Cancel all orders and close all positions."""
        if self._client is None:
            logger.warning("No client: cannot flatten positions")
            return

        logger.critical("EMERGENCY FLATTEN: cancelling all orders")
        self._client.private.cancel_all_orders()

        pos_resp = self._client.private.get_positions(status='OPEN')
        for p in pos_resp.data.get('positions', []):
            size = float(p['size'])
            if abs(size) < 1e-12:
                continue
            side = 'SELL' if size > 0 else 'BUY'
            logger.critical(
                "Closing %s position: %s %s @ market",
                p['market'], side, abs(size),
            )

    @property
    def breaker_events(self) -> List[CircuitBreakerEvent]:
        """All circuit breaker events that have occurred."""
        return list(self._breaker_events)

    def reset(self) -> None:
        """Reset internal state (e.g. between backtest runs)."""
        self._peak_equity = 0.0
        self._equity_history.clear()
        self._return_history.clear()
        self._breaker_events.clear()
