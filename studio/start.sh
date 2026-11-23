#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="127.0.0.1"
PORT="8866"
PUBLIC_MODE="0"
GUEST_MODE="0"
INVITE_CODE=""
FARM_PORT="${STUDIO_FARM_PORT:-8765}"
MAX_GUEST_JOBS="${STUDIO_MAX_GUEST_JOBS:-3}"
MAX_GUEST_DURATION="${STUDIO_MAX_GUEST_DURATION:-30}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --lan)
      HOST="0.0.0.0"
      shift
      ;;
    --public)
      PUBLIC_MODE="1"
      shift
      ;;
    --guest|--guest-mode)
      GUEST_MODE="1"
      shift
      ;;
    --invite-code)
      INVITE_CODE="$2"
      shift 2
      ;;
    --farm-port)
      FARM_PORT="$2"
      shift 2
      ;;
    --max-guest-jobs)
      MAX_GUEST_JOBS="$2"
      shift 2
      ;;
    --max-guest-duration)
      MAX_GUEST_DURATION="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: bash studio/start.sh [--host 127.0.0.1] [--port 8866] [--lan] [--public] [--guest] [--invite-code CODE] [--farm-port 8765] [--max-guest-jobs 3] [--max-guest-duration 30]

Options:
  --host <ip>                Bind address (default: 127.0.0.1)
  --port <num>               Bind port (default: 8866; port 8765 is reserved for farm_server)
  --lan                      Listen on 0.0.0.0 for same-WiFi / office LAN evaluation
  --public                   Also launch a temporary cloudflared tunnel for external colleague beta testing
  --guest,--guest-mode       Enable zero-install external guest experience mode
  --invite-code <CODE>       Optional invite code for write APIs only (default: none / zero-friction)
  --farm-port <num>          Farm server port to coordinate with (default: 8765)
  --max-guest-jobs <num>     Max cloud generation jobs per guest session (default: 3)
  --max-guest-duration <sec> Max duration seconds per guest creation (default: 30)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "$PORT" == "8765" ]]; then
  echo "Error: Port 8765 is reserved for automation/film/farm_server.py. Please choose another port (e.g. 8866)." >&2
  exit 1
fi

SERVER_ARGS=(--port "$PORT" --farm-port "$FARM_PORT" --max-guest-jobs "$MAX_GUEST_JOBS" --max-guest-duration "$MAX_GUEST_DURATION")
if [[ "$GUEST_MODE" == "1" ]]; then
  SERVER_ARGS+=(--guest-mode)
fi
if [[ -n "$INVITE_CODE" ]]; then
  SERVER_ARGS+=(--invite-code "$INVITE_CODE")
fi

cd "$ROOT_DIR"

if [[ "$PUBLIC_MODE" == "1" ]]; then
  if command -v cloudflared >/dev/null 2>&1; then
    CF_BIN="$(command -v cloudflared)"
  elif [[ -x "$ROOT_DIR/.runtime/cloudflared/cloudflared" ]]; then
    CF_BIN="$ROOT_DIR/.runtime/cloudflared/cloudflared"
  else
    echo "Error: cloudflared not found in PATH or .runtime/cloudflared/cloudflared" >&2
    echo "Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" >&2
    exit 1
  fi
  echo "[CineForge Studio] Starting local server on http://127.0.0.1:${PORT} (guest=${GUEST_MODE}) ..."
  python3 "$ROOT_DIR/studio/server.py" --host 127.0.0.1 "${SERVER_ARGS[@]}" &
  SERVER_PID=$!
  cleanup() {
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM
  sleep 1
  echo "[CineForge Studio] Opening temporary public evaluation tunnel (Ctrl+C to close)..."
  exec "$CF_BIN" tunnel --url "http://127.0.0.1:${PORT}"
else
  echo "[CineForge Studio] Starting on http://${HOST}:${PORT} (guest=${GUEST_MODE}) ..."
  if [[ "$HOST" == "0.0.0.0" ]]; then
    echo "[CineForge Studio] LAN evaluation mode active. Share http://<your-lan-ip>:${PORT} with colleagues."
  fi
  exec python3 "$ROOT_DIR/studio/server.py" --host "$HOST" "${SERVER_ARGS[@]}"
fi
