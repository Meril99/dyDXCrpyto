"""Vectorized backtesting framework for dYdX perpetual futures strategies."""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from quant.types import BacktestResult, Fill, Order, Position, Side
from quant.utils import (
    fetch_candles_df,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
)

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    initial_equity: float = 10_000.0
    maker_fee: float = 0.0002          # 2 bps
    taker_fee: float = 0.001           # 10 bps
    slippage_bps: float = 1.0          # 1 bp slippage model
    funding_rate_per_hour: float = 0.0
    max_leverage: float = 10.0


@dataclass
class BacktestContext:
    """Provides strategies with safe access to historical data."""
    candles_so_far: pd.DataFrame
    current_index: int
    config: BacktestConfig

    def lookback(self, n: int) -> pd.DataFrame:
        """Get the last n candles (inclusive of current)."""
        start = max(0, self.current_index - n + 1)
        return self.candles_so_far.iloc[start:self.current_index + 1]


class Strategy(abc.ABC):
    """Abstract base class for backtestable strategies.

    Subclass and implement on_candle(). Optionally override on_fill()
    for more complex logic.
    """

    @abc.abstractmethod
    def on_candle(
        self,
        candle: pd.Series,
        positions: Dict[str, Position],
        equity: float,
        context: BacktestContext,
    ) -> List[Order]:
        """Called for each candle. Return a list of orders to submit.

        Parameters:
            candle: Current candle row with open/high/low/close/volume.
            positions: Current open positions keyed by market.
            equity: Current total equity (cash + unrealized PnL).
            context: Access to historical candles via context.lookback(n).
        """
        ...

    def on_fill(self, fill: Fill, positions: Dict[str, Position]) -> None:
        """Called after an order is filled. Override for bookkeeping."""
        pass


