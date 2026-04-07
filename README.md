# dYdX v3 Python Client & Quantitative Trading Toolkit

<div align="center">

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![C++](https://img.shields.io/badge/C%2B%2B-17-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-153%20passing-brightgreen)
![Type Hints](https://img.shields.io/badge/typing-fully%20typed-blue)

</div>

Full-stack crypto trading system built on the [dYdX v3](https://dydx.exchange) perpetual futures exchange. Includes a Python REST API client, quantitative trading toolkit (market making, backtesting, signals, risk), a high-performance C++ order book engine, and an LLM-powered Telegram trading agent.

## Architecture

```
 News Headlines ──┐
                  ▼
              ┌──────────┐
 Orderbook ──>│  Signal   │──> Composite Score [-1, +1]
 Funding ────>│  Pipeline │        │
 Volatility ─>│  (5 sigs) │        │
              └──────────┘        ▼
              ┌────────────────────────────┐    ┌───────────────┐
              │  Avellaneda-Stoikov        │───>│ Risk Monitor  │
              │  Market Maker              │    │ (6 circuit    │
              │  (inventory skew + quotes) │    │  breakers)    │
              └────────────────────────────┘    └───────────────┘
                       │                              │
                       ▼                              ▼
              ┌──────────────┐               ┌──────────────┐
              │  Backtester  │               │   Telegram    │
              │  (offline    │               │   LLM Agent   │
              │   validation)│               │   (monitor &  │
              └──────────────┘               │    control)   │
                                             └──────────────┘
                       │
              ┌──────────────┐
              │  C++ Order   │  ~7000x faster queries
              │  Book Engine │  (pybind11)
              └──────────────┘
```

## Installation

```bash
pip install -r requirements.txt

# Optional: build the C++ order book for high-performance use
cd cpp && ./build.sh
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

### Run the Bot (24/7)

```bash
cp .env.example .env   # fill in your API keys
PYTHONPATH=. python3 bot.py
```

The bot runs the market maker with all 5 signals, risk monitoring, and Telegram alerts. See [Deployment](#deployment) for running on a server.

### Chat with Your Bot via Telegram

```bash
PYTHONPATH=. python3 -m quant.telegram_bot
```

```
You:  "What's my position?"
Bot:  "BTC-USD: LONG 0.003 @ $50,200 | uPnL: +$15.00"

You:  "Show risk status"
Bot:  "Risk Status: OK
       Equity: $10,250  Drawdown: 1.2%  VaR: $328"

You:  "Cancel all orders"
Bot:  "All orders cancelled for all markets."
```

## Quantitative Components

### Signal Pipeline (5 Signals)

Every signal outputs a normalized score in [-1, 1]. They feed into the market maker via a weighted combiner.

| Signal | Weight | Description | Formula |
|--------|--------|-------------|---------|
| **Orderbook Imbalance** | 15% | Bid/ask volume ratio from L2 book | `(bid_vol - ask_vol) / total` |
| **Funding Rate Mean Reversion** | 30% | Extreme funding predicts reversion | `-tanh(avg_rate / threshold)` |
| **Volatility Regime** | 30% | Classifies vol into LOW/NORMAL/HIGH/CRISIS | Percentile rank of rolling vol |
| **News Sentiment (LLM)** | 25% | Headlines classified by Claude/GPT | LLM outputs [-1, 1] score |
| **Cross-Asset Momentum** | - | Leader-follower lag (BTC->ETH) | `clip((leader_z - follower_z) / 4)` |

The **news sentiment signal** fetches crypto headlines (via CryptoPanic API), sends them to an LLM (Claude Haiku or GPT-4o-mini) for classification, and caches results for 5 minutes to minimize API costs. If no LLM key is configured, it defaults to neutral (0.0).

```python
from quant import SignalCombiner, OrderbookImbalance
from quant.sentiment_signal import NewsSentimentSignal

sentiment = NewsSentimentSignal("BTC-USD", cache_duration_s=300)
combiner = SignalCombiner({
    'ob_imbalance_BTC-USD': 0.15,
    'funding_mr_BTC-USD': 0.30,
    'vol_regime_BTC-USD': 0.30,
    'news_sentiment_BTC-USD': 0.25,
})
```

### Market-Making Engine

Implements the **Avellaneda-Stoikov (2008)** optimal market-making model for perpetual futures.

**Core formulas:**
- **Reservation price:** `r = mid - q * gamma * sigma^2 * tau` — shifts quotes to shed inventory
- **Optimal spread:** `delta = gamma * sigma^2 * tau + (2/gamma) * ln(1 + gamma/k)` — widens with volatility

| Parameter | Description | Default |
|-----------|-------------|---------|
| `gamma` | Inventory risk aversion | 0.1 |
| `k` | Order arrival intensity | 1.5 |
| `min_spread_bps` | Minimum spread floor | 5 bps |
| `max_spread_bps` | Maximum spread cap | 100 bps |
| `max_inventory` | Hard position limit | configurable |
| `session_duration_s` | Rolling time horizon | 3600s |

Key features:
- Inventory skewing (long inventory -> lower quotes to attract sellers)
- Signal integration via `apply_signal()` for directional bias from all 5 signals
- Rolling session horizon avoids tau->0 singularity
- Pure computation separated from exchange interaction for testability

### Backtesting Framework

Event-driven backtester with vectorized data loading and realistic simulation.

```python
class Strategy(abc.ABC):
    @abc.abstractmethod
    def on_candle(self, candle, positions, equity, context) -> List[Order]:
        """Return orders to execute. Context provides safe lookback()."""
        ...
```

Features:
- **Lookahead prevention** via `BacktestContext.lookback(n)`
- **Fill simulation**: market orders at close +/- slippage, limit orders check candle range
- **Position management**: weighted-avg entry on increase, realized PnL on reduce/flip
- **Funding rate simulation**: hourly payments matching dYdX's model (critical for perps)
- **Metrics**: Sharpe, Sortino, max drawdown, total return, win rate, profit factor

### Risk Monitor

Real-time portfolio risk tracking with 6 configurable circuit breakers.

| Circuit Breaker | Default | Description |
|----------------|---------|-------------|
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
- Callback hook `on_breaker` for Telegram alerts

## C++ Order Book Engine

High-performance L2 order book implemented in C++17 with pybind11 Python bindings.

**Benchmark results** (100K orders + 50K queries):

| Operation | Python | C++ | Speedup |
|-----------|--------|-----|---------|
| Add orders | 1.9M ops/s | 1.5M ops/s | ~1x |
| Cancel orders | 1.2M ops/s | 1.3M ops/s | ~1x |
| **Queries (top + imbalance)** | **199 ops/s** | **1.4M ops/s** | **7,024x** |

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
cd cpp && ./build.sh   # Requires CMake 3.14+, C++17 compiler, pybind11
```

## LLM Telegram Agent

Natural language interface to monitor and control the bot from your phone. Uses **tool-calling** — the LLM decides which API queries to run based on your message.

**9 tools available:** positions, account, orderbook, market price, risk status, signals, recent fills, funding payments, cancel orders.

Supports both **Anthropic (Claude)** and **OpenAI (GPT)** APIs.

```bash
# Set in .env:
TELEGRAM_BOT_TOKEN=your-token
TELEGRAM_CHAT_ID=your-chat-id
ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY

# Run:
PYTHONPATH=. python3 -m quant.telegram_bot
```

## Deployment

### Run as a 24/7 Service

```bash
# 1. Set up a server (Ubuntu VPS — DigitalOcean $6/mo, Hetzner $4/mo)
# 2. Clone and configure:
git clone https://github.com/Meril99/dyDXCrpyto.git
cd dydx-v3-python
cp .env.example .env && nano .env    # fill in credentials

# 3. Run the setup script:
chmod +x deploy/setup-server.sh && ./deploy/setup-server.sh

# 4. Start the bot:
sudo systemctl start dydx-bot
sudo systemctl enable dydx-bot       # auto-start on reboot

# 5. Monitor:
tail -f bot.log                       # live logs
sudo systemctl status dydx-bot       # service status
```

The systemd service auto-restarts on crash. The bot sends Telegram alerts for trades, circuit breakers, errors, and periodic heartbeats.

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
  bindings.cpp            #   pybind11 Python module
  CMakeLists.txt          #   Build configuration
  benchmark.py            #   Python vs C++ benchmark

quant/                    # Quantitative trading toolkit
  types.py                #   Shared dataclasses (Candle, Position, Signal, etc.)
  utils.py                #   Numerical helpers (vol, Sharpe, drawdown)
  signals.py              #   4 signal generators + SignalCombiner
  sentiment_signal.py     #   LLM-based news sentiment signal
  backtester.py           #   Strategy ABC + Backtester engine
  market_maker.py         #   Avellaneda-Stoikov market maker
  risk_monitor.py         #   Risk tracking + circuit breakers
  alerts.py               #   Telegram notification module
  llm_agent.py            #   LLM agent with tool-calling (Claude / GPT)
  llm_tools.py            #   9 tool definitions for the LLM agent
  telegram_bot.py         #   Telegram bot interface

deploy/                   # Server deployment
  setup-server.sh         #   One-command Ubuntu server setup
  dydx-bot.service        #   systemd service (auto-restart)

bot.py                    # Main 24/7 bot entry point
.env.example              # Configuration template

examples/                 # Runnable demos
  quant_backtest.py       #   Momentum strategy backtest
  quant_market_maker.py   #   Market maker with signals
  quant_signals.py        #   Signal pipeline demo
  quant_risk_monitor.py   #   Risk monitor scenarios

tests/                    # 153 unit tests
```

## Running Examples

```bash
PYTHONPATH=. python3 examples/quant_backtest.py        # Backtest a momentum strategy
PYTHONPATH=. python3 examples/quant_market_maker.py    # Market maker dry run
PYTHONPATH=. python3 examples/quant_signals.py         # Signal pipeline demo
PYTHONPATH=. python3 examples/quant_risk_monitor.py    # Risk monitor scenarios
PYTHONPATH=. python3 cpp/benchmark.py                  # C++ vs Python benchmark
```

## Development

```bash
pip install -r requirements.txt
pip install -r requirements-test.txt

pytest tests/                                          # Run tests
flake8 dydx3/ quant/ --max-line-length=100             # Lint
mypy dydx3/ --ignore-missing-imports                   # Type check
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

## License

Apache 2.0
