"""Example: Signal pipeline with all four signal types.

Demonstrates:
    - Creating and feeding each signal type
    - Combining signals with weighted aggregation
    - Inspecting signal metadata

Usage:
    python examples/quant_signals.py
"""

import time

import numpy as np

from quant import (
    OrderbookImbalance,
    FundingRateMeanReversion,
    CrossAssetMomentum,
    VolatilityRegime,
    SignalCombiner,
)
from quant.types import Orderbook, OrderbookLevel


if __name__ == '__main__':
    print("=== Signal Pipeline Demo ===\n")
    np.random.seed(42)

    # --- Signal 1: Orderbook Imbalance ---
    print("1. Orderbook Imbalance")
    ob_signal = OrderbookImbalance("BTC-USD", depth=5)
    ob = Orderbook(
        bids=[
            OrderbookLevel(50000 - i * 5, np.random.uniform(0.5, 3.0))
            for i in range(5)
        ],
        asks=[
            OrderbookLevel(50000 + i * 5, np.random.uniform(0.1, 1.0))
            for i in range(5)
        ],
        timestamp=time.time(),
    )
    sig1 = ob_signal.compute(orderbook=ob)
    print(f"   Value: {sig1.value:+.3f} (positive = more bids)")
    print(f"   Bid vol: {sig1.metadata['bid_vol']:.2f}, "
          f"Ask vol: {sig1.metadata['ask_vol']:.2f}")
    print()

    # --- Signal 2: Funding Rate Mean Reversion ---
    print("2. Funding Rate Mean Reversion")
    fr_signal = FundingRateMeanReversion("ETH-USD", threshold=0.0001)
    # Simulate rising positive funding (overheated long market)
    for rate in [0.0001, 0.0002, 0.0003, 0.0005, 0.0008]:
        fr_signal.update(rate)
    sig2 = fr_signal.compute()
    print(f"   Value: {sig2.value:+.3f} (negative = expect price drop)")
    print(f"   Avg funding: {sig2.metadata['avg_funding']:.6f}")
    print()

    # --- Signal 3: Cross-Asset Momentum ---
    print("3. Cross-Asset Momentum (BTC leads ETH)")
    cam = CrossAssetMomentum(
        leader_market="BTC-USD",
        follower_market="ETH-USD",
        lookback=10,
        lag=1,
    )
    btc_prices = 50000 + np.cumsum(np.random.randn(30) * 100)
    eth_prices = 3000 + np.cumsum(np.random.randn(30) * 20)
    for bp, ep in zip(btc_prices, eth_prices):
        cam.update(bp, ep)
    sig3 = cam.compute()
    print(f"   Value: {sig3.value:+.3f}")
    print(f"   Leader Z: {sig3.metadata.get('leader_z', 0):.3f}, "
          f"Follower Z: {sig3.metadata.get('follower_z', 0):.3f}")
    print()

    # --- Signal 4: Volatility Regime ---
    print("4. Volatility Regime Detection")
    vr = VolatilityRegime("BTC-USD", short_window=10, long_window=50)
    # Feed price history with a calm period
    prices = 50000 + np.cumsum(np.random.randn(70) * 50)
    for p in prices:
        vr.update(p)
    sig4 = vr.compute()
    print(f"   Value: {sig4.value:+.3f}")
    print(f"   Regime: {sig4.metadata.get('regime', 'N/A')}")
    print(f"   Vol percentile: {sig4.metadata.get('percentile', 0):.1%}")
    print()

    # --- Combine all signals ---
    print("5. Composite Signal")
    combiner = SignalCombiner({
        sig1.name: 0.2,   # orderbook imbalance
        sig2.name: 0.3,   # funding rate
        sig3.name: 0.2,   # cross-asset momentum
        sig4.name: 0.3,   # volatility regime
    })
    composite = combiner.combine([sig1, sig2, sig3, sig4])
    print(f"   Value: {composite.value:+.3f}")
    print(f"   Components: {composite.metadata}")
