ARG BUILDPLATFORM
ARG TARGETPLATFORM
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
ARG NO_PROXY

FROM --platform=$BUILDPLATFORM node:20-alpine AS web-build
WORKDIR /app/register_console/frontend

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=$HTTP_PROXY \
    HTTPS_PROXY=$HTTPS_PROXY \
    ALL_PROXY=$ALL_PROXY \
    NO_PROXY=$NO_PROXY \
    http_proxy=$HTTP_PROXY \
    https_proxy=$HTTPS_PROXY \
    all_proxy=$ALL_PROXY \
    no_proxy=$NO_PROXY

COPY register_console/frontend/package.json ./
COPY register_console/frontend/package-lock.json ./
RUN npm ci

COPY register_console/frontend ./
RUN npm run build

FROM --platform=$TARGETPLATFORM python:3.13-slim AS app

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
ARG NO_PROXY

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GIT_PYTHON_REFRESH=quiet \
    TZ=Asia/Shanghai \
    UV_LINK_MODE=copy \
    CHATGPT2API_REG_APP_ROOT=/app/runtime \
    HTTP_PROXY=$HTTP_PROXY \
    HTTPS_PROXY=$HTTPS_PROXY \
    ALL_PROXY=$ALL_PROXY \
    NO_PROXY=$NO_PROXY \
    http_proxy=$HTTP_PROXY \
    https_proxy=$HTTPS_PROXY \
    all_proxy=$ALL_PROXY \
    no_proxy=$NO_PROXY

WORKDIR /app

RUN apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
      git \
      libpq-dev \
      gcc \
      openssl \
      tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY reg ./reg
COPY register_console ./register_console
COPY services ./services
COPY utils ./utils
COPY api ./api
COPY VERSION ./VERSION

RUN mkdir -p /app/runtime

EXPOSE 8080

CMD ["/app/.venv/bin/uvicorn", "register_console.backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--access-log"]
