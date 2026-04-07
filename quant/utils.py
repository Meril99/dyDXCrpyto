"""Numerical utilities shared across quant components."""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from quant.types import Fill, Side


def fetch_candles_df(
    public: object,
    market: str,
    resolution: str = "1HOUR",
    limit: int = 100,
) -> pd.DataFrame:
    """Fetch candles from the dYdX API and return a DataFrame.

    Columns: timestamp, open, high, low, close, volume, market.
    Sorted ascending by timestamp.
    """
    resp = public.get_candles(market, resolution=resolution, limit=str(limit))
    raw = resp.data.get('candles', [])
    rows = []
    for c in raw:
        rows.append({
            'timestamp': pd.Timestamp(c['startedAt']).timestamp(),
            'open': float(c['open']),
            'high': float(c['high']),
            'low': float(c['low']),
            'close': float(c['close']),
            'volume': float(c.get('baseTokenVolume', c.get('usdVolume', 0))),
            'market': market,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('timestamp').reset_index(drop=True)
    return df


def realized_volatility(
    prices: np.ndarray,
    window: int = 20,
    annualize: bool = True,
    periods_per_year: float = 365.25 * 24,
) -> np.ndarray:
    """Rolling realized volatility from log returns.

    Returns array of same length as prices (NaN-padded at the start).
    Default annualization assumes hourly data.
    """
    prices = np.asarray(prices, dtype=float)
    log_returns = np.diff(np.log(prices))

    result = np.full(len(prices), np.nan)
    for i in range(window - 1, len(log_returns)):
        window_rets = log_returns[i - window + 1:i + 1]
        vol = np.std(window_rets, ddof=1)
        if annualize:
            vol *= np.sqrt(periods_per_year)
        result[i + 1] = vol
    return result


def mid_price_from_orderbook(
    bids: list,
    asks: list,
) -> float:
    """Compute micro-price (size-weighted mid) from top-of-book levels.

    micro_price = (bid_price * ask_size + ask_price * bid_size) /
                  (bid_size + ask_size)
    """
    if not bids or not asks:
        if bids:
            return bids[0].price
        if asks:
            return asks[0].price
        return 0.0

    best_bid = bids[0]
    best_ask = asks[0]
    total_size = best_bid.size + best_ask.size

    if total_size < 1e-12:
        return (best_bid.price + best_ask.price) / 2.0

    return (
        best_bid.price * best_ask.size + best_ask.price * best_bid.size
    ) / total_size


def sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: float = 365.25 * 24,
) -> float:
    """Annualized Sharpe ratio."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    std = np.std(excess, ddof=1)
    if std < 1e-12:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(periods_per_year))


def sortino_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: float = 365.25 * 24,
) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    downside = excess[excess < 0]
    if len(downside) < 1:
        return float('inf') if np.mean(excess) > 0 else 0.0
    downside_std = np.std(downside, ddof=1)
    if downside_std < 1e-12:
        return 0.0
    return float(np.mean(excess) / downside_std * np.sqrt(periods_per_year))


def max_drawdown(equity_curve: np.ndarray) -> float:
    """Maximum drawdown as a positive fraction (e.g. 0.15 = 15%)."""
    equity_curve = np.asarray(equity_curve, dtype=float)
    if len(equity_curve) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity_curve)
    dd = (peak - equity_curve) / np.where(peak > 0, peak, 1.0)
    return float(np.nanmax(dd))


def profit_factor(fills: List[Fill]) -> float:
    """Gross profit / gross loss. Returns inf if no losses."""
    gross_profit = 0.0
    gross_loss = 0.0

    # Group fills into round-trip trades (simplified: pair sequential buy/sell)
    for f in fills:
        pnl = f.price * f.size
        if f.side == Side.SELL:
            gross_profit += pnl
        else:
            gross_loss += pnl

    # Net approach: profit factor from the signed difference
    net = gross_profit - gross_loss
    if net > 0 and gross_loss > 0:
        return gross_profit / gross_loss
    elif net > 0:
        return float('inf')
    elif gross_loss > 0:
        return gross_profit / gross_loss
    return 0.0


def clip_signal(value: float) -> float:
    """Clip a raw signal value to [-1.0, 1.0]."""
    return float(np.clip(value, -1.0, 1.0))
