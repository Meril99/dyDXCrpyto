"""LLM-based news sentiment signal for crypto markets.

Fetches crypto news headlines and uses an LLM to classify sentiment,
producing a normalized signal [-1, 1] that plugs into the SignalCombiner.

Sources: CryptoPanic API (free tier) or manual headline feed.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from quant.signals import BaseSignal
from quant.types import Signal
from quant.utils import clip_signal

logger = logging.getLogger(__name__)

SENTIMENT_PROMPT = """You are a crypto market sentiment analyst.

Given the following news headlines about cryptocurrency markets,
rate the overall market sentiment as a single number from -1.0 to 1.0:

  -1.0 = extremely bearish (crash, hack, ban, fraud)
  -0.5 = moderately bearish (regulatory concerns, declining volume)
   0.0 = neutral (routine updates, mixed signals)
  +0.5 = moderately bullish (adoption, partnerships, inflows)
  +1.0 = extremely bullish (ETF approval, institutional buying, ATH)

Focus on headlines that would move crypto prices in the next 1-24 hours.
Ignore old news or irrelevant headlines.

Respond with ONLY a JSON object:
{"score": <number>, "reason": "<one sentence explanation>"}

Headlines:
{headlines}
"""


class NewsSentimentSignal(BaseSignal):
    """LLM-powered news sentiment signal.

    Fetches crypto news, sends to LLM for classification, outputs
    a signal in [-1, 1]. Caches results to avoid excessive API calls.
    """

    def __init__(
        self,
        market: str = "BTC-USD",
        cache_duration_s: float = 300,  # 5 minutes
        cryptopanic_token: Optional[str] = None,
    ) -> None:
        self._market = market
        self._cache_duration = cache_duration_s
        self._cryptopanic_token = (
            cryptopanic_token or os.environ.get('CRYPTOPANIC_API_TOKEN', '')
        )
        self._last_score: float = 0.0
        self._last_reason: str = ""
        self._last_fetch: float = 0.0
        self._headlines: List[str] = []

    @property
    def name(self) -> str:
        return f"news_sentiment_{self._market}"

    def fetch_headlines(self) -> List[str]:
        """Fetch recent crypto news headlines from CryptoPanic API."""
        if not self._cryptopanic_token:
            logger.debug("No CryptoPanic token, using manual headlines")
            return self._headlines

        try:
            # Extract base asset from market (BTC-USD -> BTC)
            asset = self._market.split('-')[0].lower()
            resp = requests.get(
                "https://cryptopanic.com/api/v1/posts/",
                params={
                    "auth_token": self._cryptopanic_token,
                    "currencies": asset,
                    "filter": "important",
                    "kind": "news",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("CryptoPanic API error: %s", resp.status_code)
                return self._headlines

            data = resp.json()
            headlines = [
                post['title'] for post in data.get('results', [])[:15]
            ]
            self._headlines = headlines
            return headlines

        except Exception as e:
            logger.error("Failed to fetch headlines: %s", e)
            return self._headlines

    def add_headline(self, headline: str) -> None:
        """Manually add a headline (for testing or custom feeds)."""
        self._headlines.append(headline)
        if len(self._headlines) > 20:
            self._headlines = self._headlines[-20:]

    def _classify_with_llm(self, headlines: List[str]) -> tuple:
        """Send headlines to LLM and get sentiment score."""
        if not headlines:
            return 0.0, "No headlines to analyze"

        headline_text = "\n".join(f"- {h}" for h in headlines)
        prompt = SENTIMENT_PROMPT.format(headlines=headline_text)

        # Try Anthropic first, then OpenAI
        anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '')
        openai_key = os.environ.get('OPENAI_API_KEY', '')

        if anthropic_key:
            return self._classify_anthropic(prompt, anthropic_key)
        elif openai_key:
            return self._classify_openai(prompt, openai_key)
        else:
            logger.warning("No LLM API key for sentiment analysis")
            return 0.0, "No LLM configured"

    def _classify_anthropic(self, prompt: str, api_key: str) -> tuple:
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return 0.0, f"API error: {resp.status_code}"

            text = resp.json()["content"][0]["text"].strip()
            data = json.loads(text)
            score = float(data.get("score", 0))
            reason = data.get("reason", "")
            return clip_signal(score), reason

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error("Failed to parse LLM response: %s", e)
            return 0.0, f"Parse error: {e}"
        except Exception as e:
            logger.error("Anthropic API error: %s", e)
            return 0.0, f"API error: {e}"

    def _classify_openai(self, prompt: str, api_key: str) -> tuple:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return 0.0, f"API error: {resp.status_code}"

            text = resp.json()["choices"][0]["message"]["content"].strip()
            data = json.loads(text)
            score = float(data.get("score", 0))
            reason = data.get("reason", "")
            return clip_signal(score), reason

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error("Failed to parse LLM response: %s", e)
            return 0.0, f"Parse error: {e}"
        except Exception as e:
            logger.error("OpenAI API error: %s", e)
            return 0.0, f"API error: {e}"

    def compute(self, **kwargs: object) -> Signal:
        """Compute the news sentiment signal.

        Caches results for cache_duration_s seconds to avoid
        excessive API calls.
        """
        now = time.time()

        # Return cached value if fresh
        if now - self._last_fetch < self._cache_duration:
            return Signal(
                name=self.name,
                market=self._market,
                value=self._last_score,
                timestamp=now,
                metadata={
                    'reason': self._last_reason,
                    'cached': 1.0,
                    'headlines_count': float(len(self._headlines)),
                },
            )

        # Fetch fresh headlines and classify
        headlines = self.fetch_headlines()
        score, reason = self._classify_with_llm(headlines)

        self._last_score = score
        self._last_reason = reason
        self._last_fetch = now

        logger.info(
            "Sentiment signal: %.2f (%s) from %d headlines",
            score, reason, len(headlines),
        )

        return Signal(
            name=self.name,
            market=self._market,
            value=score,
            timestamp=now,
            metadata={
                'reason': reason,
                'cached': 0.0,
                'headlines_count': float(len(headlines)),
            },
        )
