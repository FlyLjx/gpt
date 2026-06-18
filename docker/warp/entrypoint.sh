#!/bin/sh
set -eu

SOCKS_PORT="${WARP_SOCKS_PORT:-40000}"
HTTP_PORT="${WARP_HTTP_PORT:-8118}"
STATE_DIR="${WARP_STATE_DIR:-/var/lib/cloudflare-warp}"
LOG_DIR="${WARP_LOG_DIR:-/var/log/warp-local}"

mkdir -p "$STATE_DIR" "$LOG_DIR"

warp-svc >"$LOG_DIR/warp-svc.log" 2>&1 &
WARP_SVC_PID=$!

cleanup() {
  kill "$WARP_SVC_PID" 2>/dev/null || true
  kill "$PPROXY_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

wait_for_warp() {
  i=0
  while [ "$i" -lt 30 ]; do
    if warp-cli --accept-tos status >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  return 1
}

wait_for_warp

if ! warp-cli --accept-tos registration show >/dev/null 2>&1; then
  warp-cli --accept-tos registration new
fi

warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port "$SOCKS_PORT"
warp-cli --accept-tos connect

i=0
while [ "$i" -lt 45 ]; do
  if warp-cli --accept-tos status 2>/dev/null | grep -q "Connected"; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

python -m pproxy -l "http://0.0.0.0:${HTTP_PORT}" -r "socks5://127.0.0.1:${SOCKS_PORT}" >"$LOG_DIR/pproxy.log" 2>&1 &
PPROXY_PID=$!

wait "$PPROXY_PID"
