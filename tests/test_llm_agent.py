"""Tests for the LLM agent and tools (no API calls needed)."""

from quant.llm_tools import TradingTools, TOOLS, TOOL_FUNCTIONS
from quant.sentiment_signal import NewsSentimentSignal


class TestToolRegistry:

    def test_tools_registered(self):
        assert len(TOOLS) > 0
        names = [t['function']['name'] for t in TOOLS]
        assert 'get_positions' in names
        assert 'get_account' in names
        assert 'get_orderbook' in names
        assert 'get_risk_status' in names
        assert 'cancel_all_orders' in names

    def test_all_tools_have_descriptions(self):
        for t in TOOLS:
            assert t['function']['description']
            assert len(t['function']['description']) > 10

    def test_tool_functions_match_registry(self):
        for t in TOOLS:
            name = t['function']['name']
            assert name in TOOL_FUNCTIONS


class TestSentimentSignal:

    def test_default_neutral(self):
        sig = NewsSentimentSignal("BTC-USD")
        result = sig.compute()
        assert result.value == 0.0
        assert result.name == "news_sentiment_BTC-USD"

    def test_add_headline(self):
        sig = NewsSentimentSignal("BTC-USD")
        sig.add_headline("Bitcoin hits all-time high")
        assert len(sig._headlines) == 1

    def test_headline_limit(self):
        sig = NewsSentimentSignal("BTC-USD")
        for i in range(30):
            sig.add_headline(f"Headline {i}")
        assert len(sig._headlines) == 20  # capped

    def test_cache_returns_same(self):
        sig = NewsSentimentSignal("BTC-USD", cache_duration_s=60)
        sig._last_score = 0.5
        sig._last_reason = "test"
        sig._last_fetch = 9999999999.0  # far future = always cached
        result = sig.compute()
        assert result.value == 0.5
        assert result.metadata['cached'] == 1.0

    def test_signal_name(self):
        sig = NewsSentimentSignal("ETH-USD")
        assert sig.name == "news_sentiment_ETH-USD"
