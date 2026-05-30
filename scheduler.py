"""
APScheduler jobs:
  - 05:05 UTC  daily  → check signal, open trade if triggered
  - every 5 min       → check open position for SL/TP hit
"""

import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import trader
import strategy
import notify

log = logging.getLogger("scheduler")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

_events: list[dict] = []   # in-memory event log for dashboard


def _log_event(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _events.insert(0, {"ts": ts, "msg": msg, "level": level})
    if len(_events) > 100:
        _events.pop()
    log.info(msg)


def get_events() -> list[dict]:
    return _events


def job_check_signal():
    """Run at 05:05 UTC — evaluate strategy signal."""
    _log_event("Signal check started")
    try:
        pos = trader.get_position()
        if pos:
            _log_event(f"Position already open ({pos['direction']} @ {pos['entry_price']:.2f}) — skip")
            return

        sig = strategy.get_signal()
        _log_event(f"Signal result: {sig.get('reason', '?')}")

        if sig["signal"] in ("buy", "sell"):
            opened = trader.open_trade(sig)
            _log_event(
                f"TRADE OPENED: {opened['direction'].upper()} @ {opened['entry_price']:.2f} "
                f"SL={opened['sl']:.2f} TP={opened['tp']:.2f} Risk=${opened['risk_amount']:.2f}",
                "TRADE"
            )
            notify.trade_opened(opened)
        else:
            notify.no_signal(sig.get("reason", "no reason"))
    except Exception as e:
        _log_event(f"Signal check error: {e}", "ERROR")


def job_monitor_position():
    """Run every 5 min — check if open position hit SL/TP."""
    try:
        closed = trader.check_and_close()
        if closed:
            pnl_sign = "+" if closed["profit"] >= 0 else ""
            _log_event(
                f"TRADE CLOSED ({closed['exit_reason'].upper()}): "
                f"{closed['direction'].upper()} "
                f"exit={closed['exit_price']:.2f} "
                f"PnL={pnl_sign}${closed['profit']:.2f} "
                f"Balance=${closed['balance']:.2f}",
                "TRADE"
            )
            notify.trade_closed(closed)
    except Exception as e:
        _log_event(f"Monitor error: {e}", "ERROR")


def start() -> BackgroundScheduler:
    trader.init_db()
    sched = BackgroundScheduler(timezone="UTC")

    # Signal check at 05:05 UTC (5 min after entry bar closes)
    sched.add_job(job_check_signal,
                  CronTrigger(hour=5, minute=5, timezone="UTC"),
                  id="signal", replace_existing=True)

    # Position monitor every 5 minutes
    sched.add_job(job_monitor_position,
                  IntervalTrigger(minutes=5),
                  id="monitor", replace_existing=True)

    # Daily summary at 08:00 UTC
    sched.add_job(
        lambda: notify.daily_summary(trader.get_stats()),
        CronTrigger(hour=8, minute=0, timezone="UTC"),
        id="summary", replace_existing=True,
    )

    sched.start()
    _log_event("Scheduler started — signal job at 05:05 UTC, monitor every 5 min")
    return sched
