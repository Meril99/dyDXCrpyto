"""Example: Avellaneda-Stoikov market maker on BTC-USD.

Demonstrates:
    - Configuring the market maker
    - Feeding orderbook data
    - Computing optimal quotes with inventory skewing
    - Integrating signals for directional bias

Usage:
    python examples/quant_market_maker.py

Note: This example uses synthetic data. For live trading,
replace with real API client and orderbook feeds.
"""

import time

from quant import (
    MarketMaker,
    MarketMakerConfig,
    OrderbookImbalance,
    FundingRateMeanReversion,
    SignalCombiner,
)
from quant.types import Orderbook, OrderbookLevel, Signal


def simulate_orderbook(mid: float, spread: float = 10.0) -> Orderbook:
    """Create a synthetic orderbook around a mid price."""
    return Orderbook(
        bids=[
            OrderbookLevel(price=mid - spread / 2, size=2.0),
            OrderbookLevel(price=mid - spread, size=5.0),
            OrderbookLevel(price=mid - spread * 1.5, size=8.0),
        ],
        asks=[
            OrderbookLevel(price=mid + spread / 2, size=1.5),
            OrderbookLevel(price=mid + spread, size=4.0),
            OrderbookLevel(price=mid + spread * 1.5, size=7.0),
        ],
        timestamp=time.time(),
    )


if __name__ == '__main__':
    print("=== Avellaneda-Stoikov Market Maker Demo ===\n")

    # Configure
    config = MarketMakerConfig(
        market="BTC-USD",
        order_size=0.001,      # 0.001 BTC per side
        max_inventory=0.01,    # max 0.01 BTC position
        gamma=0.1,             # risk aversion
        k=1.5,                 # order arrival intensity
        min_spread_bps=5.0,
        max_spread_bps=50.0,
    )
    mm = MarketMaker(config=config)  # no client = dry run

    # Set up signals
    ob_signal = OrderbookImbalance("BTC-USD", depth=3)
    funding_signal = FundingRateMeanReversion("BTC-USD", threshold=0.0001)
    combiner = SignalCombiner({
        ob_signal.name: 0.3,
        funding_signal.name: 0.7,
    })

    print(f"Market:         {config.market}")
    print(f"Order size:     {config.order_size} BTC")
    print(f"Max inventory:  {config.max_inventory} BTC")
    print(f"Risk aversion:  {config.gamma}")
    print(f"Min spread:     {config.min_spread_bps} bps")
    print()

    # Simulate a few quoting cycles
    mid_prices = [50000, 50050, 49980, 50100, 50020]
    inventories = [0.0, 0.001, 0.003, 0.003, -0.002]
    funding_rates = [0.0001, 0.0002, 0.0003, -0.0001, 0.0]

    for i, (mid, inv, fr) in enumerate(
        zip(mid_prices, inventories, funding_rates)
    ):
        print(f"--- Cycle {i + 1} ---")
        print(f"  Mid price:  ${mid:,.2f}")
        print(f"  Inventory:  {inv:+.4f} BTC")
        print(f"  Funding:    {fr:+.5f}")

        # Update state
        ob = simulate_orderbook(mid)
        mm.update_orderbook(ob)
        mm.update_volatility(sigma=0.15)
        mm.update_inventory(inv)

        # Compute signals
        ob_sig = ob_signal.compute(orderbook=ob)
        funding_signal.update(fr)
        fr_sig = funding_signal.compute()
        composite = combiner.combine([ob_sig, fr_sig])
        mm.apply_signal(composite)

        print(f"  OB signal:  {ob_sig.value:+.3f}")
        print(f"  FR signal:  {fr_sig.value:+.3f}")
        print(f"  Composite:  {composite.value:+.3f}")

        # Compute quotes
        bid, ask = mm.compute_quotes()
        spread_bps = (ask.price - bid.price) / mid * 1e4

        print(f"  Bid:        ${bid.price:,.2f} x {bid.size}")
        print(f"  Ask:        ${ask.price:,.2f} x {ask.size}")
        print(f"  Spread:     {spread_bps:.1f} bps")
        print()
