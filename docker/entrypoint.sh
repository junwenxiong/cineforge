#!/usr/bin/env bash
set -euo pipefail

HOST="${STUDIO_HOST:-0.0.0.0}"
PORT="${STUDIO_PORT:-8866}"
FARM_PORT="${STUDIO_FARM_PORT:-8765}"
MODE="${STUDIO_MODE:-guest}"
INVITE_CODE="${STUDIO_INVITE_CODE:-}"
MAX_GUEST_JOBS="${STUDIO_MAX_GUEST_JOBS:-3}"
MAX_GUEST_DURATION="${STUDIO_MAX_GUEST_DURATION:-30}"
START_FARM="${START_FARM:-0}"
START_PUBLIC_TUNNEL="${START_PUBLIC_TUNNEL:-0}"

FARM_PID=""
STUDIO_PID=""

cleanup() {
  if [[ -n "$STUDIO_PID" ]] && kill -0 "$STUDIO_PID" 2>/dev/null; then
    kill "$STUDIO_PID" 2>/dev/null || true
    wait "$STUDIO_PID" 2>/dev/null || true
  fi
  if [[ -n "$FARM_PID" ]] && kill -0 "$FARM_PID" 2>/dev/null; then
    kill "$FARM_PID" 2>/dev/null || true
    wait "$FARM_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd /app

if [[ "$START_FARM" == "1" ]]; then
  if [[ -f /app/tools/film/farm_server.py ]]; then
    FARM_BIN="/app/tools/film/farm_server.py"
  else
    FARM_BIN="/app/automation/film/farm_server.py"
  fi
  echo "[CineForge Docker] Starting $(basename "$FARM_BIN") on 127.0.0.1:${FARM_PORT}..."
  python3 "$FARM_BIN" --port "$FARM_PORT" --reuse-token &
  FARM_PID=$!
  sleep 1
fi

ARGS=(
  --host "$HOST"
  --port "$PORT"
  --farm-port "$FARM_PORT"
  --max-guest-jobs "$MAX_GUEST_JOBS"
  --max-guest-duration "$MAX_GUEST_DURATION"
)

if [[ "$MODE" == "guest" ]]; then
  ARGS+=(--guest)
fi
if [[ -n "$INVITE_CODE" ]]; then
  ARGS+=(--invite-code "$INVITE_CODE")
fi

if [[ "$START_PUBLIC_TUNNEL" == "1" ]]; then
  if ! command -v cloudflared >/dev/null 2>&1; then
    echo "Error: cloudflared is not installed in this image; rebuild with INSTALL_CLOUDFLARED=1" >&2
    exit 1
  fi
  echo "[CineForge Docker] Starting Studio on 127.0.0.1:${PORT} (${MODE}) + cloudflared tunnel..."
  python3 /app/studio/server.py "${ARGS[@]}" &
  STUDIO_PID=$!
  sleep 1
  exec cloudflared tunnel --url "http://127.0.0.1:${PORT}"
else
  echo "[CineForge Docker] Starting Studio on ${HOST}:${PORT} (${MODE}, farm=:${FARM_PORT})..."
  exec python3 /app/studio/server.py "${ARGS[@]}"
fi
