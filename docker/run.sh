#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="${CINEFORGE_IMAGE:-cineforge-studio:latest}"
TAR_PATH="${SCRIPT_DIR}/cineforge-studio-latest.tar"
CONTAINER_NAME="${CINEFORGE_CONTAINER:-cineforge-studio}"

MODE="guest"
PORT="8866"
FARM_PORT="8765"
WITH_FARM="0"
PUBLIC="0"
INVITE_CODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) MODE="host"; shift ;;
    --guest) MODE="guest"; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --farm-port) FARM_PORT="$2"; shift 2 ;;
    --with-farm) WITH_FARM="1"; shift ;;
    --public) PUBLIC="1"; shift ;;
    --invite-code) INVITE_CODE="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: bash docker/run.sh [--guest|--host] [--port 8866] [--farm-port 8765] [--with-farm] [--public] [--invite-code CODE]
EOF
      exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  if [[ -f "$TAR_PATH" ]]; then
    echo "[CineForge Docker] Loading image from $TAR_PATH ..."
    docker load -i "$TAR_PATH"
  else
    echo "[CineForge Docker] Building $IMAGE_NAME ..."
    docker build -t "$IMAGE_NAME" -f "$ROOT_DIR/Dockerfile" "$ROOT_DIR"
  fi
fi

mkdir -p "$ROOT_DIR/studio/data" "$ROOT_DIR/films" "$ROOT_DIR/assets" "$ROOT_DIR/renders" "$ROOT_DIR/videos" "$ROOT_DIR/sources"

DOCKER_ARGS=(
  docker run --rm -it
  --name "$CONTAINER_NAME"
  --network host
  -e "STUDIO_MODE=${MODE}"
  -e "STUDIO_PORT=${PORT}"
  -e "STUDIO_FARM_PORT=${FARM_PORT}"
  -e "START_FARM=${WITH_FARM}"
  -e "START_PUBLIC_TUNNEL=${PUBLIC}"
  -e "STUDIO_INVITE_CODE=${INVITE_CODE}"
  -v "${ROOT_DIR}/studio/data:/app/studio/data:rw"
  -v "${ROOT_DIR}/films:/app/films:rw"
  -v "${ROOT_DIR}/assets:/app/assets:rw"
  -v "${ROOT_DIR}/renders:/app/renders:rw"
  -v "${ROOT_DIR}/videos:/app/videos:ro"
  -v "${ROOT_DIR}/sources:/app/sources:ro"
)

if [[ "$WITH_FARM" == "1" && -f "${ROOT_DIR}/.env" ]]; then
  DOCKER_ARGS+=(--env-file "${ROOT_DIR}/.env")
fi

DOCKER_ARGS+=("$IMAGE_NAME")
exec "${DOCKER_ARGS[@]}"
