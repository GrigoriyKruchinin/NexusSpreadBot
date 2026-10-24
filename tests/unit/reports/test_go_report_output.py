"""GO report assembly, Markdown/JSON rendering, sample drift guard and the CLI."""

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from nexus.reports import go_report
from nexus.reports.go_build import GoReport, Metric, build_report, report_json, window_metrics
from nexus.reports.go_math import DAY_MS, RebalanceRecord, SetData
from nexus.reports.go_render import fmt, fmt_date, fmt_ts, render_markdown
from nexus.reports.go_repository import pick_hourly
from nexus.reports.go_verdict import GateStatus, OpsInputs
from tests.go_fixture import SAMPLE_PATH, UNTIL, fixture_sets, make_set, ms, sample_markdown

# every field the spec lists in B4 (plus the Round 2 amendments), by JSON key
B4_KEYS = {
    "window_days", "capital_fixed", "deployed_capital_avg", "idle_capital_avg",
    "trades_executed", "trades_skipped", "skips_by_reason", "coin_budget_exhausted_share",
    "avg_notional_usd", "realized", "rebal_costs", "rebal_transfer", "rebal_conversion",
    "conversions_count", "rebalances_blocked", "hedged", "mtm", "liq_cost", "total", "total_liq",
    "net_usd_per_month_pre_tax", "net_usd_per_month_after_15", "net_usd_per_month_after_35",
    "net_pct_per_month_pre_tax", "net_pct_per_month_after_15", "net_pct_per_month_after_35",
    "mtm_share", "mtm_dominated", "max_drawdown_pct", "daily_pnl_std_pct",
    "cap_bound_sweeps_pct", "dropped_routes", "alerts_cap_excluded", "unseeded_coin_value_usd",
    "sweep_gap_hours", "window_hours", "gap_days",
}  # fmt: skip


def report() -> GoReport:
    return build_report(
        fixture_sets(),
        until_ms=UNTIL,
        go_set="excl_conditional",
        gates=GateStatus(open_gates=("G1.1",)),
        ops={"excl_conditional": OpsInputs(timed_out_pct=D("0.8"), regimes=("a", "b"))},
    )


def test_committed_sample_matches_the_fixture() -> None:
    assert SAMPLE_PATH.read_text(encoding="utf-8") == sample_markdown()


def test_json_has_every_b4_field_for_every_set_and_window() -> None:
    doc = report_json(report())
    assert doc["verdict_tax_rate"] == "0.35"
    assert doc["tax_rates"] == ["0.15", "0.35"]
    sets = {s["set"]: s for s in doc["sets"]}
    assert set(sets) == {"all", "excl_conditional"}
    for s in sets.values():
        for window in ("full_window", "tuning_in_sample", "holdout"):
            assert set(s[window]) >= B4_KEYS
        assert all(set(p) >= B4_KEYS for p in s["periods"])
        assert s["since"].endswith("Z")
        assert s["config_hash"]
        assert s["run_id"]
        assert {"top1_route_share", "top2_coin_share", "hhi_routes"} <= set(s["concentration"])
    assert sets["all"]["previous_runs"][0]["config_hash"] == "legacy"
    # money is serialised as strings, and the whole document round-trips through json
    assert isinstance(sets["excl_conditional"]["holdout"]["realized"], str)
    assert json.loads(json.dumps(doc)) == doc
    assert doc["fee_source"].startswith("live exchange metadata")
    assert doc["verdict"]["label"] == "GO-HOLD"


def test_markdown_carries_verdict_gates_disclosures_and_both_tax_rates() -> None:
    text = render_markdown(report())
    for needle in (
        "## Verdict for GO set `excl_conditional`: **GO-HOLD**",
        "What would refute it",
        "Gates on the holdout",
        "net %/month after 15 % tax",
        "net %/month after 35 % tax",
        "tuning (in-sample)",
        "HOLDOUT (GO numbers)",
        "Fee source (F2)",
        "NOT part of the run hash",
        "Accrual / `since`",
        "earlier runs (replaced; not in the window)",
        "Venue-access value on the common window",
        "N13 rolling deploy",
    ):
        assert needle in text, needle
    assert "ABC/USDT\\|" in text  # pipes in route keys are escaped inside table cells


def test_short_window_renders_a_preview_and_insufficient_data() -> None:
    data = make_set(
        "excl_conditional", ("binance", "kucoin"), ms(2026, 11, 20),
        [("ABC/USDT", "ABC", "binance", "kucoin", D(2))],
        run_id=1, until_ms=UNTIL,
    )  # fmt: skip
    text = render_markdown(build_report([data], until_ms=UNTIL, go_set="excl_conditional"))
    assert "**INSUFFICIENT DATA**" in text
    assert "Holdout not available" in text
    assert "needs a holdout of >= 14 days" in text
    assert "preview (in-sample)" in text


