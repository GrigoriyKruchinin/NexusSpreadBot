"""Command-line entry points (``nexus <command>``)."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

import structlog

from nexus.config.groups import LoggingSettings, RedisSettings, ScannerSettings
from nexus.config.provenance import log_settings_provenance
from nexus.config.roles import ScannerRoleSettings
from nexus.domain.clock import SystemClock
from nexus.domain.errors import KeyPolicyViolationError
from nexus.log import configure_logging

log = structlog.get_logger(__name__)

EXIT_KEY_POLICY = 3
"""Exit code when an exchange key violates the key policy (no restart can fix it)."""


async def _run_scanner() -> None:
    from nexus.container import scanner_scope

    settings = ScannerRoleSettings.load()
    configure_logging(settings.logging, service="scanner")
    log_settings_provenance("scanner")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info(
        "scanner_starting",
        exchanges=list(settings.exchanges.enabled),
        conditional_venues=list(settings.conditional.venues),
        require_verified_transfer=settings.spread.require_verified_transfer,
    )
    async with scanner_scope(settings) as scanner:
        await scanner.run(stop)
    log.info("scanner_stopped")


async def _scanner_healthy() -> bool:
    """True if the scanner heartbeat is fresh (used by the Docker healthcheck)."""
    from nexus.container import redis_client
    from nexus.infra.redis_store import RedisHeartbeat
    from nexus.scanner.service import HEARTBEAT_SERVICE

    redis_settings = RedisSettings()
    ttl_s = ScannerSettings().heartbeat_ttl_s
    clock = SystemClock()
    redis = redis_client(redis_settings.url.get_secret_value(), redis_settings.socket_timeout_s)
    try:
        last = await RedisHeartbeat(redis, clock).last_beat_ms(HEARTBEAT_SERVICE)
    finally:
        await redis.aclose()
    return last is not None and clock.now_ms() - last <= ttl_s * 1000


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="nexus", description="Nexus Spread Scanner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scanner", help="run the spread scanner")
    health = sub.add_parser("healthcheck", help="container healthchecks")
    health.add_argument("target", choices=["scanner"])
    args = parser.parse_args(argv)

    if args.command == "scanner":
        try:
            asyncio.run(_run_scanner())
        except KeyPolicyViolationError as exc:
            # Rule names only (no response bodies, keys or uids).
            log.critical("key_policy_violation", violations=exc.violations)
            return EXIT_KEY_POLICY
        return 0
    if args.command == "healthcheck":
        configure_logging(LoggingSettings(), service="healthcheck")
        try:
            healthy = asyncio.run(_scanner_healthy())
        except Exception as exc:
            log.warning("healthcheck_failed", error=type(exc).__name__)
            healthy = False
        return 0 if healthy else 1
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
