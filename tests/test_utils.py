"""Tests for quant/utils.py numerical utilities."""

import numpy as np

from quant.utils import (
    clip_signal,
    max_drawdown,
    mid_price_from_orderbook,
    realized_volatility,
    sharpe_ratio,
    sortino_ratio,
)
from quant.types import OrderbookLevel


class TestRealizedVolatility:

    def test_constant_prices_zero_vol(self):
        prices = np.array([100.0] * 25)
        vol = realized_volatility(prices, window=20, annualize=False)
        assert vol[-1] == 0.0

    def test_increasing_prices_positive_vol(self):
        prices = np.arange(1.0, 30.0)
        vol = realized_volatility(prices, window=10, annualize=False)
        assert vol[-1] > 0.0

    def test_nan_padding(self):
        prices = np.arange(1.0, 30.0)
        vol = realized_volatility(prices, window=20, annualize=False)
        assert np.isnan(vol[0])
        assert not np.isnan(vol[-1])

    def test_length_matches_input(self):
        prices = np.arange(1.0, 50.0)
        vol = realized_volatility(prices, window=10)
        assert len(vol) == len(prices)


class TestMidPrice:

    def test_simple_mid(self):
        bids = [OrderbookLevel(price=100.0, size=1.0)]
        asks = [OrderbookLevel(price=102.0, size=1.0)]
        # Equal sizes => simple mid
        mid = mid_price_from_orderbook(bids, asks)
        assert mid == 101.0

    def test_size_weighted(self):
        bids = [OrderbookLevel(price=100.0, size=3.0)]
        asks = [OrderbookLevel(price=102.0, size=1.0)]
        # micro = (100*1 + 102*3) / (3+1) = 406/4 = 101.5
        mid = mid_price_from_orderbook(bids, asks)
        assert mid == 101.5

    def test_empty_asks(self):
        bids = [OrderbookLevel(price=100.0, size=1.0)]
        mid = mid_price_from_orderbook(bids, [])
        assert mid == 100.0

    def test_empty_both(self):
        assert mid_price_from_orderbook([], []) == 0.0


class TestSharpeRatio:

    def test_positive_returns(self):
        # Need some variance for meaningful Sharpe
        np.random.seed(0)
        returns = 0.001 + np.random.randn(100) * 0.005
        s = sharpe_ratio(returns)
        assert s > 0

    def test_zero_returns(self):
        returns = np.array([0.0] * 100)
        assert sharpe_ratio(returns) == 0.0

    def test_single_return(self):
        assert sharpe_ratio(np.array([0.01])) == 0.0


class TestSortinoRatio:

    def test_no_downside(self):
        returns = np.array([0.01] * 100)
        assert sortino_ratio(returns) == float('inf')

    def test_with_downside(self):
        returns = np.array([0.01, -0.02, 0.01, -0.01, 0.02])
        s = sortino_ratio(returns)
        assert isinstance(s, float)


class TestMaxDrawdown:

    def test_no_drawdown(self):
        equity = np.array([100, 110, 120, 130])
        assert max_drawdown(equity) == 0.0

    def test_known_drawdown(self):
        equity = np.array([100, 110, 88, 95])
        dd = max_drawdown(equity)
        assert abs(dd - 0.2) < 0.01  # 20% dd from 110 to 88

    def test_single_point(self):
        assert max_drawdown(np.array([100])) == 0.0


class TestClipSignal:

    def test_within_range(self):
        assert clip_signal(0.5) == 0.5

    def test_above_range(self):
        assert clip_signal(2.0) == 1.0

    def test_below_range(self):
        assert clip_signal(-3.0) == -1.0
