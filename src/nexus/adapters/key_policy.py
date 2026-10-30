"""Key policy startup check (S-08 / A6, simplified in T9): never use a key that can trade,
withdraw or transfer.

There are no human attestation flags. The check is automatic: a key that fails it (or cannot be
verified) is *rejected*. In the default mode the scanner then runs that venue in public mode
without the key (the credential-less client is built by the composition root); with
``KEY_POLICY_STRICT=true`` (owner's own setup) a rejected key is fatal, and an unrestricted IP
binding or a property the API does not expose is a violation too.

Per core venue one signed GET reads the key's own permissions (the refuse rules live in the
parsers below). Every parser is a pure function from the
raw payload to a tuple of violated *rule names*; it fails closed (unparseable payload or a
missing/mistyped required field is a violation). The raw payload contains the api key, uid
and label: it is never logged, stored or put into an exception. Only rule names and booleans
leave this module.

Items marked [U] in the report (bybit ``ips`` shape, bybit ``readOnly`` vs ``permissions``,
okx ``ip`` wildcard) are isolated in the constants/helpers below so they are easy to adjust
after the U3 run on real read-only keys.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import structlog

from nexus.config.groups import ExchangeCredentials, KeyPolicySettings
from nexus.domain.errors import (
    ExchangeRateLimitError,
    ExchangeUnavailableError,
    KeyPolicyViolationError,
)

log = structlog.get_logger(__name__)

Parser = Callable[[Any], tuple[str, ...]]

UNPARSEABLE = "unparseable_response"
IP_UNBOUND = "ip_not_restricted"
NO_POLICY = "no_key_policy_for_venue"
REQUEST_FAILED = "request_failed"
KEY_INFO_ATTEMPTS = 3
"""Tries for the key-introspection call on transient errors (network, timeout, rate limit)."""
KEY_INFO_BACKOFF_S = 1.0
UNVERIFIABLE_KUCOIN_IP = "unverifiable:ip_binding"
UNVERIFIABLE_GATEIO_PERMS = "unverifiable:permissions_read_only"
#: Pre-T9 attestation variables; ignored (a deprecation notice is shown).
DEPRECATED_ENV_VARS = (
    "KEY_POLICY_KUCOIN_IP_ATTESTED",
    "KEY_POLICY_GATEIO_PERMISSIONS_ATTESTED",
    "KEY_POLICY_IP_BINDING_WAIVED",
)

_WILDCARD_IPS = frozenset({"*", "0.0.0.0", "0.0.0.0/0", "::/0"})  # noqa: S104 - data, not a bind
#: A CIDR this wide (/0../8) is not an IP binding in practice (treated as unbound).
_MAX_WILDCARD_PREFIX = 8
_SAFE_NAME = re.compile(r"[A-Za-z0-9_]{1,40}")


def _scope_rule(name: str) -> str:
    """Rule name for a scope taken from a response: only a short safe charset is echoed."""
    return f"permission:{name}" if _SAFE_NAME.fullmatch(name) else "permission:unexpected_scope"


def _is_wildcard_ip(ip: str) -> bool:
    if ip in _WILDCARD_IPS:
        return True
    try:
        return ipaddress.ip_network(ip, strict=False).prefixlen <= _MAX_WILDCARD_PREFIX
    except ValueError:
        return False


#: binance: flags that must be present and ``false`` (any of them grants more than reading).
BINANCE_FORBIDDEN = (
    "enableWithdrawals",
    "enableInternalTransfer",
    "permitsUniversalTransfer",
    "enableSpotAndMarginTrading",
    "enableMargin",
    "enableFutures",
    "enableVanillaOptions",
    "enablePortfolioMarginTrading",
    "enableFixApiTrade",
)
BYBIT_FORBIDDEN_WALLET = ("Withdraw", "AccountTransfer")
BYBIT_FORBIDDEN_WALLET_PREFIX = "SubMemberTransfer"
#: binance: the only ``enable*`` / ``permits*`` flags that may be true (allow-list).
BINANCE_ALLOWED_TRUE = frozenset({"enableReading", "enableFixReadOnly"})
_BINANCE_FLAG_PREFIXES = ("enable", "permits")
OKX_ALLOWED_PERMS = frozenset({"read_only"})
KUCOIN_ALLOWED_PERMS = frozenset({"General"})


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _flag(payload: Mapping[str, Any], field: str) -> bool | None:
    value = payload.get(field)
    return value if isinstance(value, bool) else None


def _missing(field: str) -> str:
    return f"missing_or_invalid_field:{field}"


def _ips(value: Any) -> list[str] | None:
    """Normalise an IP list (array or comma/space separated string); ``None`` if unusable."""
    if isinstance(value, str):
        return [ip for ip in value.replace(",", " ").split() if ip]
    if isinstance(value, list | tuple) and all(isinstance(ip, str) for ip in value):
        return [ip.strip() for ip in value if ip.strip()]
    return None


def _ip_rules(value: Any, field: str) -> tuple[str, ...]:
    ips = _ips(value)
    if ips is None:
        return (_missing(field),)
    if not ips or any(_is_wildcard_ip(ip) for ip in ips):
        return (IP_UNBOUND,)
    return ()


def parse_binance(payload: Any) -> tuple[str, ...]:
    """``GET /sapi/v1/account/apiRestrictions`` (flat object of booleans)."""
    body = _mapping(payload)
    if body is None:
        return (UNPARSEABLE,)
    rules: list[str] = []
    for field in BINANCE_FORBIDDEN:
        flag = _flag(body, field)
        if flag is None:
            rules.append(_missing(field))
        elif flag:
            rules.append(f"permission:{field}")
    # Allow-list: a flag the venue adds later is refused unless it is explicitly read-only.
    known = set(BINANCE_FORBIDDEN) | BINANCE_ALLOWED_TRUE
    extra = sorted(
        key
        for key, value in body.items()
        if key.startswith(_BINANCE_FLAG_PREFIXES) and key not in known and value is not False
    )
    rules.extend(_scope_rule(key) for key in extra)
    reading = _flag(body, "enableReading")
    if reading is None:
        rules.append(_missing("enableReading"))
    elif not reading:
        rules.append("permission:reading_disabled")
    restricted = _flag(body, "ipRestrict")
    if restricted is None:
        rules.append(_missing("ipRestrict"))
    elif not restricted:
        rules.append(IP_UNBOUND)
    return tuple(rules)


def parse_bybit(payload: Any) -> tuple[str, ...]:
    """``GET /v5/user/query-api`` (``{retCode, result: {...}}``)."""
    envelope = _mapping(payload)
    if envelope is None or envelope.get("retCode") != 0:
        return (UNPARSEABLE,)
    body = _mapping(envelope.get("result"))
    if body is None:
        return (UNPARSEABLE,)
    rules: list[str] = []
    read_only = body.get("readOnly")
    if isinstance(read_only, bool) or read_only not in (0, 1):
        rules.append(_missing("readOnly"))
    elif read_only != 1:  # authoritative flag; the group lists are scopes (report [U])
        rules.append("permission:not_read_only")
    permissions = _mapping(body.get("permissions"))
    if permissions is None:
        rules.append(_missing("permissions"))
    else:
        wallet = permissions.get("Wallet", [])
        if not isinstance(wallet, list) or not all(isinstance(item, str) for item in wallet):
            rules.append(_missing("permissions.Wallet"))
        else:
            for item in wallet:
                if item in BYBIT_FORBIDDEN_WALLET:
                    rules.append(f"permission:Wallet.{item}")
                elif item.startswith(BYBIT_FORBIDDEN_WALLET_PREFIX):
                    rules.append(f"permission:Wallet.{BYBIT_FORBIDDEN_WALLET_PREFIX}")
    rules.extend(_ip_rules(body.get("ips"), "ips"))
    return tuple(rules)


def parse_okx(payload: Any) -> tuple[str, ...]:
    """``GET /api/v5/account/config`` (``{code, data: [{...}]}``)."""
    envelope = _mapping(payload)
    if envelope is None or str(envelope.get("code")) != "0":
        return (UNPARSEABLE,)
    data = envelope.get("data")
    body = _mapping(data[0]) if isinstance(data, list) and len(data) == 1 else None
    if body is None:
        return (UNPARSEABLE,)
    rules: list[str] = []
    perm = body.get("perm")
    if not isinstance(perm, str) or not perm.strip():
        rules.append(_missing("perm"))
    else:
        scopes = {item.strip() for item in perm.split(",") if item.strip()}
        rules.extend(_scope_rule(name) for name in sorted(scopes - OKX_ALLOWED_PERMS))
        if "read_only" not in scopes:
            rules.append("permission:read_only_absent")
    ip = body.get("ip")
    if not isinstance(ip, str):
        rules.append(_missing("ip"))
    else:
        rules.extend(_ip_rules(ip, "ip"))
    return tuple(rules)


def parse_kucoin(payload: Any) -> tuple[str, ...]:
    """``GET /api/v1/user/api-key`` (``{code, data: {...}}``); the IP whitelist is not exposed."""
    envelope = _mapping(payload)
    if envelope is None or str(envelope.get("code")) != "200000":
        return (UNPARSEABLE,)
    body = _mapping(envelope.get("data"))
    if body is None:
        return (UNPARSEABLE,)
    permission = body.get("permission")
    if not isinstance(permission, str):
        return (_missing("permission"),)
    scopes = {item.strip() for item in permission.split(",") if item.strip()}
    if not scopes:
        return (_missing("permission"),)
    return tuple(_scope_rule(name) for name in sorted(scopes - KUCOIN_ALLOWED_PERMS))


def parse_gateio(payload: Any) -> tuple[str, ...]:
    """``GET /account/detail`` (flat object); permission scopes are not exposed."""
    body = _mapping(payload)
    if body is None:
        return (UNPARSEABLE,)
    return _ip_rules(body.get("ip_whitelist"), "ip_whitelist")


def deprecated_env_vars(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Names (never values) of removed ``KEY_POLICY_*`` attestation variables that are set."""
    return tuple(name for name in DEPRECATED_ENV_VARS if environ.get(name, "").strip())


