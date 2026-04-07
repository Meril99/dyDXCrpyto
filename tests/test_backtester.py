"""Tests for quant/backtester.py backtesting framework."""

from typing import Dict, List

import numpy as np
import pandas as pd

from quant.backtester import Backtester, BacktestConfig, BacktestContext, Strategy
from quant.types import Fill, Order, Position, Side


def _make_candles(n: int = 50, start_price: float = 100.0) -> pd.DataFrame:
    """Generate synthetic candle data with a slight uptrend."""
    np.random.seed(42)
    prices = start_price + np.cumsum(np.random.randn(n) * 0.5)
    prices = np.maximum(prices, 1.0)  # no negative prices
    rows = []
    for i in range(n):
        p = prices[i]
        rows.append({
            'timestamp': float(1000000 + i * 3600),
            'open': p - 0.5,
            'high': p + 1.0,
            'low': p - 1.0,
            'close': p,
            'volume': 100.0,
            'market': 'BTC-USD',
        })
    return pd.DataFrame(rows)


class BuyAndHoldStrategy(Strategy):
    """Buy on first candle, hold forever."""
    def __init__(self) -> None:
        self._bought = False

    def on_candle(
        self, candle: pd.Series, positions: Dict[str, Position],
        equity: float, context: BacktestContext,
    ) -> List[Order]:
        if not self._bought:
            self._bought = True
            return [Order(
                market='BTC-USD', side=Side.BUY,
                size=1.0,
            )]
        return []


class AlwaysBuySellStrategy(Strategy):
    """Buy then sell on alternating candles."""
    def __init__(self) -> None:
        self._i = 0

    def on_candle(
        self, candle: pd.Series, positions: Dict[str, Position],
        equity: float, context: BacktestContext,
    ) -> List[Order]:
        self._i += 1
        if self._i % 4 == 1:
            return [Order(market='BTC-USD', side=Side.BUY, size=0.1)]
        elif self._i % 4 == 3 and 'BTC-USD' in positions:
            return [Order(market='BTC-USD', side=Side.SELL, size=0.1)]
        return []


class TestBacktester:

    def test_buy_and_hold(self):
        df = _make_candles(50)
        bt = Backtester(BacktestConfig(initial_equity=10_000))
        bt.load_candles(df)
        result = bt.run(BuyAndHoldStrategy())

        assert result.candles_count == 50
        assert len(result.fills) == 1
        assert len(result.equity_curve) == 50
        assert result.final_equity != 10_000  # price changed

    def test_round_trip(self):
        df = _make_candles(50)
        bt = Backtester(BacktestConfig(initial_equity=10_000))
        bt.load_candles(df)
        result = bt.run(AlwaysBuySellStrategy())

        assert len(result.fills) > 1
        assert result.metrics['total_fills'] > 0

    def test_metrics_present(self):
        df = _make_candles(50)
        bt = Backtester(BacktestConfig(initial_equity=10_000))
        bt.load_candles(df)
        result = bt.run(AlwaysBuySellStrategy())

        assert 'sharpe_ratio' in result.metrics
        assert 'sortino_ratio' in result.metrics
        assert 'max_drawdown' in result.metrics
        assert 'total_return' in result.metrics
        assert 'win_rate' in result.metrics

    def test_equity_curve_length(self):
        df = _make_candles(30)
        bt = Backtester()
        bt.load_candles(df)
        result = bt.run(BuyAndHoldStrategy())
        assert len(result.equity_curve) == 30
        assert len(result.timestamps) == 30

    def test_missing_columns_raises(self):
        df = pd.DataFrame({'timestamp': [1], 'open': [1]})
        bt = Backtester()
        try:
            bt.load_candles(df)
            assert False, "Should have raised"
        except ValueError:
            pass

    def test_no_data_raises(self):
        bt = Backtester()
        try:
            bt.run(BuyAndHoldStrategy())
            assert False, "Should have raised"
        except ValueError:
            pass


class TestFillSimulation:

    def test_limit_order_fills_within_range(self):
        df = _make_candles(10)
        cfg = BacktestConfig(initial_equity=10_000)
        bt = Backtester(cfg)
        bt.load_candles(df)

        class LimitBuyStrategy(Strategy):
            def on_candle(self, candle, positions, equity, context):
                if context.current_index == 0:
                    # Place limit buy below the low — should NOT fill
                    return [Order(
                        market='BTC-USD', side=Side.BUY,
                        size=0.1, price=candle['low'] - 10,
                    )]
                return []

        result = bt.run(LimitBuyStrategy())
        assert len(result.fills) == 0  # limit never reached

    def test_market_order_always_fills(self):
        df = _make_candles(10)
        bt = Backtester(BacktestConfig(initial_equity=10_000))
        bt.load_candles(df)

        class MarketBuyStrategy(Strategy):
            def on_candle(self, candle, positions, equity, context):
                if context.current_index == 0:
                    return [Order(market='BTC-USD', side=Side.BUY, size=0.1)]
                return []

        result = bt.run(MarketBuyStrategy())
        assert len(result.fills) == 1
