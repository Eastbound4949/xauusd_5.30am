"""
Signal generation for XAUUSD 5:30 AM strategy.
Extracted from backtest.py — same logic, adapted for live data.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from config import (
    SYMBOL, SYMBOL_FALLBACK, DATA_LOOKBACK,
    ATR_PERIOD, EMA_PERIOD, ADX_PERIOD, ADX_MIN,
    RANGE_HOURS, THRESHOLD, SL_BUFFER_ATR, REWARD_RATIO,
    ENTRY_HOUR_UTC, ENTRY_HOUR_UTC2,
)


# ── Indicators ────────────────────────────────────────────────────────────────

def _atr(df, period=ATR_PERIOD):
    h, lo, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _ema(series, period=EMA_PERIOD):
    return series.ewm(span=period, adjust=False).mean()


def _adx(df, period=ADX_PERIOD):
    h, lo, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    plus_dm  = h.diff().clip(lower=0)
    minus_dm = (-lo.diff()).clip(lower=0)
    plus_dm  = plus_dm.where(plus_dm  > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm,  0.0)
    atr_s    = tr.ewm(alpha=1/period, adjust=False).mean()
    safe_atr = atr_s.replace(0, np.nan)
    plus_di  = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / safe_atr
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / safe_atr
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False).mean()


# ── Data fetch ────────────────────────────────────────────────────────────────

def fetch_h1(lookback: str = DATA_LOOKBACK) -> pd.DataFrame:
    """Fetch H1 OHLCV from yfinance. Returns UTC-indexed DataFrame."""
    for sym in (SYMBOL, SYMBOL_FALLBACK):
        df = yf.download(sym, period=lookback, interval="1h",
                         auto_adjust=True, progress=False)
        if not df.empty:
            break
    if df.empty:
        raise RuntimeError("yfinance returned no data for XAUUSD")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    return df


# ── Signal ────────────────────────────────────────────────────────────────────

def get_signal(df: pd.DataFrame | None = None) -> dict:
    """
    Evaluate strategy on latest H1 data.

    Returns dict:
      signal    : "buy" | "sell" | None
      entry     : float (next bar open approximation = current close)
      sl        : float
      tp        : float
      sl_dist   : float
      bar_time  : pd.Timestamp
      close     : float
      ema200    : float
      adx       : float
      adx_ok    : bool
      pos_pct   : float  (0-100, position in overnight range)
      reason    : str    (why no signal, or signal reason)
    """
    if df is None:
        df = fetch_h1()

    if len(df) < EMA_PERIOD + RANGE_HOURS + 5:
        return {"signal": None, "reason": "insufficient data"}

    df = df.copy()
    df["atr"]   = _atr(df)
    df["ema"]   = _ema(df["close"])
    df["adx"]   = _adx(df)

    # Use the most recent completed bar
    bar      = df.iloc[-1]
    bar_time = df.index[-1]

    # Only act on 05:00 or 06:00 UTC bars
    if bar_time.hour not in (ENTRY_HOUR_UTC, ENTRY_HOUR_UTC2):
        return {
            "signal": None,
            "reason": f"not entry window (bar hour={bar_time.hour} UTC)",
            "bar_time": bar_time,
            "close": float(bar["close"]),
            "ema200": float(bar["ema"]),
            "adx": float(bar["adx"]),
        }

    # Overnight range
    lookback_bars = df.iloc[-(RANGE_HOURS + 1):-1]
    range_high = float(lookback_bars["high"].max())
    range_low  = float(lookback_bars["low"].min())
    range_size = range_high - range_low
    if range_size < 1.0:
        return {"signal": None, "reason": f"range too small ({range_size:.2f})"}

    close     = float(bar["close"])
    atr_val   = float(bar["atr"])
    ema_val   = float(bar["ema"])
    adx_val   = float(bar["adx"])
    pos_pct   = (close - range_low) / range_size * 100

    # ADX filter
    adx_ok = adx_val >= ADX_MIN
    if not adx_ok:
        return {
            "signal": None, "reason": f"ADX {adx_val:.1f} < {ADX_MIN}",
            "bar_time": bar_time, "close": close,
            "ema200": ema_val, "adx": adx_val, "adx_ok": False,
            "pos_pct": pos_pct,
        }

    pos_in_range = (close - range_low) / range_size
    signal = None
    if pos_in_range <= THRESHOLD and close > ema_val:
        signal = "buy"
    elif pos_in_range >= (1 - THRESHOLD) and close < ema_val:
        signal = "sell"

    if signal is None:
        trend = "above" if close > ema_val else "below"
        return {
            "signal": None,
            "reason": f"no setup (pos={pos_pct:.1f}% in range, price {trend} EMA200)",
            "bar_time": bar_time, "close": close,
            "ema200": ema_val, "adx": adx_val, "adx_ok": adx_ok,
            "pos_pct": pos_pct,
        }

    entry = close  # approximation; live bot uses next bar open
    if signal == "buy":
        sl_dist = max(entry - (range_low - SL_BUFFER_ATR * atr_val), atr_val * 0.5)
        sl = entry - sl_dist
        tp = entry + REWARD_RATIO * sl_dist
    else:
        sl_dist = max((range_high + SL_BUFFER_ATR * atr_val) - entry, atr_val * 0.5)
        sl = entry + sl_dist
        tp = entry - REWARD_RATIO * sl_dist

    return {
        "signal":   signal,
        "entry":    entry,
        "sl":       sl,
        "tp":       tp,
        "sl_dist":  sl_dist,
        "bar_time": bar_time,
        "close":    close,
        "ema200":   ema_val,
        "adx":      adx_val,
        "adx_ok":   adx_ok,
        "pos_pct":  pos_pct,
        "reason":   f"{signal.upper()} signal — pos={pos_pct:.1f}%, ADX={adx_val:.1f}",
    }
