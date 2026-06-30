"""
Paper trading engine.
Tracks open position, equity, and all trades in SQLite.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
import yfinance as yf
import pandas as pd

from config import CAPITAL_START, RISK_PCT, REWARD_RATIO, DB_PATH, SYMBOL, SYMBOL_FALLBACK


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                direction   TEXT,
                entry_time  TEXT,
                entry_price REAL,
                sl          REAL,
                tp          REAL,
                sl_dist     REAL,
                risk_amount REAL,
                exit_time   TEXT,
                exit_price  REAL,
                exit_reason TEXT,
                profit      REAL,
                balance     REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS equity_log (
                ts      TEXT,
                balance REAL,
                note    TEXT
            )
        """)
        # Seed balance if first run
        row = c.execute("SELECT value FROM state WHERE key='balance'").fetchone()
        if row is None:
            c.execute("INSERT INTO state VALUES ('balance', ?)", (str(CAPITAL_START),))
            c.execute("INSERT INTO state VALUES ('position', 'null')")
            c.execute("INSERT INTO equity_log VALUES (?,?,?)",
                      (utc_now(), CAPITAL_START, "init"))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


# ── State helpers ─────────────────────────────────────────────────────────────

def get_balance() -> float:
    with _conn() as c:
        row = c.execute("SELECT value FROM state WHERE key='balance'").fetchone()
        return float(row["value"])


def set_balance(bal: float):
    with _conn() as c:
        c.execute("UPDATE state SET value=? WHERE key='balance'", (str(bal),))
        c.execute("INSERT INTO equity_log VALUES (?,?,?)", (utc_now(), bal, ""))


def get_position() -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT value FROM state WHERE key='position'").fetchone()
        v = json.loads(row["value"])
        return v if v else None


def set_position(pos: dict | None):
    with _conn() as c:
        c.execute("UPDATE state SET value=? WHERE key='position'",
                  (json.dumps(pos),))


# ── Trade actions ─────────────────────────────────────────────────────────────

def open_trade(signal: dict) -> dict:
    """Open a paper trade from a signal dict. Returns the position."""
    bal = get_balance()
    risk_amount = bal * (RISK_PCT / 100)

    pos = {
        "direction":   signal["signal"],
        "entry_time":  utc_now(),
        "entry_price": signal["entry"],
        "sl":          signal["sl"],
        "tp":          signal["tp"],
        "sl_dist":     signal["sl_dist"],
        "risk_amount": risk_amount,
    }
    set_position(pos)
    return pos


def check_and_close(current_price: float | None = None) -> dict | None:
    """
    Check if open position hit SL or TP.
    Scans every 1-min bar since entry (not just the latest price) so a wick
    touch or a fill missed during downtime/redeploy is still caught.
    Returns closed trade dict if closed, else None.
    """
    pos = get_position()
    if pos is None:
        return None

    direction = pos["direction"]
    bars = _fetch_bars_since(pos["entry_time"])

    hit_sl = hit_tp = False
    exit_price = current_price

    if bars is not None and not bars.empty:
        for _, bar in bars.iterrows():
            bar_high, bar_low = float(bar["High"]), float(bar["Low"])
            if direction == "buy":
                hit_sl = bar_low  <= pos["sl"]
                hit_tp = bar_high >= pos["tp"]
            else:
                hit_sl = bar_high >= pos["sl"]
                hit_tp = bar_low  <= pos["tp"]
            if hit_sl or hit_tp:
                exit_price = pos["sl"] if hit_sl else pos["tp"]
                break
    else:
        # Fallback: no bar history available — check latest close only.
        if exit_price is None:
            exit_price = _fetch_price()
        if direction == "buy":
            if exit_price <= pos["sl"]:
                hit_sl = True
            elif exit_price >= pos["tp"]:
                hit_tp = True
        else:
            if exit_price >= pos["sl"]:
                hit_sl = True
            elif exit_price <= pos["tp"]:
                hit_tp = True

    if not hit_sl and not hit_tp:
        return None

    exit_reason = "tp" if hit_tp else "sl"
    profit = pos["risk_amount"] * REWARD_RATIO if hit_tp else -pos["risk_amount"]
    bal    = get_balance() + profit
    set_balance(bal)
    set_position(None)

    with _conn() as c:
        c.execute("""
            INSERT INTO trades
              (direction, entry_time, entry_price, sl, tp, sl_dist, risk_amount,
               exit_time, exit_price, exit_reason, profit, balance)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pos["direction"], pos["entry_time"], pos["entry_price"],
            pos["sl"], pos["tp"], pos["sl_dist"], pos["risk_amount"],
            utc_now(), exit_price, exit_reason, profit, bal,
        ))

    return {**pos, "exit_price": exit_price, "exit_reason": exit_reason,
            "profit": profit, "balance": bal}


def _fetch_price() -> float:
    for sym in (SYMBOL, SYMBOL_FALLBACK):
        df = yf.download(sym, period="1d", interval="1m",
                         auto_adjust=True, progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return float(df["Close"].iloc[-1])
    raise RuntimeError("Cannot fetch current price")


def _fetch_bars_since(entry_time_iso: str) -> pd.DataFrame | None:
    """1-min OHLC bars from entry_time to now, for SL/TP scan. None if unavailable."""
    for sym in (SYMBOL, SYMBOL_FALLBACK):
        df = yf.download(sym, period="2d", interval="1m",
                         auto_adjust=True, progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            idx = df.index
            idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
            df = df.set_axis(idx)

            entry_ts = pd.Timestamp(entry_time_iso)
            entry_ts = entry_ts.tz_localize("UTC") if entry_ts.tzinfo is None else entry_ts.tz_convert("UTC")

            return df[df.index >= entry_ts]
    return None


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_trades(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_equity_log() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM equity_log ORDER BY rowid DESC LIMIT 500"
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def log_event(msg: str, level: str = "INFO"):
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                ts TEXT, level TEXT, msg TEXT
            )
        """)
        c.execute("INSERT INTO events VALUES (?,?,?)", (utc_now(), level, msg))
        c.execute("""
            DELETE FROM events WHERE rowid NOT IN (
                SELECT rowid FROM events ORDER BY rowid DESC LIMIT 200
            )
        """)


def get_events(limit: int = 20) -> list[dict]:
    with _conn() as c:
        try:
            rows = c.execute(
                "SELECT ts, level, msg FROM events ORDER BY rowid DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []


def get_stats() -> dict:
    trades = get_trades(1000)
    wins   = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    total_profit = sum(t["profit"] for t in trades)
    gross_win    = sum(t["profit"] for t in wins)
    gross_loss   = abs(sum(t["profit"] for t in losses))
    return {
        "trades":   len(trades),
        "wins":     len(wins),
        "losses":   len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "pf":       gross_win / gross_loss if gross_loss else float("inf"),
        "net":      total_profit,
        "balance":  get_balance(),
    }
