# 02 - Tech Stack

Sources: `pyproject.toml`, `uv.lock` (full list: `evidence/uv-lock-packages.txt`), `Dockerfile`, `docker-compose.local.yml`, `.pre-commit-config.yaml`.

## Language / runtime
Python `>=3.12,<3.13` (`requires-python`; `.python-version` = 3.12; lock `==3.12.*`). Docker base `python:3.12-slim`. Package manager uv (image pins uv 0.9.8). Build backend hatchling.

## Runtime dependencies (declared -> locked)
| Lib | Declared | Locked |
|---|---|---|
| ccxt | >=4.5.88 | 4.5.88 |
| celery | >=5.6.3 | 5.6.3 (kombu 5.6.2) |
| redis | >=8.1.0 | 8.1.0 |
| sqlalchemy[asyncio] | >=2.1.5 | 2.1.5 |
| asyncpg | >=0.32.0 | 0.32.0 |
| alembic | >=1.20.0 | 1.20.0 |
| pydantic / pydantic-settings | >=2.14.1 / >=2.16.0 | 2.14.1 / 2.16.0 |
| httpx | >=0.28.1 | 0.28.1 |
| structlog | >=26.1.0 | 26.1.0 |
| protobuf | ==5.29.5 (exact pin, no comment explaining why in pyproject) | 5.29.5 |
Transitive of note: aiohttp 3.14.5, cryptography 50.0.2.

## Dev tooling
ruff 0.17.1 (rules E,W,F,I,B,UP,N,S,ASYNC,RUF,ANN,SIM,PT,C4,DTZ,T20,RET,PIE,TID,PERF; line 100), mypy 2.4.0 (strict, pydantic plugin), pytest 9.1.1 + pytest-asyncio 1.4.0 (auto mode) + pytest-cov 7.1.0, fakeredis 2.40.0, celery-types, pre-commit 4.7.0 (hooks repo pre-commit-hooks v5.0.0 + local hooks), pyyaml.

## Infra
Postgres 17-alpine, Redis 7-alpine (compose); one image with roles scanner / worker-alerts / worker-maintenance / beat / migrator. Dockerfile runs as non-root.

## Observations
- Not in stack despite CLAUDE.md: FastAPI/Chart.js (V3), aiogram (not needed yet). Telegram goes via httpx.
- `ccxt.pro` WebSocket: ccxt is a single package; actual use of WS not verified (see `scanner/streams.py`).
- Outdated/abandoned: not verified. Versions are very recent relative to the audit date (2026-10) and were not compared to PyPI (no network check performed). No obviously abandoned dependency in the list. `protobuf` exact pin and pre-commit-hooks v5.0.0 are the candidates to review.
- Lock hygiene: no vulnerability scan (pip-audit etc.) was run - not verified.
