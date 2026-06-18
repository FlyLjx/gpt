FROM python:3.13-slim

ARG APT_MIRROR=https://mirrors.aliyun.com/debian

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    WARP_SOCKS_PORT=40000 \
    WARP_HTTP_PORT=8118

RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s#http://deb.debian.org/debian-security#${APT_MIRROR}-security#g; s#http://deb.debian.org/debian#${APT_MIRROR}#g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
      curl \
      gnupg \
      ca-certificates \
      lsb-release \
      procps \
    && curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ bookworm main" > /etc/apt/sources.list.d/cloudflare-client.list \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends cloudflare-warp \
    && pip install pproxy==2.7.9 \
    && rm -rf /var/lib/apt/lists/*

COPY docker/warp/entrypoint.sh /usr/local/bin/warp-entrypoint.sh

RUN chmod +x /usr/local/bin/warp-entrypoint.sh

EXPOSE 8118

ENTRYPOINT ["/usr/local/bin/warp-entrypoint.sh"]