@dataclass(frozen=True, slots=True)
class KeyAssessment:
    """Result for one key: ``violations`` reject it, ``warnings`` do not. Rule names only."""

    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        """True when the key may be used (read-only as far as the API can tell)."""
        return not self.violations


@dataclass(frozen=True, slots=True)
class KeyPolicyCheck:
    """Policy of one venue: how to parse its introspection payload.

    ``unverifiable`` names a property the venue API does not expose (a warning, or a violation
    in strict mode).
    """

    venue: str
    parse: Parser
    unverifiable: str | None = None

    def assess(self, payload: Any, settings: KeyPolicySettings) -> KeyAssessment:
        """Judge ``payload``. Never raises.

        Strict: every rule (including IP binding and unverifiable properties) is a violation.
        Default: IP binding and unverifiable properties are warnings; permissions stay fatal.
        """
        try:
            rules = list(self.parse(payload))
        except Exception as exc:
            # Fail closed, but not silently; class name only (the payload is sensitive).
            log.warning(
                "key_policy_parser_error",
                exchange=self.venue,
                rule=UNPARSEABLE,
                error=type(exc).__name__,
            )
            rules = [UNPARSEABLE]
        if self.unverifiable is not None:
            rules.append(self.unverifiable)
        if settings.strict:
            return KeyAssessment(violations=tuple(rules))
        soft = {IP_UNBOUND, UNVERIFIABLE_KUCOIN_IP, UNVERIFIABLE_GATEIO_PERMS}
        return KeyAssessment(
            violations=tuple(r for r in rules if r not in soft),
            warnings=tuple(r for r in rules if r in soft),
        )


