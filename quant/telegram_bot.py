"""Telegram bot that connects the LLM agent to a Telegram chat.

Polls for new messages and responds using the LLM agent with
tool-calling to query/control the trading system.

Usage:
    PYTHONPATH=. python3 -m quant.telegram_bot
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from quant.llm_agent import LLMAgent
from quant.llm_tools import TradingTools

logger = logging.getLogger(__name__)


class TelegramBot:
    """Long-polling Telegram bot that routes messages to the LLM agent."""

    def __init__(
        self,
        agent: LLMAgent,
        bot_token: Optional[str] = None,
        allowed_chat_ids: Optional[list] = None,
    ) -> None:
        self._agent = agent
        self._token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self._base_url = f"https://api.telegram.org/bot{self._token}"
        self._last_update_id = 0

        # Security: only respond to authorized chat IDs
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
        if allowed_chat_ids:
            self._allowed = set(str(c) for c in allowed_chat_ids)
        elif chat_id:
            self._allowed = {chat_id}
        else:
            self._allowed = set()
            logger.warning("No TELEGRAM_CHAT_ID set — bot will respond to anyone!")

    def send_message(self, chat_id: str, text: str) -> bool:
        """Send a message to a Telegram chat."""
        try:
            # Telegram has a 4096 char limit
            if len(text) > 4000:
                text = text[:4000] + "\n... (truncated)"

            resp = requests.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                # Retry without Markdown if it fails (formatting issues)
                requests.post(
                    f"{self._base_url}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                    timeout=10,
                )
            return True
        except Exception as e:
            logger.error("Failed to send message: %s", e)
            return False

    def get_updates(self) -> list:
        """Long-poll for new messages."""
        try:
            resp = requests.get(
                f"{self._base_url}/getUpdates",
                params={
                    "offset": self._last_update_id + 1,
                    "timeout": 30,
                },
                timeout=35,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("result", [])
        except Exception as e:
            logger.error("Failed to get updates: %s", e)
            return []

    def run(self) -> None:
        """Main loop: poll for messages and respond via LLM."""
        if not self._token:
            logger.error("TELEGRAM_BOT_TOKEN not set. Cannot start bot.")
            return

        logger.info("Telegram bot started. Listening for messages...")
        self.send_message(
            list(self._allowed)[0] if self._allowed else "",
            "Trading agent online. Send me a message!",
        )

        while True:
            try:
                updates = self.get_updates()

                for update in updates:
                    self._last_update_id = update["update_id"]
                    message = update.get("message", {})
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    text = message.get("text", "")

                    if not text or not chat_id:
                        continue

                    # Security check
                    if self._allowed and chat_id not in self._allowed:
                        logger.warning(
                            "Unauthorized message from chat_id=%s", chat_id,
                        )
                        self.send_message(chat_id, "Unauthorized.")
                        continue

                    logger.info("Message from %s: %s", chat_id, text)

                    # Special commands
                    if text.strip().lower() in ('/start', '/help'):
                        self.send_message(chat_id, HELP_TEXT)
                        continue

                    if text.strip().lower() == '/clear':
                        self._agent.clear_history()
                        self.send_message(chat_id, "Conversation cleared.")
                        continue

                    # Send to LLM agent
                    self.send_message(chat_id, "Thinking...")
                    response = self._agent.chat(text)
                    self.send_message(chat_id, response)

            except KeyboardInterrupt:
                logger.info("Telegram bot stopping...")
                break
            except Exception as e:
                logger.exception("Error in telegram bot loop: %s", e)
                time.sleep(5)


HELP_TEXT = """*Trading Agent*

Ask me anything about your trading bot:

*Queries:*
- "What's my position?"
- "Show me the BTC orderbook"
- "What's my PnL?"
- "What are the current signals?"
- "Show risk status"
- "What's the ETH price?"
- "Show recent fills"
- "How much funding have I paid?"

*Actions:*
- "Cancel all orders"
- "Cancel BTC orders"

*Commands:*
/help - Show this message
/clear - Clear conversation history
"""


def main() -> None:
    """Entry point for standalone telegram bot."""
    import sys
    from pathlib import Path

    # Load .env
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                os.environ.setdefault(key.strip(), value.strip())

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    # Check required env vars
    if not os.environ.get('TELEGRAM_BOT_TOKEN'):
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    llm_provider = None
    if os.environ.get('ANTHROPIC_API_KEY'):
        llm_provider = 'anthropic'
        print("Using Anthropic (Claude) as LLM provider")
    elif os.environ.get('OPENAI_API_KEY'):
        llm_provider = 'openai'
        print("Using OpenAI as LLM provider")
    else:
        print("Error: Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env")
        sys.exit(1)

    # Initialize with dYdX client
    from dydx3 import Client
    from dydx3.constants import API_HOST_MAINNET

    host = os.environ.get('DYDX_HOST', API_HOST_MAINNET)
    api_key = os.environ.get('DYDX_API_KEY', '')
    api_secret = os.environ.get('DYDX_API_SECRET', '')
    api_passphrase = os.environ.get('DYDX_API_PASSPHRASE', '')
    stark_key = os.environ.get('DYDX_STARK_PRIVATE_KEY', '')

    if api_key and api_secret and api_passphrase:
        client = Client(
            host=host,
            api_key_credentials={
                'key': api_key,
                'secret': api_secret,
                'passphrase': api_passphrase,
            },
            stark_private_key=stark_key or None,
        )
        print(f"Connected to dYdX at {host}")
    else:
        print("Warning: dYdX credentials not set. Tools will fail.")
        client = Client(host=host)

    tools = TradingTools(client)
    agent = LLMAgent(tools, provider=llm_provider)
    bot = TelegramBot(agent)
    bot.run()


if __name__ == '__main__':
    main()
