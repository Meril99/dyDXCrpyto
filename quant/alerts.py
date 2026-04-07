"""Telegram alerting for trade notifications, risk events, and status updates.

Setup:
    1. Message @BotFather on Telegram, send /newbot, follow prompts
    2. Copy the bot token (looks like: 123456:ABC-DEF1234...)
    3. Message your bot, then visit:
       https://api.telegram.org/bot<TOKEN>/getUpdates
       to find your chat_id
    4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from quant.types import Fill, Position, QuoteOrder, RiskSnapshot, Side

logger = logging.getLogger(__name__)


class TelegramAlert:
    """Send alerts to a Telegram chat."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        rate_limit_seconds: float = 5.0,
        enabled: bool = True,
    ) -> None:
        self._token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self._chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '')
        self._rate_limit = rate_limit_seconds
        self._last_sent: float = 0.0
        self._enabled = enabled

        if self._enabled and (not self._token or not self._chat_id):
            logger.warning(
                "Telegram alerts disabled: set TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID environment variables"
            )
            self._enabled = False

    def _send(self, text: str, force: bool = False) -> bool:
        """Send a message to Telegram. Rate-limited unless force=True."""
        if not self._enabled:
            logger.debug("Alert (disabled): %s", text)
            return False

        now = time.time()
        if not force and (now - self._last_sent) < self._rate_limit:
            return False

        try:
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            resp = requests.post(url, json={
                'chat_id': self._chat_id,
                'text': text,
                'parse_mode': 'Markdown',
            }, timeout=10)
            self._last_sent = time.time()
            return resp.status_code == 200
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return False

    # ---- High-level alert methods ----

    def bot_started(self, market: str, config_summary: str = "") -> None:
        """Alert that the bot has started."""
        msg = f"*BOT STARTED*\nMarket: `{market}`"
        if config_summary:
            msg += f"\n{config_summary}"
        self._send(msg, force=True)

    def bot_stopped(self, reason: str = "manual") -> None:
        """Alert that the bot has stopped."""
        self._send(f"*BOT STOPPED*\nReason: {reason}", force=True)

    def quote_placed(self, bid: QuoteOrder, ask: QuoteOrder) -> None:
        """Alert on new quotes (rate-limited)."""
        spread_bps = 0.0
        if bid.price > 0:
            spread_bps = (ask.price - bid.price) / bid.price * 1e4
        msg = (
            f"*QUOTE*\n"
            f"Bid: `${bid.price:,.2f}` x {bid.size}\n"
            f"Ask: `${ask.price:,.2f}` x {ask.size}\n"
            f"Spread: `{spread_bps:.1f} bps`"
        )
        self._send(msg)

    def fill_received(self, fill: Fill) -> None:
        """Alert on a trade fill."""
        side = "BUY" if fill.side == Side.BUY else "SELL"
        msg = (
            f"*FILL*\n"
            f"{side} `{fill.size}` {fill.market} @ `${fill.price:,.2f}`\n"
            f"Fee: `${fill.fee:.4f}`"
        )
        self._send(msg, force=True)

    def circuit_breaker(self, reason: str) -> None:
        """Alert on circuit breaker trigger."""
        msg = f"*CIRCUIT BREAKER TRIGGERED*\n`{reason}`"
        self._send(msg, force=True)

    def risk_snapshot(self, snap: RiskSnapshot) -> None:
        """Send periodic risk summary (rate-limited)."""
        status = "BREAKER" if snap.breaker_triggered else "OK"
        msg = (
            f"*RISK STATUS: {status}*\n"
            f"Equity: `${snap.total_equity:,.2f}`\n"
            f"Exposure: `${snap.total_exposure:,.2f}`\n"
            f"Margin: `{snap.margin_utilization:.1%}`\n"
            f"Drawdown: `{snap.max_drawdown:.2%}`\n"
            f"VaR(95%): `${snap.var_95:,.2f}`"
        )
        self._send(msg)

    def error(self, error_msg: str) -> None:
        """Alert on an error."""
        self._send(f"*ERROR*\n`{error_msg}`", force=True)

    def heartbeat(self, market: str, mid_price: float, inventory: float) -> None:
        """Periodic heartbeat to confirm the bot is alive (rate-limited)."""
        msg = (
            f"*HEARTBEAT*\n"
            f"Market: `{market}`\n"
            f"Mid: `${mid_price:,.2f}`\n"
            f"Inventory: `{inventory:+.6f}`"
        )
        self._send(msg)
