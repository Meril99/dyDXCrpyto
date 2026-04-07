"""Tests for quant/market_maker.py Avellaneda-Stoikov engine."""

import time

import numpy as np

from quant.market_maker import MarketMaker, MarketMakerConfig
from quant.types import Orderbook, OrderbookLevel, Side, Signal


def _make_orderbook(
    mid: float = 50000.0,
    spread: float = 10.0,
    size: float = 1.0,
) -> Orderbook:
    return Orderbook(
        bids=[OrderbookLevel(price=mid - spread / 2, size=size)],
        asks=[OrderbookLevel(price=mid + spread / 2, size=size)],
        timestamp=time.time(),
    )


class TestMarketMakerQuotes:

    def test_symmetric_quotes_zero_inventory(self):
        cfg = MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=1.0,
            gamma=0.1, k=1.5,
        )
        mm = MarketMaker(config=cfg)
        mm.update_orderbook(_make_orderbook())
        mm.update_volatility(sigma=0.2)

        bid, ask = mm.compute_quotes()

        # Both sides should have size
        assert bid.size > 0
        assert ask.size > 0
        # Ask should be above bid
        assert ask.price > bid.price
        # Quotes should be around mid
        assert abs((bid.price + ask.price) / 2 - 50000) < 1000

    def test_inventory_skew_long(self):
        cfg = MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=1.0,
            gamma=0.5, k=1.5,
        )
        mm = MarketMaker(config=cfg)
        mm.update_orderbook(_make_orderbook())
        mm.update_volatility(sigma=0.2)

        # Zero inventory
        mm.update_inventory(0.0)
        bid_neutral, ask_neutral = mm.compute_quotes()
        mid_neutral = (bid_neutral.price + ask_neutral.price) / 2

        # Long inventory — should skew quotes down
        mm.update_inventory(0.5)
        bid_long, ask_long = mm.compute_quotes()
        mid_long = (bid_long.price + ask_long.price) / 2

        assert mid_long < mid_neutral  # reservation price shifts down

    def test_inventory_skew_short(self):
        cfg = MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=1.0,
            gamma=0.5, k=1.5,
        )
        mm = MarketMaker(config=cfg)
        mm.update_orderbook(_make_orderbook())
        mm.update_volatility(sigma=0.2)

        mm.update_inventory(0.0)
        _, ask_neutral = mm.compute_quotes()
        mid_neutral = (mm.compute_quotes()[0].price + ask_neutral.price) / 2

        mm.update_inventory(-0.5)
        bid_short, ask_short = mm.compute_quotes()
        mid_short = (bid_short.price + ask_short.price) / 2

        assert mid_short > mid_neutral  # shifts up to attract sellers

    def test_max_inventory_blocks_side(self):
        cfg = MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=0.5,
        )
        mm = MarketMaker(config=cfg)
        mm.update_orderbook(_make_orderbook())
        mm.update_volatility(sigma=0.1)

        # At max long inventory — bid size should be zero
        mm.update_inventory(0.5)
        bid, ask = mm.compute_quotes()
        assert bid.size == 0.0
        assert ask.size > 0.0

        # At max short inventory — ask size should be zero
        mm.update_inventory(-0.5)
        bid, ask = mm.compute_quotes()
        assert bid.size > 0.0
        assert ask.size == 0.0


class TestSpreadBounds:

    def test_minimum_spread(self):
        cfg = MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=1.0,
            gamma=0.001, k=1.5, min_spread_bps=10.0,
        )
        mm = MarketMaker(config=cfg)
        mm.update_orderbook(_make_orderbook())
        mm.update_volatility(sigma=0.0001)  # very low vol

        bid, ask = mm.compute_quotes()
        spread_bps = (ask.price - bid.price) / 50000 * 1e4
        assert spread_bps >= 9.9  # at least min_spread_bps

    def test_maximum_spread(self):
        cfg = MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=1.0,
            gamma=10.0, k=0.01, max_spread_bps=50.0,
        )
        mm = MarketMaker(config=cfg)
        mm.update_orderbook(_make_orderbook())
        mm.update_volatility(sigma=10.0)  # extreme vol

        bid, ask = mm.compute_quotes()
        spread_bps = (ask.price - bid.price) / 50000 * 1e4
        assert spread_bps <= 51.0  # at most max_spread_bps (+ rounding)


class TestSignalIntegration:

    def test_positive_signal_shifts_up(self):
        cfg = MarketMakerConfig(
            market="BTC-USD", order_size=0.001, max_inventory=1.0,
            gamma=0.1, k=1.5, min_spread_bps=5.0,
        )
        mm = MarketMaker(config=cfg)
        mm.update_orderbook(_make_orderbook())
        mm.update_volatility(sigma=0.2)
        mm.update_inventory(0.0)

        bid_base, ask_base = mm.compute_quotes()

        mm.apply_signal(Signal(
            name="test", market="BTC-USD", value=1.0, timestamp=0,
        ))
        bid_sig, ask_sig = mm.compute_quotes()

        # Positive signal should shift quotes up
        assert bid_sig.price > bid_base.price
        assert ask_sig.price > ask_base.price
