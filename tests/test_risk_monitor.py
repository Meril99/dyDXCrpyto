"""Tests for quant/risk_monitor.py risk monitoring and circuit breakers."""

from quant.risk_monitor import CircuitBreakerEvent, RiskLimits, RiskMonitor
from quant.types import Position


class TestRiskSnapshot:

    def test_no_positions(self):
        rm = RiskMonitor(limits=RiskLimits())
        snap = rm.compute_snapshot({}, equity=10_000)

        assert snap.total_equity == 10_000
        assert snap.total_exposure == 0.0
        assert snap.net_delta == 0.0
        assert snap.margin_utilization == 0.0
        assert snap.breaker_triggered is False

    def test_single_long_position(self):
        rm = RiskMonitor()
        positions = {
            'BTC-USD': Position(
                market='BTC-USD', size=1.0,
                entry_price=50000, unrealized_pnl=500,
            ),
        }
        prices = {'BTC-USD': 50500.0}
        snap = rm.compute_snapshot(positions, equity=10_000, prices=prices)

        assert snap.total_exposure == 50500.0
        assert snap.net_delta == 50500.0
        assert snap.margin_utilization > 0

    def test_long_and_short(self):
        rm = RiskMonitor()
        positions = {
            'BTC-USD': Position(
                market='BTC-USD', size=1.0,
                entry_price=50000, unrealized_pnl=0,
            ),
            'ETH-USD': Position(
                market='ETH-USD', size=-10.0,
                entry_price=3000, unrealized_pnl=0,
            ),
        }
        prices = {'BTC-USD': 50000.0, 'ETH-USD': 3000.0}
        snap = rm.compute_snapshot(positions, equity=10_000, prices=prices)

        assert snap.total_exposure == 50000 + 30000  # sum of abs
        assert snap.net_delta == 50000 - 30000  # signed


class TestDrawdown:

    def test_drawdown_from_peak(self):
        rm = RiskMonitor()
        rm.compute_snapshot({}, equity=10_000)
        rm.compute_snapshot({}, equity=11_000)  # peak
        snap = rm.compute_snapshot({}, equity=9_900)

        expected_dd = (11_000 - 9_900) / 11_000
        assert abs(snap.max_drawdown - expected_dd) < 0.001

    def test_no_drawdown_if_increasing(self):
        rm = RiskMonitor()
        rm.compute_snapshot({}, equity=10_000)
        snap = rm.compute_snapshot({}, equity=11_000)
        assert snap.max_drawdown == 0.0


class TestCircuitBreakers:

    def test_drawdown_breaker(self):
        limits = RiskLimits(max_drawdown=0.05)
        rm = RiskMonitor(limits=limits)

        rm.compute_snapshot({}, equity=10_000)
        snap = rm.compute_snapshot({}, equity=9_000)  # 10% dd

        assert snap.breaker_triggered is True
        assert 'Drawdown' in snap.breaker_reason

    def test_exposure_breaker(self):
        limits = RiskLimits(max_total_exposure=10_000)
        rm = RiskMonitor(limits=limits)

        positions = {
            'BTC-USD': Position(
                market='BTC-USD', size=1.0,
                entry_price=50000, unrealized_pnl=0,
            ),
        }
        prices = {'BTC-USD': 50000.0}
        snap = rm.compute_snapshot(positions, equity=100_000, prices=prices)

        assert snap.breaker_triggered is True
        assert 'Exposure' in snap.breaker_reason

    def test_margin_breaker(self):
        limits = RiskLimits(max_margin_utilization=0.5)
        rm = RiskMonitor(limits=limits)

        positions = {
            'BTC-USD': Position(
                market='BTC-USD', size=1.0,
                entry_price=50000, unrealized_pnl=0,
            ),
        }
        prices = {'BTC-USD': 50000.0}
        snap = rm.compute_snapshot(positions, equity=10_000, prices=prices)
        # margin_util = 50000/10000 = 5.0 >> 0.5
        assert snap.breaker_triggered is True

    def test_position_size_breaker(self):
        limits = RiskLimits(max_position_size=0.5)
        rm = RiskMonitor(limits=limits)

        positions = {
            'BTC-USD': Position(
                market='BTC-USD', size=1.0,
                entry_price=50000, unrealized_pnl=0,
            ),
        }
        snap = rm.compute_snapshot(positions, equity=100_000)
        assert snap.breaker_triggered is True

    def test_single_loss_breaker(self):
        limits = RiskLimits(max_single_loss=100)
        rm = RiskMonitor(limits=limits)

        positions = {
            'BTC-USD': Position(
                market='BTC-USD', size=1.0,
                entry_price=50000, unrealized_pnl=-500,
            ),
        }
        snap = rm.compute_snapshot(positions, equity=10_000)
        assert snap.breaker_triggered is True

    def test_no_breaker_within_limits(self):
        limits = RiskLimits(
            max_drawdown=0.5, max_total_exposure=1_000_000,
            max_margin_utilization=10.0, max_position_size=100,
            max_single_loss=10_000, var_limit_95=100_000,
        )
        rm = RiskMonitor(limits=limits)
        rm.compute_snapshot({}, equity=10_000)
        snap = rm.compute_snapshot({}, equity=10_000)
        assert snap.breaker_triggered is False

    def test_breaker_event_logged(self):
        limits = RiskLimits(max_drawdown=0.01)
        rm = RiskMonitor(limits=limits)

        rm.compute_snapshot({}, equity=10_000)
        rm.compute_snapshot({}, equity=9_800)

        assert len(rm.breaker_events) == 1
        assert isinstance(rm.breaker_events[0], CircuitBreakerEvent)


class TestVaR:

    def test_parametric_fallback(self):
        rm = RiskMonitor()
        snap = rm.compute_snapshot({}, equity=10_000)
        # With < 20 observations, uses parametric: equity * 0.02 * 1.645
        expected = 10_000 * 0.02 * 1.645
        assert abs(snap.var_95 - expected) < 1.0

    def test_historical_var(self):
        rm = RiskMonitor()
        # Feed enough equity history
        for i in range(30):
            rm.compute_snapshot({}, equity=10_000 + i * 10)
        snap = rm.compute_snapshot({}, equity=10_300)
        assert snap.var_95 >= 0


class TestReset:

    def test_reset_clears_state(self):
        rm = RiskMonitor()
        rm.compute_snapshot({}, equity=10_000)
        rm.compute_snapshot({}, equity=9_000)
        assert len(rm.breaker_events) > 0 or rm._peak_equity > 0

        rm.reset()
        assert rm._peak_equity == 0.0
        assert len(rm._equity_history) == 0
        assert len(rm.breaker_events) == 0
