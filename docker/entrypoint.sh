#!/usr/bin/env bash
set -euo pipefail

HOST="${STUDIO_HOST:-0.0.0.0}"
PORT="${STUDIO_PORT:-8866}"
FARM_PORT="${STUDIO_FARM_PORT:-8765}"
MODE="${STUDIO_MODE:-host}"
INVITE_CODE="${STUDIO_INVITE_CODE:-}"
MAX_GUEST_JOBS="${STUDIO_MAX_GUEST_JOBS:-3}"
MAX_GUEST_DURATION="${STUDIO_MAX_GUEST_DURATION:-30}"
START_FARM="${START_FARM:-0}"
START_FARM_TUNNEL="${START_FARM_TUNNEL:-1}"
START_PUBLIC_TUNNEL="${START_PUBLIC_TUNNEL:-0}"

FARM_PID=""
FARM_TUNNEL_PID=""
STUDIO_PID=""
FARM_TUNNEL_LOG=""

cleanup() {
  for pid in "$STUDIO_PID" "$FARM_TUNNEL_PID" "$FARM_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  if [[ -n "$FARM_TUNNEL_LOG" && -f "$FARM_TUNNEL_LOG" ]]; then
    rm -f "$FARM_TUNNEL_LOG"
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

  if [[ "$START_FARM_TUNNEL" == "1" ]] && command -v cloudflared >/dev/null 2>&1; then
    FARM_TUNNEL_LOG="$(mktemp)"
    cloudflared tunnel --protocol http2 --url "http://127.0.0.1:${FARM_PORT}" >"$FARM_TUNNEL_LOG" 2>&1 &
    FARM_TUNNEL_PID=$!
    FARM_URL=""
    for _ in $(seq 1 30); do
      FARM_URL="$(grep -Eo 'https://[A-Za-z0-9-]+\.trycloudflare\.com' "$FARM_TUNNEL_LOG" | head -n 1 || true)"
      [[ -n "$FARM_URL" ]] && break
      sleep 0.5
    done
    FARM_TOKEN=""
    if [[ -f /app/renders/farm/token ]]; then
      FARM_TOKEN="$(tr -d ' \r\n' < /app/renders/farm/token)"
    fi
    echo "========================================================================"
    echo "  CineForge Studio Web : http://127.0.0.1:${PORT}"
    echo "  Open in Google Colab : https://colab.research.google.com/github/junwenxiong/cineforge/blob/main/colab/CineForge_Colab_Worker.ipynb"
    [[ -n "$FARM_URL" ]] && echo "  Colab FARM_URL       : ${FARM_URL}"
    [[ -n "$FARM_TOKEN" ]] && echo "  Colab FARM_TOKEN     : ${FARM_TOKEN}"
    echo "========================================================================"
  fi
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
  exec cloudflared tunnel --protocol http2 --url "http://127.0.0.1:${PORT}"
else
  echo "[CineForge Docker] Starting Studio on ${HOST}:${PORT} (${MODE}, farm=:${FARM_PORT})..."
  if [[ "$START_FARM" == "1" ]]; then
    python3 /app/studio/server.py "${ARGS[@]}" &
    STUDIO_PID=$!
    wait "$STUDIO_PID"
  else
    exec python3 /app/studio/server.py "${ARGS[@]}"
  fi
fi
