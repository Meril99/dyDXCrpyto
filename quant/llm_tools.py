"""LLM tool definitions for the trading agent.

Each tool is a function the LLM can call to interact with the trading
system. Tools return plain-text summaries that the LLM can relay to
the user in natural language.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from quant.types import Side

# Tool registry
TOOLS: List[Dict[str, Any]] = []
TOOL_FUNCTIONS: Dict[str, Callable] = {}


def tool(name: str, description: str, parameters: Dict[str, Any]):
    """Decorator to register a function as an LLM tool."""
    def decorator(func: Callable) -> Callable:
        TOOLS.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        })
        TOOL_FUNCTIONS[name] = func
        return func
    return decorator


class TradingTools:
    """Collection of tools the LLM agent can call.

    Each method queries the dYdX API or internal state and returns
    a human-readable string summary.
    """

    def __init__(self, client: Any, market_maker: Any = None, risk_monitor: Any = None) -> None:
        self._client = client
        self._mm = market_maker
        self._rm = risk_monitor

    @tool(
        name="get_positions",
        description="Get all open trading positions with PnL",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def get_positions(self) -> str:
        resp = self._client.private.get_positions(status='OPEN')
        positions = resp.data.get('positions', [])
        if not positions:
            return "No open positions."

        lines = ["Open positions:"]
        for p in positions:
            side = "LONG" if float(p['size']) > 0 else "SHORT"
            lines.append(
                f"  {p['market']}: {side} {abs(float(p['size']))} "
                f"@ ${float(p['entryPrice']):,.2f} | "
                f"uPnL: ${float(p.get('unrealizedPnl', 0)):+,.2f}"
            )
        return "\n".join(lines)

    @tool(
        name="get_account",
        description="Get account equity, balance, and margin info",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def get_account(self) -> str:
        resp = self._client.private.get_account()
        acc = resp.data['account']
        return (
            f"Account:\n"
            f"  Equity: ${float(acc['equity']):,.2f}\n"
            f"  Free collateral: ${float(acc.get('freeCollateral', 0)):,.2f}\n"
            f"  Quote balance: ${float(acc.get('quoteBalance', 0)):,.2f}"
        )

    @tool(
        name="get_orderbook",
        description="Get current orderbook (best bid/ask, spread, depth) for a market",
        parameters={
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Market pair, e.g. BTC-USD",
                },
            },
            "required": ["market"],
        },
    )
    def get_orderbook(self, market: str = "BTC-USD") -> str:
        resp = self._client.public.get_orderbook(market)
        bids = resp.data.get('bids', [])
        asks = resp.data.get('asks', [])

        if not bids or not asks:
            return f"Orderbook for {market} is empty."

        best_bid = float(bids[0]['price'])
        best_ask = float(asks[0]['price'])
        spread = best_ask - best_bid
        spread_bps = spread / best_bid * 1e4

        bid_vol = sum(float(b['size']) for b in bids[:5])
        ask_vol = sum(float(a['size']) for a in asks[:5])

        return (
            f"{market} Orderbook:\n"
            f"  Best bid: ${best_bid:,.2f} | Best ask: ${best_ask:,.2f}\n"
            f"  Spread: ${spread:.2f} ({spread_bps:.1f} bps)\n"
            f"  Mid: ${(best_bid + best_ask) / 2:,.2f}\n"
            f"  Top 5 bid vol: {bid_vol:.4f} | ask vol: {ask_vol:.4f}"
        )

    @tool(
        name="get_market_price",
        description="Get current price for a market",
        parameters={
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Market pair, e.g. ETH-USD",
                },
            },
            "required": ["market"],
        },
    )
    def get_market_price(self, market: str = "BTC-USD") -> str:
        resp = self._client.public.get_markets(market=market)
        data = resp.data.get('markets', {}).get(market, {})
        if not data:
            return f"Market {market} not found."

        return (
            f"{market}:\n"
            f"  Price: ${float(data.get('indexPrice', 0)):,.2f}\n"
            f"  24h volume: ${float(data.get('volume24H', 0)):,.0f}\n"
            f"  Open interest: ${float(data.get('openInterest', 0)):,.0f}\n"
            f"  Next funding: {data.get('nextFundingRate', 'N/A')}"
        )

    @tool(
        name="get_risk_status",
        description="Get current risk metrics: drawdown, exposure, VaR, circuit breakers",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def get_risk_status(self) -> str:
        if self._rm is None:
            return "Risk monitor not initialized."
        try:
            snap = self._rm.update()
            status = "BREAKER TRIGGERED" if snap.breaker_triggered else "OK"
            lines = [
                f"Risk Status: {status}",
                f"  Equity: ${snap.total_equity:,.2f}",
                f"  Exposure: ${snap.total_exposure:,.2f}",
                f"  Net delta: ${snap.net_delta:,.2f}",
                f"  Margin util: {snap.margin_utilization:.1%}",
                f"  Drawdown: {snap.max_drawdown:.2%}",
                f"  VaR (95%): ${snap.var_95:,.2f}",
            ]
            if snap.breaker_triggered:
                lines.append(f"  Breaker reason: {snap.breaker_reason}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching risk: {e}"

    @tool(
        name="get_signals",
        description="Get current trading signal values from the signal pipeline",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def get_signals(self) -> str:
        if self._mm is None:
            return "Market maker not running."
        return (
            f"Market Maker State:\n"
            f"  Mid price: ${self._mm.mid_price:,.2f}\n"
            f"  Inventory: {self._mm.inventory:+.6f}\n"
            f"  Volatility: {self._mm.sigma:.6f}\n"
            f"  Signal skew: ${self._mm._signal_skew:,.2f}"
        )

    @tool(
        name="get_recent_fills",
        description="Get recent trade fills",
        parameters={
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Market to filter (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of fills to return (default 5)",
                },
            },
            "required": [],
        },
    )
    def get_recent_fills(self, market: Optional[str] = None, limit: int = 5) -> str:
        resp = self._client.private.get_fills(market=market, limit=str(limit))
        fills = resp.data.get('fills', [])
        if not fills:
            return "No recent fills."

        lines = [f"Last {len(fills)} fills:"]
        for f in fills:
            lines.append(
                f"  {f['side']} {f['size']} {f['market']} "
                f"@ ${float(f['price']):,.2f} | "
                f"fee: ${float(f['fee']):,.4f} | "
                f"{f['createdAt']}"
            )
        return "\n".join(lines)

    @tool(
        name="cancel_all_orders",
        description="Cancel all open orders. Use with caution.",
        parameters={
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Market to cancel (optional, cancels all if empty)",
                },
            },
            "required": [],
        },
    )
    def cancel_all_orders(self, market: Optional[str] = None) -> str:
        try:
            self._client.private.cancel_all_orders(market=market)
            scope = market or "all markets"
            return f"All orders cancelled for {scope}."
        except Exception as e:
            return f"Failed to cancel orders: {e}"

    @tool(
        name="get_funding_payments",
        description="Get recent funding rate payments",
        parameters={
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Market to filter (optional)",
                },
            },
            "required": [],
        },
    )
    def get_funding_payments(self, market: Optional[str] = None) -> str:
        resp = self._client.private.get_funding_payments(
            market=market, limit='5',
        )
        payments = resp.data.get('fundingPayments', [])
        if not payments:
            return "No recent funding payments."

        lines = ["Recent funding payments:"]
        total = 0.0
        for p in payments:
            amt = float(p['payment'])
            total += amt
            lines.append(
                f"  {p['market']} | {p['effectiveAt']} | "
                f"${amt:+,.4f} | rate: {p.get('rate', 'N/A')}"
            )
        lines.append(f"  Total: ${total:+,.4f}")
        return "\n".join(lines)

    @tool(
        name="get_historical_pnl",
        description="Get recent PnL history",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def get_historical_pnl(self) -> str:
        resp = self._client.private.get_historical_pnl()
        pnls = resp.data.get('historicalPnl', [])
        if not pnls:
            return "No PnL history available."

        lines = ["Recent PnL:"]
        for p in pnls[:5]:
            lines.append(
                f"  {p['createdAt']} | "
                f"equity: ${float(p.get('equity', 0)):,.2f} | "
                f"pnl: ${float(p.get('totalPnl', 0)):+,.2f}"
            )
        return "\n".join(lines)

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool by name with given arguments."""
        method = getattr(self, name, None)
        if method is None:
            return f"Unknown tool: {name}"
        try:
            return method(**arguments)
        except Exception as e:
            return f"Tool error ({name}): {e}"
