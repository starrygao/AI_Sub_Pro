#!/bin/bash
cd "$(dirname "$0")"
URL="http://127.0.0.1:18090"

if curl -fsS "$URL" >/dev/null 2>&1; then
    echo "AI Sub Pro is already running."
    open "$URL"
    exit 0
fi

echo "Starting AI Sub Pro..."
python3 app/main.py --headless &
PID=$!

cleanup() {
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

for _ in {1..60}; do
    if curl -fsS "$URL" >/dev/null 2>&1; then
        open "$URL"
        wait "$PID"
        exit $?
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        wait "$PID"
        exit $?
    fi
    sleep 0.5
done

echo "ERROR: AI Sub Pro did not become ready at $URL" >&2
exit 1
