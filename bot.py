"""Main trading bot — runs the market maker 24/7 with risk monitoring and Telegram alerts.

Setup:
    1. Copy .env.example to .env and fill in your credentials
    2. Run: PYTHONPATH=. python3 bot.py

Environment variables (set in .env or export):
    DYDX_API_KEY          - Your dYdX API key
    DYDX_API_SECRET       - Your dYdX API secret
    DYDX_API_PASSPHRASE   - Your dYdX API passphrase
    DYDX_STARK_PRIVATE_KEY - Your STARK private key
    DYDX_POSITION_ID      - Your position ID
    DYDX_HOST             - API host (default: mainnet)
    DYDX_MARKET           - Market to trade (default: BTC-USD)
    TELEGRAM_BOT_TOKEN    - Telegram bot token (optional)
    TELEGRAM_CHAT_ID      - Telegram chat ID (optional)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

# Load .env file if it exists
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())

from dydx3 import Client
from dydx3.constants import API_HOST_MAINNET, API_HOST_SEPOLIA

from quant.alerts import TelegramAlert
from quant.market_maker import MarketMaker, MarketMakerConfig
from quant.risk_monitor import RiskMonitor, RiskLimits
from quant.signals import (
    FundingRateMeanReversion,
    OrderbookImbalance,
    SignalCombiner,
    VolatilityRegime,
)
from quant.sentiment_signal import NewsSentimentSignal
from quant.market_maker import parse_orderbook

# ============================================================
# Configuration — read from environment
# ============================================================

DYDX_HOST = os.environ.get('DYDX_HOST', API_HOST_MAINNET)
DYDX_MARKET = os.environ.get('DYDX_MARKET', 'BTC-USD')
API_KEY = os.environ.get('DYDX_API_KEY', '')
API_SECRET = os.environ.get('DYDX_API_SECRET', '')
API_PASSPHRASE = os.environ.get('DYDX_API_PASSPHRASE', '')
STARK_KEY = os.environ.get('DYDX_STARK_PRIVATE_KEY', '')
POSITION_ID = os.environ.get('DYDX_POSITION_ID', '')

# Market maker params (tune these)
ORDER_SIZE = float(os.environ.get('BOT_ORDER_SIZE', '0.001'))
MAX_INVENTORY = float(os.environ.get('BOT_MAX_INVENTORY', '0.01'))
GAMMA = float(os.environ.get('BOT_GAMMA', '0.1'))
MIN_SPREAD_BPS = float(os.environ.get('BOT_MIN_SPREAD_BPS', '5.0'))
REFRESH_INTERVAL = float(os.environ.get('BOT_REFRESH_INTERVAL', '10.0'))

# Risk limits
MAX_DRAWDOWN = float(os.environ.get('BOT_MAX_DRAWDOWN', '0.10'))
MAX_EXPOSURE = float(os.environ.get('BOT_MAX_EXPOSURE', '50000'))

# Heartbeat interval (seconds)
HEARTBEAT_INTERVAL = float(os.environ.get('BOT_HEARTBEAT_INTERVAL', '300'))

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log'),
    ],
)
logger = logging.getLogger('bot')

# ============================================================
# Graceful shutdown
# ============================================================

shutdown_requested = False


def handle_signal(signum: int, frame: object) -> None:
    global shutdown_requested
    logger.info("Shutdown signal received (%s)", signum)
    shutdown_requested = True


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

# ============================================================
# Main bot loop
# ============================================================


def validate_config() -> bool:
    """Check that required env vars are set."""
    missing = []
    if not API_KEY:
        missing.append('DYDX_API_KEY')
    if not API_SECRET:
        missing.append('DYDX_API_SECRET')
    if not API_PASSPHRASE:
        missing.append('DYDX_API_PASSPHRASE')
    if not STARK_KEY:
        missing.append('DYDX_STARK_PRIVATE_KEY')
    if not POSITION_ID:
        missing.append('DYDX_POSITION_ID')

    if missing:
        logger.error(
            "Missing required environment variables: %s",
            ', '.join(missing),
        )
        logger.error(
            "Copy .env.example to .env and fill in your credentials"
        )
        return False
    return True


def run() -> None:
    """Main entry point."""
    logger.info("=" * 50)
    logger.info("Starting dYdX Market Making Bot")
    logger.info("=" * 50)

    if not validate_config():
        sys.exit(1)

    # --- Initialize client ---
    client = Client(
        host=DYDX_HOST,
        api_key_credentials={
            'key': API_KEY,
            'secret': API_SECRET,
            'passphrase': API_PASSPHRASE,
        },
        stark_private_key=STARK_KEY,
    )
    logger.info("Client connected to %s", DYDX_HOST)

    # --- Initialize components ---
    mm_config = MarketMakerConfig(
        market=DYDX_MARKET,
        order_size=ORDER_SIZE,
        max_inventory=MAX_INVENTORY,
        gamma=GAMMA,
        min_spread_bps=MIN_SPREAD_BPS,
        refresh_interval_s=REFRESH_INTERVAL,
        position_id=POSITION_ID,
    )
    mm = MarketMaker(client=client, config=mm_config)

    alerts = TelegramAlert()

    risk = RiskMonitor(
        client=client,
        limits=RiskLimits(
            max_drawdown=MAX_DRAWDOWN,
            max_total_exposure=MAX_EXPOSURE,
        ),
        on_breaker=lambda event: alerts.circuit_breaker(event.reason),
    )

    # Signals
    ob_signal = OrderbookImbalance(DYDX_MARKET, depth=10)
    fr_signal = FundingRateMeanReversion(DYDX_MARKET)
    vol_signal = VolatilityRegime(DYDX_MARKET, short_window=20, long_window=200)
    sentiment_signal = NewsSentimentSignal(
        market=DYDX_MARKET,
        cache_duration_s=300,  # Re-fetch news every 5 minutes
    )
    combiner = SignalCombiner({
        ob_signal.name: 0.15,
        fr_signal.name: 0.30,
        vol_signal.name: 0.30,
        sentiment_signal.name: 0.25,  # News sentiment gets 25% weight
    })

    # --- Notify start ---
    config_summary = (
        f"Size: {ORDER_SIZE} | Max inv: {MAX_INVENTORY} | "
        f"Gamma: {GAMMA} | Spread: {MIN_SPREAD_BPS}bps"
    )
    alerts.bot_started(DYDX_MARKET, config_summary)
    logger.info("Market: %s | %s", DYDX_MARKET, config_summary)

    # --- Main loop ---
    last_heartbeat = 0.0
    cycle_count = 0
    error_count = 0
    max_consecutive_errors = 10

    while not shutdown_requested:
        try:
            cycle_count += 1

            # 1. Risk check
            snap = risk.update()
            if snap.breaker_triggered:
                logger.warning("Circuit breaker: %s", snap.breaker_reason)
                mm.cancel_stale_orders()
                alerts.risk_snapshot(snap)
                time.sleep(60)  # Wait before retrying
                continue

            # 2. Update signals
            ob_resp = client.public.get_orderbook(DYDX_MARKET)
            orderbook = parse_orderbook(ob_resp.data)

            ob_sig = ob_signal.compute(orderbook=orderbook)
            vol_signal.update(orderbook.bids[0].price if orderbook.bids else 0)
            vol_sig = vol_signal.compute()
            fr_sig = fr_signal.compute()
            news_sig = sentiment_signal.compute()  # LLM news sentiment
            composite = combiner.combine([ob_sig, fr_sig, vol_sig, news_sig])

            # 3. Feed signal to market maker and run
            mm.update_orderbook(orderbook)
            mm.update_volatility()
            mm.apply_signal(composite)

            # Fetch inventory
            pos_resp = client.private.get_positions(
                market=DYDX_MARKET, status='OPEN',
            )
            positions = pos_resp.data.get('positions', [])
            inv = float(positions[0]['size']) if positions else 0.0
            mm.update_inventory(inv)

            # 4. Compute and place quotes
            bid, ask = mm.compute_quotes()
            mm.place_quotes(bid, ask)

            # 5. Log
            spread_bps = (
                (ask.price - bid.price) / mm.mid_price * 1e4
                if mm.mid_price > 0 else 0
            )
            logger.info(
                "Cycle %d | mid=%.2f inv=%+.6f sig=%+.3f "
                "bid=%.2f ask=%.2f spread=%.1fbps",
                cycle_count, mm.mid_price, inv, composite.value,
                bid.price, ask.price, spread_bps,
            )

            # 6. Periodic heartbeat
            now = time.time()
            if now - last_heartbeat > HEARTBEAT_INTERVAL:
                alerts.heartbeat(DYDX_MARKET, mm.mid_price, inv)
                alerts.risk_snapshot(snap)
                last_heartbeat = now

            # Reset error count on success
            error_count = 0

        except KeyboardInterrupt:
            break
        except Exception as e:
            error_count += 1
            logger.exception("Error in cycle %d: %s", cycle_count, e)
            alerts.error(f"Cycle {cycle_count}: {e}")

            if error_count >= max_consecutive_errors:
                logger.critical(
                    "Too many consecutive errors (%d), shutting down",
                    error_count,
                )
                alerts.bot_stopped(
                    f"Too many errors: {error_count} consecutive"
                )
                mm.cancel_stale_orders()
                sys.exit(1)

            time.sleep(min(30, error_count * 5))  # Backoff
            continue

        time.sleep(REFRESH_INTERVAL)

    # --- Shutdown ---
    logger.info("Shutting down gracefully...")
    mm.cancel_stale_orders()
    alerts.bot_stopped("graceful shutdown")
    logger.info("Bot stopped.")


if __name__ == '__main__':
    run()
