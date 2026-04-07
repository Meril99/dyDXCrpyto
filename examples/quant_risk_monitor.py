"""Example: Risk monitor with circuit breakers.

Demonstrates:
    - Setting up risk limits
    - Computing risk snapshots
    - Circuit breaker triggers
    - Portfolio-level metrics

Usage:
    python examples/quant_risk_monitor.py
"""

from quant import RiskMonitor, RiskLimits
from quant.types import Position


def print_snapshot(snap, label: str = "") -> None:
    """Pretty-print a risk snapshot."""
    if label:
        print(f"\n--- {label} ---")
    print(f"  Equity:        ${snap.total_equity:,.2f}")
    print(f"  Exposure:      ${snap.total_exposure:,.2f}")
    print(f"  Net delta:     ${snap.net_delta:,.2f}")
    print(f"  Margin util:   {snap.margin_utilization:.1%}")
    print(f"  Drawdown:      {snap.max_drawdown:.2%}")
    print(f"  VaR (95%):     ${snap.var_95:,.2f}")
    if snap.breaker_triggered:
        print(f"  ** BREAKER:    {snap.breaker_reason}")
    else:
        print(f"  Status:        OK")


if __name__ == '__main__':
    print("=== Risk Monitor Demo ===")

    # Configure limits
    limits = RiskLimits(
        max_drawdown=0.10,          # 10% max drawdown
        max_position_size=2.0,      # max 2 BTC per market
        max_total_exposure=100_000, # $100k total exposure
        max_margin_utilization=5.0, # 5x leverage
        max_single_loss=1_000,      # $1k per-position loss limit
        var_limit_95=5_000,         # $5k 1-day VaR limit
    )
    rm = RiskMonitor(limits=limits)

    # --- Scenario 1: Healthy portfolio ---
    positions = {
        'BTC-USD': Position(
            market='BTC-USD', size=0.5,
            entry_price=50000, unrealized_pnl=250,
        ),
        'ETH-USD': Position(
            market='ETH-USD', size=5.0,
            entry_price=3000, unrealized_pnl=-100,
        ),
    }
    prices = {'BTC-USD': 50500.0, 'ETH-USD': 2980.0}
    snap = rm.compute_snapshot(positions, equity=50_000, prices=prices)
    print_snapshot(snap, "Scenario 1: Healthy Portfolio")

    # --- Scenario 2: Growing exposure ---
    positions['SOL-USD'] = Position(
        market='SOL-USD', size=100.0,
        entry_price=150, unrealized_pnl=500,
    )
    prices['SOL-USD'] = 155.0
    snap = rm.compute_snapshot(positions, equity=50_500, prices=prices)
    print_snapshot(snap, "Scenario 2: Added SOL Position")

    # --- Scenario 3: Market drawdown ---
    positions['BTC-USD'].unrealized_pnl = -3000
    positions['ETH-USD'].unrealized_pnl = -2000
    snap = rm.compute_snapshot(positions, equity=44_000, prices=prices)
    print_snapshot(snap, "Scenario 3: Market Drawdown")

    # --- Scenario 4: Recovery ---
    positions['BTC-USD'].unrealized_pnl = 1000
    positions['ETH-USD'].unrealized_pnl = 500
    snap = rm.compute_snapshot(positions, equity=52_000, prices=prices)
    print_snapshot(snap, "Scenario 4: Recovery")

    # --- Summary ---
    print(f"\n--- Circuit Breaker History ---")
    for event in rm.breaker_events:
        print(f"  [{event.reason}] "
              f"value={event.metric_value:.4f} "
              f"threshold={event.threshold:.4f}")
    if not rm.breaker_events:
        print("  No breakers triggered.")
