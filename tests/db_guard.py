"""Safety guard: integration tests may only touch the dedicated test database (R-01)."""

TEST_DB_NAME = "nexus_test"
LIVE_DB_NAME = "nexus"


class UnsafeDatabaseError(RuntimeError):
    """Raised when integration tests are pointed at a non-test database."""


def assert_test_database(db_name: str) -> None:
    """Refuse unless ``db_name`` is exactly the dedicated test database."""
    name = db_name.strip()
    if name == LIVE_DB_NAME or name != TEST_DB_NAME:
        msg = (
            f"refusing to run integration tests on database {name!r}: "
            f"only {TEST_DB_NAME!r} is allowed (set POSTGRES_DB={TEST_DB_NAME})"
        )
        raise UnsafeDatabaseError(msg)
