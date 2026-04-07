"""Benchmark: C++ OrderBook vs pure Python OrderBook.

Measures throughput for add/cancel/query operations.

Usage:
    python cpp/benchmark.py
"""

from __future__ import annotations

import random
import time
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Pure Python OrderBook (baseline)
# ============================================================

class PythonOrderBook:
    """Minimal Python orderbook for benchmarking."""

    def __init__(self):
        self.bids = {}  # price -> total_size
        self.asks = {}
        self.orders = {}  # id -> (side, price, size)

    def add_order(self, oid, side, price, size):
        self.orders[oid] = (side, price, size)
        book = self.bids if side == 'BUY' else self.asks
        book[price] = book.get(price, 0.0) + size

    def cancel_order(self, oid):
        if oid not in self.orders:
            return False
        side, price, size = self.orders.pop(oid)
        book = self.bids if side == 'BUY' else self.asks
        book[price] -= size
        if book[price] <= 1e-12:
            del book[price]
        return True

    def top(self):
        best_bid = max(self.bids.keys()) if self.bids else 0
        best_ask = min(self.asks.keys()) if self.asks else float('inf')
        return best_bid, best_ask

    def imbalance(self, depth=10):
        bid_prices = sorted(self.bids.keys(), reverse=True)[:depth]
        ask_prices = sorted(self.asks.keys())[:depth]
        bid_vol = sum(self.bids[p] for p in bid_prices)
        ask_vol = sum(self.asks[p] for p in ask_prices)
        total = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total if total > 0 else 0


# ============================================================
# Benchmark runner
# ============================================================

def bench_python(n_orders: int, n_queries: int) -> dict:
    """Benchmark the pure Python orderbook."""
    ob = PythonOrderBook()
    random.seed(42)

    # Generate orders
    orders = []
    for i in range(n_orders):
        side = 'BUY' if random.random() < 0.5 else 'SELL'
        base = 50000
        offset = random.gauss(0, 50)
        price = round(base + offset if side == 'BUY' else base - offset, 2)
        size = round(random.uniform(0.01, 5.0), 4)
        orders.append((i, side, abs(price), size))

    # Benchmark adds
    t0 = time.perf_counter()
    for oid, side, price, size in orders:
        ob.add_order(oid, side, price, size)
    add_time = time.perf_counter() - t0

    # Benchmark queries
    t0 = time.perf_counter()
    for _ in range(n_queries):
        ob.top()
        ob.imbalance(10)
    query_time = time.perf_counter() - t0

    # Benchmark cancels
    cancel_ids = random.sample(range(n_orders), n_orders // 2)
    t0 = time.perf_counter()
    for oid in cancel_ids:
        ob.cancel_order(oid)
    cancel_time = time.perf_counter() - t0

    return {
        'add_time': add_time,
        'cancel_time': cancel_time,
        'query_time': query_time,
        'add_rate': n_orders / add_time,
        'cancel_rate': len(cancel_ids) / cancel_time,
        'query_rate': n_queries / query_time,
    }


def bench_cpp(n_orders: int, n_queries: int) -> dict:
    """Benchmark the C++ orderbook."""
    try:
        import orderbook_cpp as ob_mod
    except ImportError:
        print("C++ module not found. Build it first: cd cpp && ./build.sh")
        return {}

    ob = ob_mod.OrderBook()
    random.seed(42)

    orders = []
    for i in range(n_orders):
        side = ob_mod.BUY if random.random() < 0.5 else ob_mod.SELL
        base = 50000
        offset = random.gauss(0, 50)
        price = round(base + offset if side == ob_mod.BUY else base - offset, 2)
        size = round(random.uniform(0.01, 5.0), 4)
        orders.append((i, side, abs(price), size))

    # Benchmark adds
    t0 = time.perf_counter()
    for oid, side, price, size in orders:
        ob.add_order(oid, side, price, size)
    add_time = time.perf_counter() - t0

    # Benchmark queries
    t0 = time.perf_counter()
    for _ in range(n_queries):
        ob.top()
        ob.imbalance(10)
    query_time = time.perf_counter() - t0

    # Benchmark cancels
    cancel_ids = random.sample(range(n_orders), n_orders // 2)
    t0 = time.perf_counter()
    for oid in cancel_ids:
        ob.cancel_order(oid)
    cancel_time = time.perf_counter() - t0

    return {
        'add_time': add_time,
        'cancel_time': cancel_time,
        'query_time': query_time,
        'add_rate': n_orders / add_time,
        'cancel_rate': len(cancel_ids) / cancel_time,
        'query_rate': n_queries / query_time,
    }


def format_rate(rate: float) -> str:
    if rate >= 1e6:
        return f"{rate / 1e6:.1f}M"
    elif rate >= 1e3:
        return f"{rate / 1e3:.1f}K"
    return f"{rate:.0f}"


if __name__ == '__main__':
    N_ORDERS = 100_000
    N_QUERIES = 50_000

    print(f"=== OrderBook Benchmark ===")
    print(f"Orders: {N_ORDERS:,}  |  Queries: {N_QUERIES:,}")
    print()

    # Python baseline
    print("Running Python baseline...")
    py_results = bench_python(N_ORDERS, N_QUERIES)
    print(f"  Add:    {py_results['add_time']:.3f}s "
          f"({format_rate(py_results['add_rate'])} ops/s)")
    print(f"  Cancel: {py_results['cancel_time']:.3f}s "
          f"({format_rate(py_results['cancel_rate'])} ops/s)")
    print(f"  Query:  {py_results['query_time']:.3f}s "
          f"({format_rate(py_results['query_rate'])} ops/s)")
    print()

    # C++ implementation
    print("Running C++ implementation...")
    cpp_results = bench_cpp(N_ORDERS, N_QUERIES)
    if cpp_results:
        print(f"  Add:    {cpp_results['add_time']:.3f}s "
              f"({format_rate(cpp_results['add_rate'])} ops/s)")
        print(f"  Cancel: {cpp_results['cancel_time']:.3f}s "
              f"({format_rate(cpp_results['cancel_rate'])} ops/s)")
        print(f"  Query:  {cpp_results['query_time']:.3f}s "
              f"({format_rate(cpp_results['query_rate'])} ops/s)")
        print()

        # Speedup
        print("--- Speedup (C++ / Python) ---")
        print(f"  Add:    {py_results['add_rate'] and cpp_results['add_rate'] / py_results['add_rate']:.1f}x")
        print(f"  Cancel: {py_results['cancel_rate'] and cpp_results['cancel_rate'] / py_results['cancel_rate']:.1f}x")
        print(f"  Query:  {py_results['query_rate'] and cpp_results['query_rate'] / py_results['query_rate']:.1f}x")
    else:
        print("  Skipped (module not built)")
