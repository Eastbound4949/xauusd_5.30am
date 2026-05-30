"""Telegram notifications. Token/chat_id from env vars."""

import os
import requests

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send(msg: str) -> bool:
    if not TOKEN or not CHAT_ID:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def trade_opened(pos: dict):
    send(
        f"<b>XAUUSD BOT — TRADE OPENED</b>\n"
        f"Direction: {pos['direction'].upper()}\n"
        f"Entry:  ${pos['entry_price']:,.2f}\n"
        f"SL:     ${pos['sl']:,.2f}\n"
        f"TP:     ${pos['tp']:,.2f}\n"
        f"Risk:   ${pos['risk_amount']:.2f}"
    )


def trade_closed(closed: dict):
    emoji  = "" if closed["profit"] > 0 else ""
    pnl    = closed["profit"]
    reason = closed["exit_reason"].upper()
    send(
        f"{emoji} <b>XAUUSD BOT — TRADE CLOSED ({reason})</b>\n"
        f"Direction: {closed['direction'].upper()}\n"
        f"Exit:    ${closed['exit_price']:,.2f}\n"
        f"P&L:     ${pnl:+.2f}\n"
        f"Balance: ${closed['balance']:,.2f}"
    )


def no_signal(reason: str):
    send(f"<b>XAUUSD BOT — No signal</b>\n{reason}")


def daily_summary(stats: dict):
    send(
        f"<b>XAUUSD BOT — Daily Summary</b>\n"
        f"Balance:   ${stats['balance']:,.2f}\n"
        f"Trades:    {stats['trades']}\n"
        f"Win rate:  {stats['win_rate']:.1f}%\n"
        f"Net P&L:   ${stats['net']:+.2f}\n"
        f"PF:        {stats['pf']:.2f}"
    )
