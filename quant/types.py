"""Shared data types for the quantitative trading toolkit."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class Side(enum.Enum):
    """Order/position side."""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Candle:
    """OHLCV candle."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    market: str = ""
    resolution: str = ""


@dataclass
class OrderbookLevel:
    """Single price level in an orderbook."""
    price: float
    size: float


@dataclass
class Orderbook:
    """L2 orderbook snapshot."""
    bids: List[OrderbookLevel]
    asks: List[OrderbookLevel]
    timestamp: float


@dataclass
class Signal:
    """Normalized signal output in [-1, 1]."""
    name: str
    market: str
    value: float
    timestamp: float
    metadata: Dict[str, float] = field(default_factory=dict)


@dataclass
class Fill:
    """A simulated or real trade fill."""
    market: str
    side: Side
    price: float
    size: float
    fee: float
    timestamp: float
    is_maker: bool = False


@dataclass
class Position:
    """Tracks an open position."""
    market: str
    size: float              # positive = long, negative = short
    entry_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    funding_payments: float = 0.0


@dataclass
class Order:
    """Order submitted by a strategy during backtesting."""
    market: str
    side: Side
    size: float
    price: Optional[float] = None   # None = market order (fill at close)
    is_maker: bool = False


@dataclass
class QuoteOrder:
    """A single quote (one side of a market-maker's pair)."""
    market: str
    side: Side
    price: float
    size: float
    client_id: Optional[str] = None
    order_id: Optional[str] = None


@dataclass
class BacktestResult:
    """Complete output of a backtest run."""
    equity_curve: List[float]
    timestamps: List[float]
    fills: List[Fill]
    positions: Dict[str, Position]
    metrics: Dict[str, float]
    candles_count: int
    final_equity: float


@dataclass
class RiskSnapshot:
    """Point-in-time risk assessment."""
    timestamp: float
    total_equity: float
    total_exposure: float
    net_delta: float
    margin_utilization: float
    var_95: float
    max_drawdown: float
    positions: Dict[str, Position]
    breaker_triggered: bool
    breaker_reason: Optional[str] = None
