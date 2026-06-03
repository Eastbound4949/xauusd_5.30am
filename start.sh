#!/bin/bash
# Start worker (background) + Streamlit dashboard (foreground)
# Both share the same trades.db in the same container

set -e

echo "=== XAUUSD 5:30AM Bot Starting ==="
echo "Starting scheduler worker in background..."
python -u worker.py &
WORKER_PID=$!
echo "Worker started (PID $WORKER_PID)"

echo "Starting Streamlit dashboard..."
exec streamlit run main.py \
    --server.port "${PORT:-8080}" \
    --server.address 0.0.0.0 \
    --server.headless true
