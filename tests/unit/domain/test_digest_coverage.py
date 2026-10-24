from nexus.domain.digest import HOUR_MS, SetCoverage, compute_set_coverage

H0 = 1_800_000_000_000 // HOUR_MS * HOUR_MS  # an hour boundary
DAY = 24 * HOUR_MS


def _full(start: int, hours: range, sweeps: int = 360) -> dict[int, int]:
    return {start + h * HOUR_MS: sweeps for h in hours}


def test_continuous_run_has_no_gap() -> None:
    since, until = H0, H0 + DAY
    counts = {"all": _full(H0, range(24))}
    (cov,) = compute_set_coverage(counts, {"all": H0 - 5 * DAY}, since, until, 60)
    assert cov == SetCoverage("all", 24, 0, 0)


def test_missing_hours_and_thin_hours_count_as_downtime() -> None:
    since, until = H0, H0 + DAY
    sweeps = _full(H0, range(24))
    del sweeps[H0 + 3 * HOUR_MS]  # dark hour
    sweeps[H0 + 4 * HOUR_MS] = 30  # half of the minimum
    (cov,) = compute_set_coverage({"all": sweeps}, {"all": H0 - DAY}, since, until, 60)
    assert (cov.hours_expected, cov.hours_gap, cov.downtime_min) == (24, 2, 90)


def test_partial_window_edges_are_skipped() -> None:
    since, until = H0 + 600_000, H0 + DAY + 600_000  # not on an hour boundary
    (cov,) = compute_set_coverage(
        {"all": _full(H0, range(25))}, {"all": H0 - DAY}, since, until, 60
    )
    assert cov.hours_expected == 23


def test_new_set_is_judged_only_after_its_first_hour() -> None:
    since, until = H0, H0 + DAY
    first_seen = H0 + 10 * HOUR_MS + 1_000  # appeared inside hour 10
    sweeps = _full(H0, range(10, 24))
    sweeps[H0 + 10 * HOUR_MS] = 3  # partial first hour: ignored
    (cov,) = compute_set_coverage({"s": sweeps}, {"s": first_seen}, since, until, 60)
    assert (cov.hours_expected, cov.hours_gap) == (13, 0)


def test_set_added_in_the_last_hour_has_no_complete_hour() -> None:
    since, until = H0, H0 + DAY
    (cov,) = compute_set_coverage({}, {"s": until - 1_000}, since, until, 60)
    assert (cov.hours_expected, cov.hours_gap, cov.downtime_min) == (0, 0, 0)


def test_all_first_then_alphabetical() -> None:
    first = {"excl_bybit": 0, "all": 0, "excl_conditional": 0}
    result = compute_set_coverage({}, first, H0, H0 + 2 * HOUR_MS, 60)
    assert [c.portfolio_id for c in result] == ["all", "excl_bybit", "excl_conditional"]
