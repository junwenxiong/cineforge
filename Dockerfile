ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="CineForge Studio" \
      org.opencontainers.image.description="CineForge Studio visual AI film workflow + shared Colab farm coordinator"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=8866 \
    STUDIO_FARM_PORT=8765 \
    STUDIO_MODE=guest \
    STUDIO_MAX_GUEST_JOBS=3 \
    STUDIO_MAX_GUEST_DURATION=30 \
    START_FARM=0 \
    START_PUBLIC_TUNNEL=0

ARG INSTALL_CLOUDFLARED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      fonts-wqy-zenhei \
      curl \
      bash \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && if [ "${INSTALL_CLOUDFLARED}" = "1" ]; then \
         curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" -o /usr/local/bin/cloudflared \
         && chmod 755 /usr/local/bin/cloudflared \
         || rm -f /usr/local/bin/cloudflared; \
       fi

WORKDIR /app

COPY requirements.txt /app/requirements.txt
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
