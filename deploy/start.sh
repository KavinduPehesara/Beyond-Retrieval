#!/usr/bin/env bash
# Start the API, the page and the proxy in front of them.
#
# set -e alone would not notice a child dying in the background, which is the
# failure that matters here: a container whose API has quietly exited still
# serves the page, and the page then fails one request at a time instead of
# saying what is wrong. So each child is waited on and any exit takes the
# container down, where the platform will restart it and the logs will say why.

set -euo pipefail

: "${SLR_DB_PATH:=/data/slr.db}"
: "${SLR_LIVE_DB_PATH:=/data/live_reviews.sqlite3}"
: "${SLR_RUNS_DIR:=/data/runs}"
: "${SLR_API_URL:=http://127.0.0.1:8000}"
export SLR_DB_PATH SLR_LIVE_DB_PATH SLR_RUNS_DIR SLR_API_URL

mkdir -p "$(dirname "$SLR_DB_PATH")" "$(dirname "$SLR_LIVE_DB_PATH")" "$SLR_RUNS_DIR" /tmp/nginx-body

if [ -z "${GOOGLE_REDIRECT_URI:-}" ]; then
  echo "WARNING: GOOGLE_REDIRECT_URI is unset, so sign-in will fail." >&2
  echo "         Set it to https://<your-space>.hf.space/auth/google/callback" >&2
fi
if [ -z "${ALLOWED_EMAILS:-}" ]; then
  echo "WARNING: ALLOWED_EMAILS is unset. Anyone with a Google account can" >&2
  echo "         sign in and spend this server's model keys." >&2
fi

python -m uvicorn slr.api.app:app --host 127.0.0.1 --port 8000 --workers 1 &
api=$!

streamlit run app/Home.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --browser.gatherUsageStats false &
page=$!

nginx -c /app/deploy/nginx.conf -g 'daemon off;' &
proxy=$!

# Whichever goes first ends the container.
wait -n "$api" "$page" "$proxy"
code=$?
echo "a process exited with status $code; shutting down" >&2
kill "$api" "$page" "$proxy" 2>/dev/null || true
exit "$code"
