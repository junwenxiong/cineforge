#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="127.0.0.1"
PORT="8866"
PUBLIC_MODE="0"
GUEST_MODE="0"
WITH_FARM="0"
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
    --with-farm)
      WITH_FARM="1"
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
Usage: bash studio/start.sh [--with-farm] [--host 127.0.0.1] [--port 8866] [--lan] [--public] [--guest] [--invite-code CODE] [--farm-port 8765]

Options:
  --with-farm                One-click mode: also start farm_server.py + cloudflared tunnel for Google Colab
  --host <ip>                Bind address (default: 127.0.0.1)
  --port <num>               Bind port (default: 8866; port 8765 is reserved for farm_server)
  --lan                      Listen on 0.0.0.0 for same-WiFi / office LAN evaluation
  --public                   Also launch a temporary cloudflared tunnel for external web preview
  --guest,--guest-mode       Enable zero-install external guest experience mode
  --invite-code <CODE>       Optional invite code for write APIs only (default: none)
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
  echo "Error: Port 8765 is reserved for tools/film/farm_server.py. Please choose another port (e.g. 8866)." >&2
  exit 1
fi

ensure_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    echo "$(command -v cloudflared)"
    return 0
  fi
  if [[ -x "$ROOT_DIR/.runtime/cloudflared/cloudflared" ]]; then
    echo "$ROOT_DIR/.runtime/cloudflared/cloudflared"
    return 0
  fi
  local os_name arch_name dl_url target_dir target_bin
  os_name="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch_name="$(uname -m)"
  if [[ "$os_name" == "linux" ]]; then
    case "$arch_name" in
      x86_64|amd64) dl_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
      aarch64|arm64) dl_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
      *) dl_url="" ;;
    esac
    if [[ -n "$dl_url" ]] && command -v curl >/dev/null 2>&1; then
      target_dir="$ROOT_DIR/.runtime/cloudflared"
      target_bin="$target_dir/cloudflared"
      mkdir -p "$target_dir"
      echo "[CineForge] Downloading cloudflared binary to .runtime/cloudflared/ ..." >&2
      if curl -fsSL "$dl_url" -o "$target_bin"; then
        chmod 755 "$target_bin"
        echo "$target_bin"
        return 0
      fi
      rm -f "$target_bin"
    fi
  fi
  echo "Error: cloudflared not found. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" >&2
  return 1
}

SERVER_ARGS=(--port "$PORT" --farm-port "$FARM_PORT" --max-guest-jobs "$MAX_GUEST_JOBS" --max-guest-duration "$MAX_GUEST_DURATION")
if [[ "$GUEST_MODE" == "1" ]]; then
  SERVER_ARGS+=(--guest-mode)
fi
if [[ -n "$INVITE_CODE" ]]; then
  SERVER_ARGS+=(--invite-code "$INVITE_CODE")
fi

cd "$ROOT_DIR"

FARM_PID=""
FARM_TUNNEL_PID=""
SERVER_PID=""
FARM_TUNNEL_LOG=""

cleanup() {
  for pid in "$SERVER_PID" "$FARM_TUNNEL_PID" "$FARM_PID"; do
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

if [[ "$WITH_FARM" == "1" ]]; then
  FARM_BIN="$ROOT_DIR/tools/film/farm_server.py"
  [[ -f "$FARM_BIN" ]] || FARM_BIN="$ROOT_DIR/automation/film/farm_server.py"
  echo "[CineForge] Starting local farm coordinator on 127.0.0.1:${FARM_PORT} ..."
  python3 "$FARM_BIN" --port "$FARM_PORT" --reuse-token &
  FARM_PID=$!
  sleep 1

  CF_BIN="$(ensure_cloudflared)"
  FARM_TUNNEL_LOG="$(mktemp)"
  "$CF_BIN" tunnel --protocol http2 --url "http://127.0.0.1:${FARM_PORT}" >"$FARM_TUNNEL_LOG" 2>&1 &
  FARM_TUNNEL_PID=$!
  FARM_URL=""
  for _ in $(seq 1 30); do
    FARM_URL="$(grep -Eo 'https://[A-Za-z0-9-]+\.trycloudflare\.com' "$FARM_TUNNEL_LOG" | head -n 1 || true)"
    [[ -n "$FARM_URL" ]] && break
    sleep 0.5
  done
  FARM_TOKEN=""
  if [[ -f "$ROOT_DIR/renders/farm/token" ]]; then
    FARM_TOKEN="$(tr -d ' \r\n' < "$ROOT_DIR/renders/farm/token")"
  fi
  echo ""
  echo "========================================================================"
  echo "  CineForge Studio Web : http://${HOST}:${PORT}"
  echo "  Open in Google Colab : https://colab.research.google.com/github/junwenxiong/cineforge/blob/main/colab/CineForge_Colab_Worker.ipynb"
  if [[ -n "$FARM_URL" ]]; then
    echo "  Colab FARM_URL       : ${FARM_URL}"
  else
    echo "  Colab FARM_URL       : (tunnel still connecting; check network/proxy)"
  fi
  if [[ -n "$FARM_TOKEN" ]]; then
    echo "  Colab FARM_TOKEN     : ${FARM_TOKEN}"
  fi
  echo "  Keep this terminal open while Colab is rendering. Press Ctrl+C to stop."
  echo "========================================================================"
  echo ""
fi

if [[ "$PUBLIC_MODE" == "1" ]]; then
  CF_BIN="$(ensure_cloudflared)"
  echo "[CineForge Studio] Starting local server on http://127.0.0.1:${PORT} (guest=${GUEST_MODE}) ..."
  python3 "$ROOT_DIR/studio/server.py" --host 127.0.0.1 "${SERVER_ARGS[@]}" &
  SERVER_PID=$!
  sleep 1
  echo "[CineForge Studio] Opening temporary public evaluation tunnel (Ctrl+C to close)..."
  exec "$CF_BIN" tunnel --protocol http2 --url "http://127.0.0.1:${PORT}"
else
  echo "[CineForge Studio] Starting on http://${HOST}:${PORT} (guest=${GUEST_MODE}) ..."
  if [[ "$HOST" == "0.0.0.0" ]]; then
    echo "[CineForge Studio] LAN evaluation mode active. Share http://<your-lan-ip>:${PORT} with colleagues."
  fi
  if [[ "$WITH_FARM" == "1" ]]; then
    python3 "$ROOT_DIR/studio/server.py" --host "$HOST" "${SERVER_ARGS[@]}" &
    SERVER_PID=$!
    wait "$SERVER_PID"
  else
    exec python3 "$ROOT_DIR/studio/server.py" --host "$HOST" "${SERVER_ARGS[@]}"
  fi
fi
