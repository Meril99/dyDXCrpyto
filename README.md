# dYdX v3 Python Client & Quantitative Trading Toolkit

<div align="center">

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-143%20passing-brightgreen)
![Type Hints](https://img.shields.io/badge/typing-fully%20typed-blue)

</div>

Python REST API client for [dYdX v3](https://dydx.exchange) perpetual futures exchange, with an integrated **quantitative trading toolkit** featuring a market-making engine, backtesting framework, signal pipeline, and risk monitor.

## Architecture

```
                    +-----------+
   Market Data ---> |  Signals  | ---> Normalized scores [-1, 1]
                    +-----------+
                         |
                         v
                   +----------------+      +--------------+
                   | Market Maker   | ---> | Risk Monitor |
                   | (A-S optimal   |      | (circuit     |
                   |  quoting)      |      |  breakers)   |
                   +----------------+      +--------------+
                         |
                         v
                   +-----------+
                   | Backtester| (validate strategies offline)
                   +-----------+
```

## Installation

```bash
pip install -r requirements.txt
```

Requires Python 3.8+. Key dependencies: `web3`, `numpy`, `pandas`.

## Quick Start

### API Client

```python
from dydx3 import Client
from dydx3.constants import API_HOST_MAINNET

# Public data (no auth needed)
client = Client(host=API_HOST_MAINNET)
markets = client.public.get_markets()
orderbook = client.public.get_orderbook('BTC-USD')

# Authenticated trading
client = Client(
    host=API_HOST_MAINNET,
    api_key_credentials={'key': '...', 'secret': '...', 'passphrase': '...'},
    stark_private_key='...',
)
client.private.create_order(
    position_id='12345',
    market='ETH-USD',
    side='BUY',
    order_type='LIMIT',
    post_only=True,
    size='1.0',
    price='3000',
    limit_fee='0.0015',
    expiration_epoch_seconds=1700000000,
)
```

### Run a Backtest

```python
from quant import Backtester, BacktestConfig, Strategy, Order, Side
from quant.types import Position

class MomentumStrategy(Strategy):
    def on_candle(self, candle, positions, equity, context):
        lookback = context.lookback(20)
        if len(lookback) < 20:
            return []
        sma = lookback['close'].mean()
        size = equity * 0.1 / candle['close']

        if candle['close'] > sma and 'ETH-USD' not in positions:
            return [Order(market='ETH-USD', side=Side.BUY, size=size)]
        elif candle['close'] < sma and 'ETH-USD' in positions:
            return [Order(market='ETH-USD', side=Side.SELL,
                          size=abs(positions['ETH-USD'].size))]
        return []

bt = Backtester(BacktestConfig(initial_equity=10_000))
bt.load_candles_from_api(client.public, 'ETH-USD', '1HOUR', limit=500)
result = bt.run(MomentumStrategy())

print(f"Sharpe:   {result.metrics['sharpe_ratio']:.2f}")
print(f"Max DD:   {result.metrics['max_drawdown']:.1%}")
print(f"Return:   {result.metrics['total_return']:.1%}")
```

### Market Making with Signals

```python
from quant import MarketMaker, MarketMakerConfig, OrderbookImbalance

mm = MarketMaker(client, MarketMakerConfig(
    market='BTC-USD',
    order_size=0.001,
    max_inventory=0.01,
    gamma=0.1,        # risk aversion
    k=1.5,            # order arrival intensity
    min_spread_bps=5,
))

# Continuous quoting loop
while True:
    bid, ask = mm.run_once()
    time.sleep(mm._config.refresh_interval_s)
```

## Quantitative Components

### Market-Making Engine

Implements the **Avellaneda-Stoikov (2008)** optimal market-making model for perpetual futures.

**Core formulas:**
- **Reservation price:** `r = mid - q * γ * σ² * τ` — shifts quotes to shed inventory
- **Optimal spread:** `δ = γ * σ² * τ + (2/γ) * ln(1 + γ/k)` — widens with volatility and risk aversion

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gamma` | Inventory risk aversion | 0.1 |
| `k` | Order arrival intensity | 1.5 |
| `min_spread_bps` | Minimum spread floor | 5 bps |
| `max_spread_bps` | Maximum spread cap | 100 bps |
| `max_inventory` | Hard position limit | - |
| `session_duration_s` | Rolling time horizon | 3600s |

Key features:
- Inventory skewing (long inventory → lower quotes to attract sellers)
- Signal integration via `apply_signal()` for directional bias
- Rolling session horizon avoids τ→0 singularity
- Pure computation separated from exchange interaction for testability

### Backtesting Framework

Event-driven backtester with vectorized data loading and realistic simulation.

**Strategy interface:**
```python
class Strategy(abc.ABC):
    @abc.abstractmethod
    def on_candle(self, candle, positions, equity, context) -> List[Order]:
        """Return orders to execute. Context provides safe lookback()."""
        ...
```

Features:
- **Lookahead prevention** via `BacktestContext.lookback(n)`
- **Fill simulation**: market orders at close ± slippage, limit orders check candle range
- **Position management**: weighted-avg entry on increase, realized PnL on reduce/flip
- **Funding rate simulation**: hourly payments matching dYdX's model (critical for perps)
- **Metrics**: Sharpe, Sortino, max drawdown, total return, win rate, profit factor

### Signal Pipeline

Four signal generators, each outputting a normalized score in [-1, 1]:

| Signal | Description | Formula |
|--------|-------------|---------|
| **Orderbook Imbalance** | Bid/ask volume ratio from L2 book | `(bid_vol - ask_vol) / total` |
| **Funding Rate Mean Reversion** | Extreme funding predicts reversion | `-tanh(avg_rate / threshold)` |
| **Cross-Asset Momentum** | Leader-follower lag detection (BTC→ETH) | `clip((leader_z - follower_z) / 4)` |
| **Volatility Regime** | Classifies vol into LOW/NORMAL/HIGH/CRISIS | Percentile rank of rolling vol |

Signals compose via `SignalCombiner` with configurable weights:
```python
combiner = SignalCombiner({
    'ob_imbalance_BTC-USD': 0.3,
    'funding_mr_BTC-USD': 0.4,
    'vol_regime_BTC-USD': 0.3,
})
composite = combiner.combine([sig1, sig2, sig3])
```

### Risk Monitor

Real-time portfolio risk tracking with configurable circuit breakers.

| Circuit Breaker | Default Threshold | Description |
|----------------|-------------------|-------------|
| Max drawdown | 10% | From peak equity |
| Max exposure | $50,000 | Total notional across all positions |
| Margin utilization | 80% | Exposure / equity |
| VaR (95%) | $2,000 | 1-day historical simulation VaR |
| Position size | 100 units | Per-market absolute size limit |
| Single loss | $500 | Per-position unrealized loss |

Features:
- Works in **live mode** (fetches from API) and **backtest mode** (pure computation)
- Historical simulation VaR with parametric fallback
- `emergency_flatten()` cancels all orders and closes positions
- Callback hook `on_breaker` for custom alerting

## C++ Order Book Engine

High-performance L2 order book implemented in C++ with pybind11 Python bindings. ~**85x faster** than an equivalent pure Python implementation.

**Operations:**
- `add_order(id, side, price, size)` — O(log N) insert into sorted price map
- `cancel_order(id)` — O(1) lookup + O(log N) level removal
- `modify_order(id, new_size)` — O(1) lookup + O(1) size update
- `top()` — O(1) BBO, mid-price, micro-price, spread
- `vwap(side, size)` — sweep through levels for volume-weighted avg price
- `imbalance(depth)` — bid/ask volume ratio over top N levels
- `bid_depth(n)` / `ask_depth(n)` — N levels of market depth

**Data structures:** `std::map<double, PriceLevel>` for O(log N) sorted levels, `std::unordered_map<uint64_t, Order>` for O(1) order lookup.

```python
import orderbook_cpp as ob

book = ob.OrderBook()
book.add_order(1, ob.BUY, 50000.0, 1.5)
book.add_order(2, ob.SELL, 50010.0, 0.8)

tob = book.top()
print(f"Spread: {tob.spread}  Mid: {tob.mid_price}  Micro: {tob.micro_price:.2f}")
print(f"VWAP to buy 1 BTC: {book.vwap(ob.BUY, 1.0):.2f}")
print(f"Imbalance: {book.imbalance(10):+.3f}")
```

**Build:**
```bash
cd cpp && ./build.sh
```

Requires CMake 3.14+, a C++17 compiler, and pybind11 (`pip install pybind11`).

## Project Structure

```
dydx3/                    # API client library
  dydx_client.py          #   Main Client class
  modules/                #   API endpoint modules (public, private, eth, onboarding)
  eth_signing/            #   Ethereum EIP-712 signing
  starkex/                #   STARK key cryptography & order signing
  helpers/                #   HTTP, query building, ID generation

cpp/                      # C++ order book engine
  orderbook.h / .cpp      #   Core engine (std::map + unordered_map)
  bindings.cpp             #   pybind11 Python module
  CMakeLists.txt           #   Build configuration
  benchmark.py             #   Python vs C++ benchmark (~85x speedup)

quant/                    # Quantitative trading toolkit
  types.py                #   Shared dataclasses (Candle, Position, Signal, etc.)
  utils.py                #   Numerical helpers (vol, Sharpe, drawdown)
  signals.py              #   4 signal generators + SignalCombiner
  backtester.py           #   Strategy ABC + Backtester engine
  market_maker.py         #   Avellaneda-Stoikov market maker
  risk_monitor.py         #   Risk tracking + circuit breakers

examples/                 # Runnable examples
  quant_backtest.py       #   Momentum strategy backtest
  quant_market_maker.py   #   Market maker with signals
  quant_signals.py        #   Signal pipeline demo
  quant_risk_monitor.py   #   Risk monitor demo

tests/                    # 143 unit tests
```

## Running Examples

```bash
python examples/quant_backtest.py        # Backtest a momentum strategy
python examples/quant_market_maker.py    # Market maker dry run
python examples/quant_signals.py         # Signal pipeline demo
python examples/quant_risk_monitor.py    # Risk monitor scenarios
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-test.txt

# Run tests
pytest tests/

# Lint
flake8 dydx3/ quant/ --max-line-length=100

# Type check
mypy dydx3/ --ignore-missing-imports
```

## API Client Reference

### Authentication Levels

| Level | Required Credentials | Endpoints |
|-------|---------------------|-----------|
| Public | None | Markets, orderbook, candles, trades, funding |
| Private | `api_key_credentials` | Orders, positions, fills, transfers, PnL |
| Eth Private | `eth_private_key` or `web3` | API key management, recovery |
| Onboarding | `eth_private_key` or `web3` | User creation, STARK key derivation |

### Supported Markets

39 perpetual futures markets including BTC-USD, ETH-USD, SOL-USD, AVAX-USD, LINK-USD, AAVE-USD, UNI-USD, DOGE-USD, MATIC-USD, and more. All USDC-margined.

### STARK Signing Performance

For faster order signing, provide a path to the C++ shared library:

```python
client = Client(
    crypto_c_exports_path='./libcrypto_c_exports.so',
    ...
)
```

## License

Apache 2.0
