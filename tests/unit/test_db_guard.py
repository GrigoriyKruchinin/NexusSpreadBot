import pytest

from tests.db_guard import UnsafeDatabaseError, assert_test_database


def test_accepts_test_db() -> None:
    assert_test_database("nexus_test")


@pytest.mark.parametrize(
    "name", ["nexus", "", "postgres", "nexus_test2", "Nexus_test", "prod_nexus_test"]
)
def test_refuses_other_dbs(name: str) -> None:
    with pytest.raises(UnsafeDatabaseError):
        assert_test_database(name)