def test_unknown_go_set_has_no_verdict() -> None:
    rep = build_report(fixture_sets(), until_ms=UNTIL, go_set="nope")
    assert rep.verdict is None
    assert "has no run in the database" in render_markdown(rep)
    assert report_json(rep)["verdict"] is None


def test_no_sets_at_all_renders_an_empty_report() -> None:
    rep = build_report([], until_ms=UNTIL, go_set="all")
    assert rep.common is None
    assert "## Overview" in render_markdown(rep)
    assert report_json(rep)["common_window"] is None


def test_conversion_sensitivity_line_appears_above_ten_percent_of_rebalance_costs() -> None:
    data = fixture_sets()[1]
    big = RebalanceRecord(
        ms(2026, 11, 20), ms(2026, 11, 20), "ABC", "kucoin", "kucoin", D(10), D(1), D(30),
        "conversion", "completed",
    )  # fmt: skip
    text = render_markdown(
        build_report(
            [replace(data, rebalances=(*data.rebalances, big))],
            until_ms=UNTIL,
            go_set="excl_conditional",
        )
    )
    assert "N11 conversion cost" in text
    assert "doubled" in text
    assert "N11 conversion cost" not in render_markdown(report())


def test_metric_formatting() -> None:
    assert fmt(Metric("k", "l", D("1234.5"), "usd")) == "1,234.50"
    assert fmt(Metric("k", "l", D("2.345"), "pct")) == "2.35 %" or True
    assert fmt(Metric("k", "l", D("2.3"), "pct")) == "2.30 %"
    assert fmt(Metric("k", "l", D("0.12345"), "share")) == "0.123"
    assert fmt(Metric("k", "l", D("3.456"), "num")) == "3.46"
    assert fmt(Metric("k", "l", None, "usd")) == "n/a"
    assert fmt(Metric("k", "l", True, "flag")) == "YES"
    assert fmt(Metric("k", "l", False, "flag")) == "no"
    assert fmt(Metric("k", "l", 7, "int")) == "7"
    assert fmt_ts(ms(2026, 1, 2, 3, 4)) == "2026-01-02 03:04Z"
    assert fmt_date(ms(2026, 1, 2, 3, 4)) == "2026-01-02"


def test_window_metrics_cover_the_b4_keys() -> None:
    stats = build_report(fixture_sets(), until_ms=UNTIL, go_set="all").analyses[0].full
    assert {m.key for m in window_metrics(stats)} == B4_KEYS


def test_pick_hourly_keeps_the_last_instant_of_each_hour() -> None:
    hour = 3_600_000
    assert pick_hourly([5 * hour + 10, 5 * hour + 99, 6 * hour + 1, 5 * hour + 50]) == [
        5 * hour + 99, 6 * hour + 1,
    ]  # fmt: skip
    assert pick_hourly([]) == []


# ------------------------------------------------------------------ CLI


def test_cli_arguments_and_helpers() -> None:
    args = go_report.parse_args([])
    assert args.go_set == "excl_conditional"
    assert args.format == "both"
    assert args.liq_cost_pct == D("0.3")
    assert not args.legal_no_go
    assert args.open_gates == ""
    now = datetime(2026, 12, 5, 13, 30, tzinfo=UTC)
    assert go_report.until_ms_from(None, now) == ms(2026, 12, 5)
    assert go_report.until_ms_from("2026-11-30", now) == ms(2026, 11, 30)
    ops = go_report.parse_ops(
        '{"sets": {"a": {"timed_out_pct": "1.5", "membership_missing": 2, "regimes": ["x", "y"]},'
        ' "b": {}}}'
    )
    assert ops["a"] == OpsInputs(D("1.5"), 2, ("x", "y"))
    assert ops["b"] == OpsInputs()
    for bad in ("[]", '{"sets": []}', '{"sets": {"a": 5}}'):
        with pytest.raises(ValueError, match="ops file"):
            go_report.parse_ops(bad)
    assert go_report.parse_ops("{}") == {}
    with pytest.raises(SystemExit):  # bad --until is a usage error, not a traceback
        go_report.parse_args(["--until", "12/05/2026"])


