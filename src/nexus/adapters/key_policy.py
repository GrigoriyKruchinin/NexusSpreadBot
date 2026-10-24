"""Key policy startup check (S-08 / A6): refuse keys that can trade, withdraw or transfer.

Per core venue one signed GET reads the key's own permissions (endpoints and refuse rules:
``docs/reports/exchange-key-permissions.md``). Every parser is a pure function from the
raw payload to a tuple of violated *rule names*; it fails closed (unparseable payload or a
missing/mistyped required field is a violation). The raw payload contains the api key, uid
and label: it is never logged, stored or put into an exception. Only rule names and booleans
leave this module.

Items marked [U] in the report (bybit ``ips`` shape, bybit ``readOnly`` vs ``permissions``,
okx ``ip`` wildcard) are isolated in the constants/helpers below so they are easy to adjust
after the U3 run on real read-only keys.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import structlog

from nexus.config.groups import ExchangeCredentials, KeyPolicySettings
from nexus.domain.errors import KeyPolicyViolationError

log = structlog.get_logger(__name__)

Parser = Callable[[Any], tuple[str, ...]]

UNPARSEABLE = "unparseable_response"
IP_UNBOUND = "ip_not_restricted"
NO_POLICY = "no_key_policy_for_venue"
REQUEST_FAILED = "request_failed"
ATTEST_KUCOIN_IP = "attestation_required:ip_binding"
ATTEST_GATEIO_PERMS = "attestation_required:permissions_read_only"

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
    """``GET /api/v1/user/api-key`` (``{code, data: {...}}``); IP binding is attested."""
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
    """``GET /account/detail`` (flat object); permission scopes are attested."""
    body = _mapping(payload)
    if body is None:
        return (UNPARSEABLE,)
    return _ip_rules(body.get("ip_whitelist"), "ip_whitelist")


@dataclass(frozen=True, slots=True)
class KeyPolicyCheck:
    """Policy of one venue: how to parse its introspection payload and what is attested."""

    venue: str
    parse: Parser
    attestation: Callable[[KeyPolicySettings], tuple[bool, str]] | None = None

    def evaluate(self, payload: Any, settings: KeyPolicySettings) -> tuple[str, ...]:
        """Rule names violated by ``payload`` (empty = key passes). Never raises."""
        return self.evaluate_waiver(payload, settings)[0]

    def evaluate_waiver(
        self, payload: Any, settings: KeyPolicySettings
    ) -> tuple[tuple[str, ...], bool]:
        """``(violated rules, key is IP-unbound under the waiver)``. Never raises.

        With ``ip_binding_waived`` only ``ip_not_restricted`` and the KuCoin IP attestation
        are dropped; every other rule is kept.
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
        if self.attestation is not None:
            attested, rule = self.attestation(settings)
            if not attested:
                rules.append(rule)
        if not settings.ip_binding_waived:
            return tuple(rules), False
        waived = {IP_UNBOUND, ATTEST_KUCOIN_IP}
        return tuple(r for r in rules if r not in waived), any(r in waived for r in rules)


KEY_POLICIES: dict[str, KeyPolicyCheck] = {
    "binance": KeyPolicyCheck("binance", parse_binance),
    "bybit": KeyPolicyCheck("bybit", parse_bybit),
    "okx": KeyPolicyCheck("okx", parse_okx),
    "kucoin": KeyPolicyCheck(
        "kucoin", parse_kucoin, lambda s: (s.kucoin_ip_attested, ATTEST_KUCOIN_IP)
    ),
    "gateio": KeyPolicyCheck(
        "gateio", parse_gateio, lambda s: (s.gateio_permissions_attested, ATTEST_GATEIO_PERMS)
    ),
}


async def verify_key_policies(
    adapters: Mapping[str, object],
    credentials: Mapping[str, ExchangeCredentials],
    settings: KeyPolicySettings,
) -> tuple[str, ...]:
    """Check every venue that has a key configured; raise on any violation.

    Returns the venues whose keys are IP-unbound under the explicit local-run waiver
    (``KEY_POLICY_IP_BINDING_WAIVED``), sorted; empty without the waiver.

    Venues without a key (public data mode) are skipped. All venues are evaluated before
    raising so one run reports every problem. A configured key on a venue without a policy
    is refused (fail closed).
    """
    violations: dict[str, tuple[str, ...]] = {}
    unbound: list[str] = []
    for venue, adapter in adapters.items():
        creds = credentials.get(venue)
        if creds is None or not creds.is_configured:
            log.info("key_policy_skipped", exchange=venue, reason="no_key_public_mode")
            continue
        policy = KEY_POLICIES.get(venue)
        read_key_info = getattr(adapter, "fetch_key_info", None)
        if policy is None or read_key_info is None:
            violations[venue] = (NO_POLICY,)
            continue
        try:
            payload = await read_key_info()
        except Exception as exc:
            # Any failure (exchange, read-only guard, configuration, ...) refuses this venue
            # and the other venues are still checked. Only the class name is logged: messages
            # of auth errors may embed request details.
            log.warning("key_policy_request_failed", exchange=venue, error=type(exc).__name__)
            violations[venue] = (REQUEST_FAILED,)
            continue
        rules, ip_unbound = policy.evaluate_waiver(payload, settings)
        del payload  # raw response holds apiKey / uid / label
        log.info("key_policy_checked", exchange=venue, passed=not rules, violations=list(rules))
        if rules:
            violations[venue] = rules
        elif ip_unbound:
            unbound.append(venue)
    if violations:
        raise KeyPolicyViolationError(violations)
    result = tuple(sorted(unbound))
    if result:
        # Names only: no key material, no IPs.
        log.warning("key_policy_ip_binding_waived", venues=list(result))
    return result