KEY_POLICIES: dict[str, KeyPolicyCheck] = {
    "binance": KeyPolicyCheck("binance", parse_binance),
    "bybit": KeyPolicyCheck("bybit", parse_bybit),
    "okx": KeyPolicyCheck("okx", parse_okx),
    "kucoin": KeyPolicyCheck("kucoin", parse_kucoin, UNVERIFIABLE_KUCOIN_IP),
    "gateio": KeyPolicyCheck("gateio", parse_gateio, UNVERIFIABLE_GATEIO_PERMS),
}


@dataclass(frozen=True, slots=True)
class KeyPolicyReport:
    """Outcome for all venues: rejected keys (must not be used) and warnings (usable keys)."""

    rejected: Mapping[str, tuple[str, ...]]
    warnings: Mapping[str, tuple[str, ...]]

    @property
    def rejected_venues(self) -> tuple[str, ...]:
        """Venues that must run without their key, sorted."""
        return tuple(sorted(self.rejected))


async def _read_with_retry(venue: str, read_key_info: Callable[[], Awaitable[Any]]) -> Any:
    """Call the key-introspection endpoint; retry transient errors with a short backoff.

    A network blip at startup must not demote a venue to public mode for the whole run.
    Auth and other permanent errors are not retried.
    """
    for attempt in range(1, KEY_INFO_ATTEMPTS + 1):
        try:
            return await read_key_info()
        except (ExchangeUnavailableError, ExchangeRateLimitError, TimeoutError) as exc:
            if attempt >= KEY_INFO_ATTEMPTS:
                raise
            log.info("key_policy_retry", exchange=venue, attempt=attempt, error=type(exc).__name__)
            await asyncio.sleep(KEY_INFO_BACKOFF_S * attempt)
    raise AssertionError  # pragma: no cover - the loop always returns or raises


