from nexus.domain.digest import HOUR_MS, SetCoverage, compute_set_coverage

H0 = 1_800_000_000_000 // HOUR_MS * HOUR_MS  # an hour boundary
DAY = 24 * HOUR_MS
LAG = 600_000  # window ends 10 min after the last full hour: counters are flushed


def _full(start: int, hours: range, sweeps: int = 360) -> dict[int, int]:
    return {start + h * HOUR_MS: sweeps for h in hours}


def test_continuous_run_has_no_gap() -> None:
    since, until = H0, H0 + DAY + LAG
    counts = {"all": _full(H0, range(24))}
    (cov,) = compute_set_coverage(counts, {"all": H0 - 5 * DAY}, since, until, 60)
    assert cov == SetCoverage("all", 24, 0, 0)


def test_missing_hours_and_thin_hours_count_as_downtime() -> None:
    since, until = H0, H0 + DAY + LAG
    sweeps = _full(H0, range(24))
    del sweeps[H0 + 3 * HOUR_MS]  # dark hour
    sweeps[H0 + 4 * HOUR_MS] = 30  # half of the minimum
    (cov,) = compute_set_coverage({"all": sweeps}, {"all": H0 - DAY}, since, until, 60)
    assert (cov.hours_expected, cov.hours_gap, cov.downtime_min) == (24, 2, 60 + 55)


def test_partial_window_edges_are_skipped() -> None:
    since, until = H0 + 600_000, H0 + DAY + 600_000  # not on an hour boundary
    (cov,) = compute_set_coverage(
        {"all": _full(H0, range(25))}, {"all": H0 - DAY}, since, until, 60
    )
    assert cov.hours_expected == 23


def test_new_set_is_judged_only_after_its_first_hour() -> None:
    since, until = H0, H0 + DAY + LAG
    first_seen = H0 + 10 * HOUR_MS + 1_000  # appeared inside hour 10
    sweeps = _full(H0, range(10, 24))
    sweeps[H0 + 10 * HOUR_MS] = 3  # partial first hour: ignored
    (cov,) = compute_set_coverage({"s": sweeps}, {"s": first_seen}, since, until, 60)
    assert (cov.hours_expected, cov.hours_gap) == (13, 0)


def test_set_added_in_the_last_hour_has_no_complete_hour() -> None:
    since, until = H0, H0 + DAY + LAG
    (cov,) = compute_set_coverage({}, {"s": until - 1_000}, since, until, 60)
    assert (cov.hours_expected, cov.hours_gap, cov.downtime_min) == (0, 0, 0)


def test_all_first_then_alphabetical() -> None:
    first = {"excl_bybit": 0, "all": 0, "excl_conditional": 0}
    result = compute_set_coverage({}, first, H0, H0 + 2 * HOUR_MS, 60)
    assert [c.portfolio_id for c in result] == ["all", "excl_bybit", "excl_conditional"]


def test_partial_hour_outage_is_not_hidden() -> None:
    """45 min dark inside one hour (90 sweeps of 360): not a gap hour, but 45 min of downtime."""
    since, until = H0, H0 + DAY + LAG
    sweeps = _full(H0, range(24))
    sweeps[H0 + 5 * HOUR_MS] = 90
    (cov,) = compute_set_coverage({"all": sweeps}, {"all": H0 - DAY}, since, until, 60, 360)
    assert (cov.hours_gap, cov.downtime_min) == (0, 45)


def test_outage_split_across_an_hour_boundary() -> None:
    since, until = H0, H0 + DAY + LAG
    sweeps = _full(H0, range(24))
    sweeps[H0 + 5 * HOUR_MS] = 180  # 30 min dark at the end of hour 5
    sweeps[H0 + 6 * HOUR_MS] = 180  # 30 min dark at the start of hour 6
    (cov,) = compute_set_coverage({"all": sweeps}, {"all": H0 - DAY}, since, until, 60, 360)
    assert cov.downtime_min == 60


def test_slow_steady_scanner_is_not_blamed_for_the_nominal_rate() -> None:
    """Nominal 360/h but the scanner really does ~200/h every hour: capped by the median."""
    since, until = H0, H0 + DAY + LAG
    (cov,) = compute_set_coverage(
        {"all": _full(H0, range(24), sweeps=200)}, {"all": H0 - DAY}, since, until, 60, 360
    )
    assert cov.downtime_min == 0


def test_normal_jitter_is_not_downtime() -> None:
    since, until = H0, H0 + DAY + LAG
    sweeps = _full(H0, range(24))
    sweeps[H0 + HOUR_MS] = 340
    (cov,) = compute_set_coverage({"all": sweeps}, {"all": H0 - DAY}, since, until, 60, 360)
    assert cov.downtime_min == 0


def test_newest_hour_is_skipped_until_its_counters_are_flushed() -> None:
    since = H0
    fresh_end = H0 + DAY + 120_000  # last hour closed only 2 min ago: flush lag
    (cov,) = compute_set_coverage({}, {"all": H0 - DAY}, since, fresh_end, 60, 360)
    assert cov.hours_expected == 23
    (later,) = compute_set_coverage({}, {"all": H0 - DAY}, since, H0 + DAY + LAG, 60, 360)
    assert later.hours_expected == 24
