"""Tests for quant/signals.py signal pipeline."""

import time

import numpy as np

from quant.signals import (
    CrossAssetMomentum,
    FundingRateMeanReversion,
    OrderbookImbalance,
    SignalCombiner,
    VolatilityRegime,
)
from quant.types import Orderbook, OrderbookLevel, Signal


class TestOrderbookImbalance:

    def test_all_bids(self):
        ob = Orderbook(
            bids=[OrderbookLevel(100, 10.0)],
            asks=[OrderbookLevel(101, 0.0)],
            timestamp=time.time(),
        )
        sig = OrderbookImbalance("BTC-USD", depth=5).compute(orderbook=ob)
        assert sig.value == 1.0

    def test_all_asks(self):
        ob = Orderbook(
            bids=[OrderbookLevel(100, 0.0)],
            asks=[OrderbookLevel(101, 10.0)],
            timestamp=time.time(),
        )
        sig = OrderbookImbalance("BTC-USD").compute(orderbook=ob)
        assert sig.value == -1.0

    def test_balanced(self):
        ob = Orderbook(
            bids=[OrderbookLevel(100, 5.0)],
            asks=[OrderbookLevel(101, 5.0)],
            timestamp=time.time(),
        )
        sig = OrderbookImbalance("BTC-USD").compute(orderbook=ob)
        assert sig.value == 0.0

    def test_no_orderbook(self):
        sig = OrderbookImbalance("BTC-USD").compute()
        assert sig.value == 0.0

    def test_output_range(self):
        ob = Orderbook(
            bids=[OrderbookLevel(100, 8.0)],
            asks=[OrderbookLevel(101, 2.0)],
            timestamp=time.time(),
        )
        sig = OrderbookImbalance("BTC-USD").compute(orderbook=ob)
        assert -1.0 <= sig.value <= 1.0


class TestFundingRateMeanReversion:

    def test_high_positive_funding_gives_sell(self):
        sig_gen = FundingRateMeanReversion("ETH-USD", threshold=0.0001)
        for _ in range(10):
            sig_gen.update(0.001)  # Very high positive funding
        sig = sig_gen.compute()
        assert sig.value < 0  # Expect sell signal

    def test_high_negative_funding_gives_buy(self):
        sig_gen = FundingRateMeanReversion("ETH-USD", threshold=0.0001)
        for _ in range(10):
            sig_gen.update(-0.001)
        sig = sig_gen.compute()
        assert sig.value > 0  # Expect buy signal

    def test_zero_funding_neutral(self):
        sig_gen = FundingRateMeanReversion("ETH-USD")
        for _ in range(10):
            sig_gen.update(0.0)
        sig = sig_gen.compute()
        assert abs(sig.value) < 0.01

    def test_no_history(self):
        sig = FundingRateMeanReversion("ETH-USD").compute()
        assert sig.value == 0.0


class TestCrossAssetMomentum:

    def test_insufficient_data(self):
        cam = CrossAssetMomentum(lookback=20)
        sig = cam.compute()
        assert sig.value == 0.0

    def test_leader_sudden_move_follower_lags(self):
        cam = CrossAssetMomentum(lookback=5, lag=1)
        np.random.seed(42)
        # Both assets flat, then leader has a sudden jump
        for i in range(25):
            cam.update(100 + np.random.randn() * 0.1,
                       50 + np.random.randn() * 0.1)
        # Leader jumps up sharply
        cam.update(100, 50)
        cam.update(103, 50)  # leader jumped, follower stayed
        sig = cam.compute()
        # Signal should be nonzero (divergence detected)
        assert sig.value != 0.0

    def test_output_bounded(self):
        cam = CrossAssetMomentum(lookback=5, lag=1)
        for i in range(30):
            cam.update(100 + i, 50 - i)
        sig = cam.compute()
        assert -1.0 <= sig.value <= 1.0


class TestVolatilityRegime:

    def test_insufficient_data(self):
        vr = VolatilityRegime("BTC-USD", short_window=5, long_window=20)
        sig = vr.compute()
        assert sig.metadata.get('regime') == 'INSUFFICIENT_DATA'

    def test_low_vol_regime(self):
        vr = VolatilityRegime("BTC-USD", short_window=5, long_window=50)
        # First add volatile data, then calm data
        for i in range(40):
            vr.update(100 + (-1) ** i * 5)  # high vol
        for i in range(20):
            vr.update(100 + i * 0.01)  # very low vol
        sig = vr.compute()
        assert sig.value >= 0  # LOW or NORMAL regime

    def test_output_bounded(self):
        vr = VolatilityRegime("BTC-USD", short_window=5, long_window=50)
        for i in range(60):
            vr.update(100 + i * 0.1)
        sig = vr.compute()
        assert -1.0 <= sig.value <= 1.0


class TestSignalCombiner:

    def test_equal_weights(self):
        combiner = SignalCombiner({'a': 1.0, 'b': 1.0})
        signals = [
            Signal(name='a', market='BTC-USD', value=1.0, timestamp=0),
            Signal(name='b', market='BTC-USD', value=-1.0, timestamp=0),
        ]
        result = combiner.combine(signals)
        assert abs(result.value) < 0.01  # cancels out

    def test_single_signal(self):
        combiner = SignalCombiner({'a': 1.0})
        signals = [
            Signal(name='a', market='BTC-USD', value=0.5, timestamp=0),
        ]
        result = combiner.combine(signals)
        assert abs(result.value - 0.5) < 0.01

    def test_weighted(self):
        combiner = SignalCombiner({'a': 3.0, 'b': 1.0})
        signals = [
            Signal(name='a', market='BTC-USD', value=1.0, timestamp=0),
            Signal(name='b', market='BTC-USD', value=-1.0, timestamp=0),
        ]
        result = combiner.combine(signals)
        # (3*1 + 1*(-1)) / (3+1) = 2/4 = 0.5
        assert abs(result.value - 0.5) < 0.01

    def test_output_clipped(self):
        combiner = SignalCombiner({'a': 1.0})
        signals = [
            Signal(name='a', market='BTC-USD', value=5.0, timestamp=0),
        ]
        result = combiner.combine(signals)
        assert result.value <= 1.0
