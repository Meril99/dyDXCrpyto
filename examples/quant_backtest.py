"""Example: Backtest a simple momentum strategy on ETH-USD.

Demonstrates:
    - Defining a custom Strategy subclass
    - Loading candle data
    - Running a backtest and inspecting results

Usage:
    python examples/quant_backtest.py
"""

from typing import Dict, List

import numpy as np
import pandas as pd

from quant import Backtester, BacktestConfig, Strategy, Order, Side
from quant.types import Fill, Position


class MomentumStrategy(Strategy):
    """Buy when price crosses above 20-period SMA, sell when below.

    Position sizes at 10% of equity per trade. This is a simple
    trend-following strategy suitable for demonstrating the backtester.
    """

    def __init__(self, sma_period: int = 20) -> None:
        self._sma_period = sma_period

    def on_candle(
        self,
        candle: pd.Series,
        positions: Dict[str, Position],
        equity: float,
        context: 'BacktestContext',
    ) -> List[Order]:
        lookback = context.lookback(self._sma_period)
        if len(lookback) < self._sma_period:
            return []

        sma = lookback['close'].mean()
        market = candle.get('market', 'ETH-USD')
        size = equity * 0.1 / candle['close']

        if candle['close'] > sma and market not in positions:
            return [Order(market=market, side=Side.BUY, size=size)]
        elif candle['close'] < sma and market in positions:
            pos = positions[market]
            return [Order(market=market, side=Side.SELL, size=abs(pos.size))]
        return []


def generate_synthetic_candles(n: int = 500) -> pd.DataFrame:
    """Generate synthetic price data with trend and mean-reversion."""
    np.random.seed(42)
    prices = [100.0]
    for _ in range(n - 1):
        ret = 0.0002 + np.random.randn() * 0.02  # slight upward drift
        prices.append(prices[-1] * (1 + ret))

    rows = []
    for i, p in enumerate(prices):
        noise = abs(np.random.randn() * 0.5)
        rows.append({
            'timestamp': float(1_000_000 + i * 3600),
            'open': p - noise,
            'high': p + abs(np.random.randn()),
            'low': p - abs(np.random.randn()),
            'close': p,
            'volume': np.random.uniform(100, 1000),
            'market': 'ETH-USD',
        })
    return pd.DataFrame(rows)


if __name__ == '__main__':
    print("=== Momentum Strategy Backtest ===\n")

    # Generate data (replace with API fetch for live data)
    candles = generate_synthetic_candles(500)
    print(f"Loaded {len(candles)} candles")
    print(f"Price range: ${candles['close'].min():.2f} - "
          f"${candles['close'].max():.2f}\n")

    # Configure and run
    config = BacktestConfig(
        initial_equity=10_000,
        taker_fee=0.001,
        slippage_bps=2.0,
    )
    bt = Backtester(config)
    bt.load_candles(candles)

    result = bt.run(MomentumStrategy(sma_period=20))

    # Print results
    print(f"Final equity:  ${result.final_equity:,.2f}")
    print(f"Total fills:   {len(result.fills)}")
    print()
    print("--- Performance Metrics ---")
    for key, val in result.metrics.items():
        if isinstance(val, float):
            if 'ratio' in key or 'return' in key or 'rate' in key or 'drawdown' in key:
                print(f"  {key:20s}: {val:+.4f}")
            else:
                print(f"  {key:20s}: {val:.4f}")
        else:
            print(f"  {key:20s}: {val}")