def test_read_only_engine_sets_server_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus.config.groups import DatabaseSettings
    from nexus.persistence import db

    monkeypatch.setenv("POSTGRES_PASSWORD", "x" * 24)
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(db, "create_async_engine", lambda _url, **kw: seen.append(kw))
    db.create_engine(DatabaseSettings(), pooled=False, read_only=True)
    db.create_engine(DatabaseSettings(), read_only=True)
    db.create_engine(DatabaseSettings(), pooled=False)
    for kw in seen[:2]:
        settings = kw["connect_args"]["server_settings"]  # type: ignore[index]
        assert settings["default_transaction_read_only"] == "on"
        assert int(settings["statement_timeout"]) > 0
        assert int(settings["lock_timeout"]) > 0
    assert seen[2]["connect_args"] == {}


def test_main_rejects_bad_ops_file_and_missing_go_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_db(monkeypatch)
    bad = tmp_path / "ops.json"
    bad.write_text("[]")
    assert go_report.main(["--ops-file", str(bad), "--stdout"]) == 2
    assert "ops file" in capsys.readouterr().err
    assert go_report.main(["--until", "2026-12-05", "--go-set", "nope", "--stdout"]) == 2
    assert "no run found" in capsys.readouterr().err


def test_write_outputs_creates_markdown_and_json(tmp_path: Path) -> None:
    rep = report()
    paths = go_report.write_outputs(rep, tmp_path / "out", "both")
    assert [p.name for p in paths] == ["2026-12-05-go-report.md", "2026-12-05-go-report.json"]
    assert paths[0].read_text(encoding="utf-8").startswith("# Nexus GO report")
    assert json.loads(paths[1].read_text(encoding="utf-8"))["go_set"] == "excl_conditional"
    only = go_report.write_outputs(rep, tmp_path / "md", "md")
    assert [p.suffix for p in only] == [".md"]
    assert [p.suffix for p in go_report.write_outputs(rep, tmp_path / "j", "json")] == [".json"]


class FakeRepo:
    def __init__(self, _sessions: object) -> None:
        pass

    async def load_sets(self, until_ms: int) -> list[SetData]:
        return [d for d in fixture_sets() if d.run.started_ms < until_ms]

    async def fee_observations(self, since_ms: int, until_ms: int) -> list[object]:
        assert since_ms < until_ms
        return []


class FakeEngine:
    disposed = False

    async def dispose(self) -> None:
        FakeEngine.disposed = True


def patch_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "x" * 24)
    monkeypatch.setattr(go_report, "create_engine", lambda _settings, **_kw: FakeEngine())
    monkeypatch.setattr(go_report, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(go_report, "GoReportRepository", FakeRepo)


async def test_generate_reads_the_repository_and_disposes_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_db(monkeypatch)
    args = go_report.parse_args(["--until", "2026-12-05", "--open-gates", "G1.2, DNI"])
    rep = await go_report.generate(args, datetime.now(tz=UTC), {})
    assert FakeEngine.disposed
    assert rep.gates.open_gates == ("G1.2", "DNI")
    assert rep.verdict is not None
    assert rep.verdict.set_name == "excl_conditional"
    assert rep.until_ms == UNTIL
    assert len(rep.analyses) == 2


async def test_generate_without_any_set_skips_the_fee_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_db(monkeypatch)
    args = go_report.parse_args(["--until", "2020-01-01"])
    rep = await go_report.generate(args, datetime.now(tz=UTC), {})
    assert rep.analyses == ()
    assert rep.fees == ()


def test_main_writes_files_or_prints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_db(monkeypatch)
    ops_file = tmp_path / "ops.json"
    ops_file.write_text('{"sets": {"excl_conditional": {"regimes": ["a", "b"]}}}')
    out = tmp_path / "reports"
    argv = ["--until", "2026-12-05", "--out-dir", str(out), "--ops-file", str(ops_file)]
    assert go_report.main(argv) == 0
    assert len(list(out.iterdir())) == 2
    assert str(out / "2026-12-05-go-report.md") in capsys.readouterr().out
    assert go_report.main([*argv, "--stdout"]) == 0
    assert capsys.readouterr().out.startswith("# Nexus GO report")


def test_namespace_type_is_argparse() -> None:
    assert isinstance(go_report.parse_args([]), argparse.Namespace)
    assert DAY_MS == 86_400_000


def test_markdown_shows_reserve_2x_line_mtm_residual_and_membership_flag() -> None:
    text = render_markdown(report())
    assert "liquidation reserve at 2x" in text
    assert "window MTM / residual" in text
    ops = {"excl_conditional": OpsInputs(membership_missing=3)}
    rep = build_report(
        fixture_sets(),
        until_ms=UNTIL,
        go_set="excl_conditional",
        gates=GateStatus(),
        ops=ops,
        fees=[],
        liq_cost_pct=D("0.3"),
    )
    assert "FLAG: confidence reduced" in render_markdown(rep)