class Backtester:
    """Event-driven backtester with vectorized data loading.

    Usage:
        bt = Backtester(config)
        bt.load_candles(df)
        result = bt.run(my_strategy)
        print(result.metrics)
    """

    def __init__(self, config: Optional[BacktestConfig] = None) -> None:
        self._config = config or BacktestConfig()
        self._candles: Optional[pd.DataFrame] = None
        self._funding: Optional[pd.DataFrame] = None

    def load_candles(self, candles: pd.DataFrame) -> None:
        """Load candle data.

        Expected columns: timestamp, open, high, low, close, volume.
        Optionally: market.
        """
        required = {'timestamp', 'open', 'high', 'low', 'close', 'volume'}
        missing = required - set(candles.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        self._candles = candles.sort_values('timestamp').reset_index(drop=True)

    def load_candles_from_api(
        self,
        public: Any,
        market: str,
        resolution: str = "1HOUR",
        limit: int = 100,
    ) -> None:
        """Fetch candles from dYdX API and load them."""
        df = fetch_candles_df(public, market, resolution, limit)
        self.load_candles(df)

    def load_funding_rates(self, funding: pd.DataFrame) -> None:
        """Load historical funding rates.

        Expected columns: timestamp, market, rate.
        """
        self._funding = funding.sort_values('timestamp').reset_index(drop=True)

    def run(self, strategy: Strategy) -> BacktestResult:
        """Execute the backtest and return results."""
        if self._candles is None:
            raise ValueError("No candle data loaded")

        cfg = self._config
        candles = self._candles
        n = len(candles)

        # State
        cash = cfg.initial_equity
        positions: Dict[str, Position] = {}
        fills: List[Fill] = []
        equity_curve: List[float] = []
        timestamps: List[float] = []

        for i in range(n):
            row = candles.iloc[i]
            ts = float(row['timestamp'])

            # 1. Apply funding to open positions
            cash = self._apply_funding(row, positions, cash)

            # 2. Update unrealized PnL
            for pos in positions.values():
                pos.unrealized_pnl = (
                    (row['close'] - pos.entry_price) * pos.size
                )

            # 3. Compute equity
            equity = cash + sum(
                p.unrealized_pnl for p in positions.values()
            )

            # 4. Ask strategy for orders
            context = BacktestContext(
                candles_so_far=candles.iloc[:i + 1],
                current_index=i,
                config=cfg,
            )
            orders = strategy.on_candle(row, positions, equity, context)

            # 5. Simulate order matching
            for order in (orders or []):
                fill = self._simulate_fill(order, row, cfg)
                if fill is not None:
                    cash = self._apply_fill(fill, positions, cash)
                    fills.append(fill)
                    strategy.on_fill(fill, positions)

            # 6. Record equity
            equity = cash + sum(
                p.unrealized_pnl for p in positions.values()
            )
            equity_curve.append(equity)
            timestamps.append(ts)

        # Compute metrics
        eq_arr = np.array(equity_curve)
        if len(eq_arr) > 1:
            returns = np.diff(eq_arr) / np.where(
                eq_arr[:-1] != 0, eq_arr[:-1], 1.0,
            )
        else:
            returns = np.array([])
        metrics = self._compute_metrics(returns, eq_arr, fills)

        return BacktestResult(
            equity_curve=equity_curve,
            timestamps=timestamps,
            fills=fills,
            positions=positions,
            metrics=metrics,
            candles_count=n,
            final_equity=equity_curve[-1] if equity_curve else cfg.initial_equity,
        )

    def _simulate_fill(
        self,
        order: Order,
        candle: pd.Series,
        cfg: BacktestConfig,
    ) -> Optional[Fill]:
        """Simulate order matching against the candle."""
        if order.price is None:
            # Market order: fill at close +/- slippage
            slippage = candle['close'] * cfg.slippage_bps * 1e-4
            fill_price = (
                candle['close'] + slippage
                if order.side == Side.BUY
                else candle['close'] - slippage
            )
        else:
            # Limit order: check if executable within candle range
            if order.side == Side.BUY and order.price >= candle['low']:
                fill_price = order.price
            elif order.side == Side.SELL and order.price <= candle['high']:
                fill_price = order.price
            else:
                return None

        fee_rate = cfg.maker_fee if order.is_maker else cfg.taker_fee
        fee = fill_price * order.size * fee_rate

        return Fill(
            market=order.market,
            side=order.side,
            price=fill_price,
            size=order.size,
            fee=fee,
            timestamp=float(candle['timestamp']),
            is_maker=order.is_maker,
        )

    def _apply_fill(
        self,
        fill: Fill,
        positions: Dict[str, Position],
        cash: float,
    ) -> float:
        """Update positions and cash after a fill."""
        market = fill.market
        signed_size = fill.size if fill.side == Side.BUY else -fill.size

        if market not in positions:
            # Open new position
            positions[market] = Position(
                market=market,
                size=signed_size,
                entry_price=fill.price,
            )
            cash -= fill.fee
        else:
            pos = positions[market]
            same_direction = (
                (pos.size > 0 and fill.side == Side.BUY)
                or (pos.size < 0 and fill.side == Side.SELL)
            )

            if same_direction:
                # Increasing position — weighted average entry
                total = abs(pos.size) + fill.size
                pos.entry_price = (
                    pos.entry_price * abs(pos.size)
                    + fill.price * fill.size
                ) / total
                pos.size += signed_size
            else:
                # Reducing or flipping
                closed_size = min(abs(pos.size), fill.size)
                realized = (fill.price - pos.entry_price) * closed_size
                if pos.size < 0:
                    realized = -realized
                pos.realized_pnl += realized
                cash += realized

                pos.size += signed_size
                if abs(pos.size) < 1e-12:
                    del positions[market]
                elif np.sign(pos.size) != np.sign(
                    pos.size - signed_size
                ):
                    # Flipped direction
                    pos.entry_price = fill.price

            cash -= fill.fee

        return cash

    def _apply_funding(
        self,
        candle: pd.Series,
        positions: Dict[str, Position],
        cash: float,
    ) -> float:
        """Apply funding rate to open positions.

        dYdX funding is paid every hour. Positive rate = longs pay shorts.
        """
        rate = self._config.funding_rate_per_hour

        # Use historical funding if available
        if self._funding is not None and not self._funding.empty:
            ts = float(candle['timestamp'])
            closest = self._funding.iloc[
                (self._funding['timestamp'] - ts).abs().argsort()[:1]
            ]
            if not closest.empty:
                rate = float(closest.iloc[0]['rate'])

        for pos in positions.values():
            # Positive rate: longs pay, shorts receive
            payment = -pos.size * pos.entry_price * rate
            pos.funding_payments += payment
            cash += payment

        return cash

    def _compute_metrics(
        self,
        returns: np.ndarray,
        equity_curve: np.ndarray,
        fills: List[Fill],
    ) -> Dict[str, float]:
        """Compute performance metrics."""
        if len(equity_curve) < 2:
            return {
                'sharpe_ratio': 0.0,
                'sortino_ratio': 0.0,
                'max_drawdown': 0.0,
                'total_return': 0.0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'total_fills': 0,
            }

        # Compute win rate from round-trip trades
        win_count = 0
        total_trades = 0
        buy_fills: Dict[str, List[Fill]] = {}
        for f in fills:
            if f.side == Side.BUY:
                buy_fills.setdefault(f.market, []).append(f)
            else:
                # Match against earliest buy
                buys = buy_fills.get(f.market, [])
                if buys:
                    entry = buys.pop(0)
                    if f.price > entry.price:
                        win_count += 1
                    total_trades += 1

        return {
            'sharpe_ratio': sharpe_ratio(returns),
            'sortino_ratio': sortino_ratio(returns),
            'max_drawdown': max_drawdown(equity_curve),
            'total_return': float(
                equity_curve[-1] / equity_curve[0] - 1.0
            ),
            'win_rate': win_count / total_trades if total_trades > 0 else 0.0,
            'profit_factor': profit_factor(fills),
            'total_fills': float(len(fills)),
        }
