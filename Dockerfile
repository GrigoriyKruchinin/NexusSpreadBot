# syntax=docker/dockerfile:1.7
# Nexus Spread Scanner image: one image, many roles (scanner / workers / beat / migrator).

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first (cached layer), then the project itself.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN groupadd --system --gid 10001 nexus \
    && useradd --system --uid 10001 --gid nexus --home-dir /app --shell /usr/sbin/nologin nexus
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
# D-01b: settings are BAKED into the image (no bind mount). A bind mount of a WSL path is not yet available when
# Docker Desktop restarts containers after `wsl --shutdown` / a reboot (the distro proxy mounts it later), so
# every app container used to die at start. The file holds no secrets (startup guard, A7); a settings change
# now needs `docker compose build` + recreate.
# `local.tom[l]`: the optional untracked overlay (owner's personal values); the glob makes it
# optional, nexus.toml always matches.
COPY config/nexus.toml config/local.tom[l] ./config/
COPY src/nexus/persistence/migrations ./src/nexus/persistence/migrations

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXUS_RUNTIME=container

USER nexus
CMD ["nexus", "--help"]
