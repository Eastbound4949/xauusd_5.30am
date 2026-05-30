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
    Returns closed trade dict if closed, else None.
    """
    pos = get_position()
    if pos is None:
        return None

    if current_price is None:
        current_price = _fetch_price()

    direction = pos["direction"]
    hit_sl = hit_tp = False

    if direction == "buy":
        if current_price <= pos["sl"]:
            hit_sl = True
        elif current_price >= pos["tp"]:
            hit_tp = True
    else:
        if current_price >= pos["sl"]:
            hit_sl = True
        elif current_price <= pos["tp"]:
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
            utc_now(), current_price, exit_reason, profit, bal,
        ))

    return {**pos, "exit_price": current_price, "exit_reason": exit_reason,
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


def get_stats() -> dict:
    trades = get_trades(1000)
    if not trades:
        return {"trades": 0}
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
