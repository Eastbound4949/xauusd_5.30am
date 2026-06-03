"""
Standalone scheduler worker for XAUUSD 5:30AM bot.
Runs independently of Streamlit — starts at container launch.
"""

import logging
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("worker")

import trader
import scheduler as sched_mod


def main():
    log.info("=" * 50)
    log.info("  XAUUSD 5:30AM BOT — Worker Starting")
    log.info("  Signal check : 05:05 UTC daily (Mon-Fri)")
    log.info("  Position mon : every 5 min")
    log.info("=" * 50)

    trader.init_db()
    sched = sched_mod.start()

    def _shutdown(signum, frame):
        log.info("Worker shutting down...")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
