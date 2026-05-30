"""Bot configuration — edit here first."""

# Capital & risk
CAPITAL_START   = 1000.0   # paper trading starting balance (USD)
RISK_PCT        = 1.5      # % of balance risked per trade
REWARD_RATIO    = 3.5      # take-profit = RR × stop-loss distance

# Strategy params (10yr optimised)
EMA_PERIOD      = 200
ADX_MIN         = 20
ADX_PERIOD      = 14
RANGE_HOURS     = 8        # overnight range lookback (H1 bars)
THRESHOLD       = 0.25     # top/bottom 25% of range triggers signal
SL_BUFFER_ATR   = 0.25     # SL placed ATR*buf beyond range extreme
ATR_PERIOD      = 14
MAX_DAILY_LOSS  = 3.0      # halt trading if daily loss > 3%

# Timing
ENTRY_HOUR_UTC  = 5        # 05:00 UTC = 5:30 AM UK (GMT) / 6:30 AM BST
ENTRY_HOUR_UTC2 = 6        # also check 06:00 bar (BST offset)

# Data
SYMBOL          = "GC=F"   # Gold futures (yfinance) — fallback: XAUUSD=X
SYMBOL_FALLBACK = "XAUUSD=X"
DATA_LOOKBACK   = "60d"    # need 200+ H1 bars for EMA200 warmup (~13 trading days min)

# Database
DB_PATH         = "trades.db"
