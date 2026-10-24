"""GO report CLI: ``python -m nexus.reports.go_report`` (read-only; see ``make go-report``).

Reads the paper portfolios of every venue set from PostgreSQL (``POSTGRES_*`` env, i.e. the app
role). The session is read-only by server setting (``default_transaction_read_only=on``, plus
statement and lock timeouts), so no write is possible even with the app role.
Writes ``<out>/<date>-go-report.md`` and ``.json``. Paper simulation only: no orders,
no transfers, no keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from nexus.config.groups import DatabaseSettings
from nexus.persistence.db import create_engine, create_session_factory
from nexus.reports.go_build import GoReport, build_report, report_json
from nexus.reports.go_math import DAY_MS, DEFAULT_LIQ_COST_PCT
from nexus.reports.go_render import fmt_date, render_markdown
from nexus.reports.go_repository import GoReportRepository, earliest_since_ms
from nexus.reports.go_verdict import GateStatus, OpsInputs

DEFAULT_GO_SET = "excl_conditional"
"""Conservative default: no Bybit/gateio (open gates G1.2, G1.5); change with ``--go-set``."""
DEFAULT_OUT_DIR = "docs/reports/go"


def parse_ops(text: str) -> dict[str, OpsInputs]:
    """Parse ``{"sets": {"<set>": {"timed_out_pct", "membership_missing", "regimes"}}}``."""
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("ops file: top level must be a JSON object")
    sets = raw.get("sets", {})
    if not isinstance(sets, dict):
        raise ValueError('ops file: "sets" must be an object of set name -> object')
    result: dict[str, OpsInputs] = {}
    for name, item in sets.items():
        if not isinstance(item, dict):
            raise ValueError(f"ops file: entry {name!r} must be an object")
        timed_out = item.get("timed_out_pct")
        missing = item.get("membership_missing")
        result[str(name)] = OpsInputs(
            timed_out_pct=Decimal(str(timed_out)) if timed_out is not None else None,
            membership_missing=int(missing) if missing is not None else None,
            regimes=tuple(str(r) for r in item.get("regimes", [])),
        )
    return result


def _date_arg(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value!r}") from exc
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(prog="nexus.reports.go_report", description=__doc__)
    parser.add_argument("--go-set", default=DEFAULT_GO_SET, help="set the verdict is for")
    parser.add_argument(
        "--until", type=_date_arg, help="last complete UTC day + 1 (YYYY-MM-DD); default today"
    )
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--format", choices=["md", "json", "both"], default="both")
    parser.add_argument("--stdout", action="store_true", help="print Markdown instead of files")
    parser.add_argument("--liq-cost-pct", type=Decimal, default=DEFAULT_LIQ_COST_PCT)
    parser.add_argument(
        "--open-gates",
        default="",
        help="comma-separated legal/access gates not cleared (empty = all cleared)",
    )
    parser.add_argument("--legal-no-go", action="store_true", help="lawyer: real legal penalties")
    parser.add_argument("--ops-file", help="JSON with timed_out_pct / membership_missing / regimes")
    return parser.parse_args(argv)


def until_ms_from(arg: str | None, now: datetime) -> int:
    """``--until`` as epoch ms; default = start of today (UTC), i.e. the last complete day."""
    day = datetime.strptime(arg, "%Y-%m-%d").replace(tzinfo=UTC) if arg else now
    return int(day.timestamp() * 1000) // DAY_MS * DAY_MS


async def generate(args: argparse.Namespace, now: datetime, ops: dict[str, OpsInputs]) -> GoReport:
    """Query the database and build the report model."""
    engine = create_engine(DatabaseSettings(), pooled=False, read_only=True)
    try:
        repo = GoReportRepository(create_session_factory(engine))
        until_ms = until_ms_from(args.until, now)
        datas = await repo.load_sets(until_ms)
        since = earliest_since_ms(datas)
        fees = await repo.fee_observations(since, until_ms) if since is not None else []
    finally:
        await engine.dispose()
    gates = GateStatus(
        open_gates=tuple(g.strip() for g in args.open_gates.split(",") if g.strip()),
        legal_no_go=args.legal_no_go,
    )
    return build_report(
        datas,
        until_ms=until_ms,
        go_set=args.go_set,
        gates=gates,
        ops=ops,
        fees=fees,
        liq_cost_pct=args.liq_cost_pct,
    )


def write_outputs(report: GoReport, out_dir: Path, fmt: str) -> list[Path]:
    """Write the Markdown and/or JSON files; returns the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{fmt_date(report.until_ms)}-go-report"
    written = []
    if fmt in ("md", "both"):
        path = out_dir / f"{stem}.md"
        path.write_text(render_markdown(report), encoding="utf-8")
        written.append(path)
    if fmt in ("json", "both"):
        path = out_dir / f"{stem}.json"
        path.write_text(json.dumps(report_json(report), indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(argv)
    try:
        ops = parse_ops(Path(args.ops_file).read_text(encoding="utf-8")) if args.ops_file else {}
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
        sys.stderr.write(f"error: --ops-file: {exc}\n")
        return 2
    report = asyncio.run(generate(args, datetime.now(tz=UTC), ops))
    if args.stdout:
        sys.stdout.write(render_markdown(report))
    else:
        for path in write_outputs(report, Path(args.out_dir), args.format):
            sys.stdout.write(f"{path}\n")
    if report.verdict is None:
        sys.stderr.write(f"error: no run found for --go-set {args.go_set!r}; no verdict\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
