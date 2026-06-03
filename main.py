"""
XAUUSD 5:30 AM Strategy — Paper Trading Dashboard
Streamlit app + embedded APScheduler.
Deploy: Railway (Procfile: streamlit run main.py --server.port $PORT)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

import trader
from config import (
    CAPITAL_START, RISK_PCT, REWARD_RATIO,
    EMA_PERIOD, ADX_MIN, RANGE_HOURS, THRESHOLD,
)

st.set_page_config(
    page_title="XAUUSD 5:30AM Bot",
    page_icon="",
    layout="wide",
)

trader.init_db()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("XAUUSD 5:30 AM Paper Trading Bot")
st.caption(
    f"Strategy: EMA{EMA_PERIOD} trend + ADX>{ADX_MIN} filter | "
    f"{RANGE_HOURS}hr range | {THRESHOLD*100:.0f}% threshold | "
    f"1.5% risk | {REWARD_RATIO}:1 R:R"
)

# ── Top metrics ───────────────────────────────────────────────────────────────
stats    = trader.get_stats()
balance  = trader.get_balance()
pos      = trader.get_position()
net_pct  = (balance - CAPITAL_START) / CAPITAL_START * 100

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Balance",     f"${balance:,.2f}", f"{net_pct:+.1f}%")
col2.metric("Trades",      stats.get("trades", 0))
col3.metric("Win Rate",    f"{stats.get('win_rate', 0):.1f}%")
col4.metric("Profit Factor", f"{stats.get('pf', 0):.2f}" if stats.get('trades') else "—")
col5.metric("Net P&L",     f"${stats.get('net', 0):+.2f}")

st.divider()

# ── Open position ─────────────────────────────────────────────────────────────
st.subheader("Open Position")
if pos:
    pc1, pc2, pc3, pc4, pc5 = st.columns(5)
    pc1.metric("Direction",    pos["direction"].upper())
    pc2.metric("Entry",        f"${pos['entry_price']:,.2f}")
    pc3.metric("Stop Loss",    f"${pos['sl']:,.2f}")
    pc4.metric("Take Profit",  f"${pos['tp']:,.2f}")
    pc5.metric("Risk",         f"${pos['risk_amount']:.2f}")
    st.caption(f"Opened: {pos['entry_time']}")
else:
    st.info("No open position — waiting for 05:05 UTC signal check.")

st.divider()

# ── Equity curve ──────────────────────────────────────────────────────────────
st.subheader("Equity Curve")
eq_log = trader.get_equity_log()
if len(eq_log) > 1:
    df_eq = pd.DataFrame(eq_log)
    df_eq["ts"] = pd.to_datetime(df_eq["ts"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_eq["ts"], y=df_eq["balance"],
        mode="lines", name="Balance",
        line=dict(color="#00e676", width=2),
        fill="tozeroy", fillcolor="rgba(0,230,118,0.08)",
    ))
    fig.add_hline(y=CAPITAL_START, line_dash="dot", line_color="gray",
                  annotation_text="Start")
    fig.update_layout(
        height=300, template="plotly_dark",
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis_title="Balance (USD)",
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Equity curve will appear after first trade.")

# ── Trade history ─────────────────────────────────────────────────────────────
st.subheader("Trade History")
trades = trader.get_trades(100)
if trades:
    df_t = pd.DataFrame(trades)
    df_t["entry_time"] = pd.to_datetime(df_t["entry_time"]).dt.strftime("%Y-%m-%d %H:%M")
    df_t["exit_time"]  = pd.to_datetime(df_t["exit_time"]).dt.strftime("%Y-%m-%d %H:%M")
    df_t["profit"]     = df_t["profit"].map(lambda x: f"${x:+.2f}")
    df_t["balance"]    = df_t["balance"].map(lambda x: f"${x:,.2f}")
    df_t["entry_price"] = df_t["entry_price"].map(lambda x: f"${x:,.2f}")
    df_t["exit_price"]  = df_t["exit_price"].map(lambda x: f"${x:,.2f}")
    st.dataframe(
        df_t[["direction","entry_time","entry_price","exit_time",
              "exit_price","exit_reason","profit","balance"]].rename(columns={
            "entry_time": "Entry Time", "exit_time": "Exit Time",
            "entry_price": "Entry", "exit_price": "Exit",
            "exit_reason": "Reason", "direction": "Dir",
        }),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("No completed trades yet.")

# ── Event log ─────────────────────────────────────────────────────────────────
st.subheader("Bot Log")
events = trader.get_events(20)
if events:
    for ev in events[:20]:
        colour = {"TRADE": "green", "ERROR": "red"}.get(ev["level"], "gray")
        st.markdown(
            f"<span style='color:{colour};font-family:monospace'>"
            f"{ev['msg']}</span>",
            unsafe_allow_html=True,
        )
else:
    st.caption("No events yet.")

# ── Config sidebar ────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Config")
    st.write(f"**Starting capital:** ${CAPITAL_START:,.0f}")
    st.write(f"**Risk per trade:** {RISK_PCT}%")
    st.write(f"**R:R:** {REWARD_RATIO}:1")
    st.write(f"**EMA period:** {EMA_PERIOD}")
    st.write(f"**ADX min:** {ADX_MIN}")
    st.write(f"**Range hours:** {RANGE_HOURS}")
    st.write(f"**Threshold:** {THRESHOLD*100:.0f}%")
    st.divider()
    st.write(f"**Entry time:** 05:05 UTC daily")
    st.write(f"**Monitor:** every 5 min")
    st.divider()
    if st.button("Force signal check now"):
        import scheduler as _sched
        _sched.job_check_signal()
        st.rerun()
    if st.button("Force position check now"):
        import scheduler as _sched
        _sched.job_monitor_position()
        st.rerun()
    st.divider()
    st.caption(f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")

# Auto-refresh every 60s
st.markdown(
    "<meta http-equiv='refresh' content='60'>",
    unsafe_allow_html=True,
)
