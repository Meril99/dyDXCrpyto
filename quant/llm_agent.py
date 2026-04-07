"""LLM-powered Telegram trading agent.

Uses Claude (or OpenAI) with tool-calling to understand natural language
queries and execute trading operations.

Architecture:
    User (Telegram) → Bot → LLM (with tools) → dYdX API → Response → User
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from quant.llm_tools import TOOLS, TradingTools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a trading assistant for a dYdX perpetual futures trading bot.

You can query positions, account info, orderbooks, risk metrics, signals,
and recent trades using the tools available to you.

Guidelines:
- Be concise. Traders want quick answers, not essays.
- Format numbers clearly: use $ for USD amounts, % for percentages.
- If the user asks to do something risky (close all positions, cancel orders),
  confirm you're doing it but proceed — they're the boss.
- If you don't have a tool for something, say so honestly.
- When explaining risk metrics, keep it simple: "Your drawdown is 5%,
  which means you've lost 5% from your peak equity."
- Always mention if a circuit breaker is active.
"""


class LLMAgent:
    """LLM agent that processes natural language and calls trading tools.

    Supports both Anthropic (Claude) and OpenAI APIs.
    Set ANTHROPIC_API_KEY or OPENAI_API_KEY in environment.
    """

    def __init__(
        self,
        trading_tools: TradingTools,
        provider: Optional[str] = None,
    ) -> None:
        self._tools = trading_tools
        self._conversation: List[Dict[str, Any]] = []

        # Auto-detect provider
        if provider:
            self._provider = provider
        elif os.environ.get('ANTHROPIC_API_KEY'):
            self._provider = 'anthropic'
        elif os.environ.get('OPENAI_API_KEY'):
            self._provider = 'openai'
        else:
            self._provider = 'none'
            logger.warning(
                "No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
            )

    def chat(self, user_message: str) -> str:
        """Process a user message and return the agent's response.

        The agent may call one or more tools before responding.
        """
        if self._provider == 'none':
            return "LLM not configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."

        if self._provider == 'anthropic':
            return self._chat_anthropic(user_message)
        else:
            return self._chat_openai(user_message)

    # ============================================================
    # Anthropic (Claude) implementation
    # ============================================================

    def _chat_anthropic(self, user_message: str) -> str:
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            return "ANTHROPIC_API_KEY not set."

        self._conversation.append({
            "role": "user",
            "content": user_message,
        })

        # Convert tools to Anthropic format
        anthropic_tools = []
        for t in TOOLS:
            anthropic_tools.append({
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            })

        # Keep conversation manageable
        messages = self._conversation[-20:]

        max_rounds = 5
        for _ in range(max_rounds):
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                    "tools": anthropic_tools,
                },
                timeout=30,
            )

            if resp.status_code != 200:
                logger.error("Anthropic API error: %s", resp.text)
                return f"API error: {resp.status_code}"

            data = resp.json()
            stop_reason = data.get("stop_reason", "")

            # Collect text and tool calls from response
            text_parts = []
            tool_uses = []
            for block in data.get("content", []):
                if block["type"] == "text":
                    text_parts.append(block["text"])
                elif block["type"] == "tool_use":
                    tool_uses.append(block)

            # If there are tool calls, execute them and continue
            if tool_uses:
                # Add assistant message with tool uses
                messages.append({"role": "assistant", "content": data["content"]})

                # Execute each tool and add results
                tool_results = []
                for tu in tool_uses:
                    result = self._tools.execute_tool(
                        tu["name"], tu.get("input", {}),
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result,
                    })
                    logger.info("Tool %s → %s", tu["name"], result[:100])

                messages.append({"role": "user", "content": tool_results})
            else:
                # No tool calls — we have the final response
                response_text = "\n".join(text_parts) or "No response."
                self._conversation.append({
                    "role": "assistant",
                    "content": response_text,
                })
                return response_text

        return "Reached maximum tool call rounds."

    # ============================================================
    # OpenAI implementation
    # ============================================================

    def _chat_openai(self, user_message: str) -> str:
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            return "OPENAI_API_KEY not set."

        self._conversation.append({
            "role": "user",
            "content": user_message,
        })

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self._conversation[-20:])

        max_rounds = 5
        for _ in range(max_rounds):
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "tools": TOOLS,
                    "tool_choice": "auto",
                },
                timeout=30,
            )

            if resp.status_code != 200:
                logger.error("OpenAI API error: %s", resp.text)
                return f"API error: {resp.status_code}"

            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]

            if msg.get("tool_calls"):
                messages.append(msg)
                for tc in msg["tool_calls"]:
                    args = json.loads(tc["function"]["arguments"])
                    result = self._tools.execute_tool(
                        tc["function"]["name"], args,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
                    logger.info(
                        "Tool %s → %s", tc["function"]["name"], result[:100],
                    )
            else:
                response_text = msg.get("content", "No response.")
                self._conversation.append({
                    "role": "assistant",
                    "content": response_text,
                })
                return response_text

        return "Reached maximum tool call rounds."

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._conversation.clear()
