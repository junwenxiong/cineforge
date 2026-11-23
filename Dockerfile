ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG TARGETARCH=amd64
ARG INSTALL_CLOUDFLARED=1

LABEL org.opencontainers.image.title="CineForge Studio" \
      org.opencontainers.image.description="CineForge Studio local web UI + Google Colab multi-model compute coordinator"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=8866 \
    STUDIO_FARM_PORT=8765 \
    STUDIO_MODE=host \
    STUDIO_MAX_GUEST_JOBS=3 \
    STUDIO_MAX_GUEST_DURATION=30 \
    START_FARM=0 \
    START_FARM_TUNNEL=1 \
    START_PUBLIC_TUNNEL=0

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      fonts-wqy-zenhei \
      curl \
      bash \
      ca-certificates \
      libgles2 \
      libegl1 \
    && rm -rf /var/lib/apt/lists/* \
    && if [ "${INSTALL_CLOUDFLARED}" = "1" ]; then \
         CF_ARCH="${TARGETARCH:-amd64}"; \
         case "${CF_ARCH}" in \
           amd64|x86_64) CF_BIN="cloudflared-linux-amd64" ;; \
           arm64|aarch64) CF_BIN="cloudflared-linux-arm64" ;; \
           *) CF_BIN="cloudflared-linux-amd64" ;; \
         esac; \
         curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${CF_BIN}" -o /usr/local/bin/cloudflared \
         && chmod 755 /usr/local/bin/cloudflared \
         || rm -f /usr/local/bin/cloudflared; \
       fi

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY .env.example /app/.env.example
COPY colab /app/colab
COPY studio /app/studio
COPY tools /app/tools
COPY examples /app/examples
COPY docs /app/docs
COPY docker/entrypoint.sh /usr/local/bin/cineforge-entrypoint.sh

RUN chmod +x /usr/local/bin/cineforge-entrypoint.sh /app/studio/start.sh \
    && mkdir -p /app/studio/data/uploads /app/studio/data/previews /app/studio/data/dispatch /app/studio/data/thumbs \
                /app/films /app/assets /app/videos /app/sources /app/renders

EXPOSE 8866 8765

HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${STUDIO_PORT:-8866}/api/health" >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/cineforge-entrypoint.sh"]
