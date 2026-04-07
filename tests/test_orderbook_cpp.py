"""Tests for the C++ OrderBook engine.

These tests run against the compiled pybind11 module.
Skip gracefully if the module is not built.
"""

import pytest

try:
    import orderbook_cpp as ob
    HAS_CPP = True
except ImportError:
    HAS_CPP = False

pytestmark = pytest.mark.skipif(
    not HAS_CPP, reason="C++ orderbook module not built"
)


class TestAddAndCancel:

    def test_add_single_bid(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        assert book.order_count() == 1
        assert book.level_count(ob.BUY) == 1

    def test_add_single_ask(self):
        book = ob.OrderBook()
        book.add_order(1, ob.SELL, 101.0, 2.0)
        assert book.order_count() == 1
        assert book.level_count(ob.SELL) == 1

    def test_cancel_order(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        assert book.cancel_order(1) is True
        assert book.order_count() == 0
        assert book.level_count(ob.BUY) == 0

    def test_cancel_nonexistent(self):
        book = ob.OrderBook()
        assert book.cancel_order(999) is False

    def test_duplicate_id_raises(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        with pytest.raises(ValueError):
            book.add_order(1, ob.SELL, 101.0, 1.0)

    def test_negative_size_raises(self):
        book = ob.OrderBook()
        with pytest.raises(ValueError):
            book.add_order(1, ob.BUY, 100.0, -1.0)

    def test_multiple_orders_same_level(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        book.add_order(2, ob.BUY, 100.0, 2.0)
        assert book.order_count() == 2
        assert book.level_count(ob.BUY) == 1
        tob = book.top()
        assert tob.best_bid_size == 3.0

    def test_clear(self):
        book = ob.OrderBook()
        for i in range(100):
            book.add_order(i, ob.BUY, 100.0 - i * 0.1, 1.0)
        book.clear()
        assert book.order_count() == 0
        assert len(book) == 0


class TestModifyOrder:

    def test_modify_size_up(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        book.modify_order(1, 3.0)
        assert book.top().best_bid_size == 3.0

    def test_modify_size_down(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 5.0)
        book.modify_order(1, 2.0)
        assert book.top().best_bid_size == 2.0

    def test_modify_to_zero_cancels(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        book.modify_order(1, 0.0)
        assert book.order_count() == 0

    def test_modify_nonexistent(self):
        book = ob.OrderBook()
        assert book.modify_order(999, 1.0) is False


class TestTopOfBook:

    def test_empty_book(self):
        book = ob.OrderBook()
        tob = book.top()
        assert tob.mid_price == 0.0
        assert tob.spread == 0.0

    def test_bbo(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 99.0, 1.0)
        book.add_order(2, ob.BUY, 100.0, 2.0)
        book.add_order(3, ob.SELL, 101.0, 1.5)
        book.add_order(4, ob.SELL, 102.0, 3.0)

        tob = book.top()
        assert tob.best_bid == 100.0
        assert tob.best_bid_size == 2.0
        assert tob.best_ask == 101.0
        assert tob.best_ask_size == 1.5
        assert tob.spread == 1.0

    def test_mid_price(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        book.add_order(2, ob.SELL, 102.0, 1.0)
        assert book.top().mid_price == 101.0

    def test_micro_price(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 3.0)  # large bid
        book.add_order(2, ob.SELL, 102.0, 1.0)  # small ask
        tob = book.top()
        # micro = (100*1 + 102*3) / (3+1) = 406/4 = 101.5
        assert abs(tob.micro_price - 101.5) < 0.01


class TestDepth:

    def _build_book(self):
        book = ob.OrderBook()
        # 5 bid levels
        for i in range(5):
            book.add_order(i, ob.BUY, 100.0 - i, float(i + 1))
        # 5 ask levels
        for i in range(5):
            book.add_order(100 + i, ob.SELL, 101.0 + i, float(i + 1))
        return book

    def test_bid_depth_ordering(self):
        book = self._build_book()
        depth = book.bid_depth(3)
        assert len(depth) == 3
        # Highest bid first
        assert depth[0].price == 100.0
        assert depth[1].price == 99.0
        assert depth[2].price == 98.0

    def test_ask_depth_ordering(self):
        book = self._build_book()
        depth = book.ask_depth(3)
        assert len(depth) == 3
        # Lowest ask first
        assert depth[0].price == 101.0
        assert depth[1].price == 102.0

    def test_depth_sizes(self):
        book = self._build_book()
        depth = book.bid_depth(1)
        assert depth[0].size == 1.0  # order at 100.0 has size 1.0

    def test_depth_exceeds_levels(self):
        book = self._build_book()
        depth = book.bid_depth(100)
        assert len(depth) == 5  # only 5 levels exist


class TestVWAP:

    def test_single_level(self):
        book = ob.OrderBook()
        book.add_order(1, ob.SELL, 100.0, 10.0)
        assert book.vwap(ob.BUY, 5.0) == 100.0

    def test_multi_level(self):
        book = ob.OrderBook()
        book.add_order(1, ob.SELL, 100.0, 2.0)
        book.add_order(2, ob.SELL, 101.0, 3.0)
        # Buy 5 units: 2@100 + 3@101 = 200+303 = 503, /5 = 100.6
        vwap = book.vwap(ob.BUY, 5.0)
        assert abs(vwap - 100.6) < 0.01

    def test_partial_level(self):
        book = ob.OrderBook()
        book.add_order(1, ob.SELL, 100.0, 10.0)
        book.add_order(2, ob.SELL, 101.0, 10.0)
        # Buy 3: all from first level
        assert book.vwap(ob.BUY, 3.0) == 100.0

    def test_empty_book(self):
        book = ob.OrderBook()
        assert book.vwap(ob.BUY, 1.0) == 0.0


class TestImbalance:

    def test_all_bids(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 10.0)
        # No asks, but imbalance needs both sides
        # With only bids: bid_vol=10, ask_vol=0 => 1.0
        assert book.imbalance(5) == 1.0

    def test_balanced(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 5.0)
        book.add_order(2, ob.SELL, 101.0, 5.0)
        assert abs(book.imbalance(5)) < 0.01

    def test_heavy_asks(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        book.add_order(2, ob.SELL, 101.0, 9.0)
        # (1-9)/(1+9) = -0.8
        assert abs(book.imbalance(5) - (-0.8)) < 0.01

    def test_empty_book(self):
        book = ob.OrderBook()
        assert book.imbalance(5) == 0.0


class TestRepr:

    def test_orderbook_repr(self):
        book = ob.OrderBook()
        s = repr(book)
        assert "OrderBook" in s

    def test_top_repr(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        s = repr(book.top())
        assert "TopOfBook" in s

    def test_depth_repr(self):
        book = ob.OrderBook()
        book.add_order(1, ob.BUY, 100.0, 1.0)
        depth = book.bid_depth(1)
        s = repr(depth[0])
        assert "DepthLevel" in s
