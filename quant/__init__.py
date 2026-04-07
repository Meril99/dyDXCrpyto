"""dYdX v3 Quantitative Trading Toolkit.

Components:
    - MarketMaker: Avellaneda-Stoikov market-making engine
    - Backtester / Strategy: Vectorized backtesting framework
    - Signals: Orderbook imbalance, funding rate MR, cross-asset momentum, vol regime
    - RiskMonitor: Real-time risk tracking with circuit breakers
"""

from quant.types import (
    BacktestResult,
    Candle,
    Fill,
    Orderbook,
    OrderbookLevel,
    Order,
    Position,
    QuoteOrder,
    RiskSnapshot,
    Signal,
    Side,
)
from quant.signals import (
    BaseSignal,
    CrossAssetMomentum,
    FundingRateMeanReversion,
    OrderbookImbalance,
    SignalCombiner,
    VolatilityRegime,
)
from quant.backtester import Backtester, BacktestConfig, Strategy
from quant.market_maker import MarketMaker, MarketMakerConfig
from quant.risk_monitor import RiskMonitor, RiskLimits