async def assess_venue_key(
    venue: str,
    adapter: object,
    credentials: ExchangeCredentials | None,
    settings: KeyPolicySettings,
) -> KeyAssessment | None:
    """The single policy decision shared by ``nexus check`` and the scanner.

    ``None`` = no key configured (public mode). Never raises. Only rule names leave here.
    """
    if credentials is None or not credentials.is_configured:
        log.info("key_policy_skipped", exchange=venue, reason="no_key_public_mode")
        return None
    policy = KEY_POLICIES.get(venue)
    read_key_info = getattr(adapter, "fetch_key_info", None)
    if policy is None or read_key_info is None:
        return KeyAssessment(violations=(NO_POLICY,))
    try:
        payload = await _read_with_retry(venue, read_key_info)
    except Exception as exc:
        # Any failure (exchange, read-only guard, configuration, ...) rejects this key. Only the
        # class name is logged: messages of auth errors may embed request details.
        log.warning("key_policy_request_failed", exchange=venue, error=type(exc).__name__)
        return KeyAssessment(violations=(REQUEST_FAILED,))
    assessment = policy.assess(payload, settings)
    del payload  # raw response holds apiKey / uid / label
    log.info(
        "key_policy_checked",
        exchange=venue,
        passed=assessment.accepted,
        violations=list(assessment.violations),
        warnings=list(assessment.warnings),
    )
    return assessment


async def verify_key_policies(
    adapters: Mapping[str, object],
    credentials: Mapping[str, ExchangeCredentials],
    settings: KeyPolicySettings,
) -> KeyPolicyReport:
    """Check every venue that has a key configured.

    Venues without a key (public data mode) are skipped. All venues are evaluated so one run
    reports every problem. A configured key on a venue without a policy is rejected (fail
    closed). In strict mode any rejection raises :class:`KeyPolicyViolationError`; otherwise
    the caller must run the rejected venues without their key (see ``container``).
    """
    rejected: dict[str, tuple[str, ...]] = {}
    warnings: dict[str, tuple[str, ...]] = {}
    for venue, adapter in adapters.items():
        assessment = await assess_venue_key(venue, adapter, credentials.get(venue), settings)
        if assessment is None:
            continue
        if not assessment.accepted:
            rejected[venue] = assessment.violations
        elif assessment.warnings:
            warnings[venue] = assessment.warnings
    if rejected and settings.strict:
        raise KeyPolicyViolationError(rejected)
    if rejected:
        # Names only: no key material, no IPs.
        log.warning("key_policy_public_fallback", venues=sorted(rejected), rules=rejected)
    if warnings:
        log.warning("key_policy_warnings", rules=warnings)
    return KeyPolicyReport(rejected=rejected, warnings=warnings)
