"""Unit tests are hermetic: no implicit use of the repo ``config/nexus.toml`` (A7, risk R2)."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def _empty_config_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("nexus-config") / "empty.toml"
    path.write_text("# hermetic unit-test settings file: no keys, code defaults apply\n")
    return path


@pytest.fixture(autouse=True)
def _hermetic_config_file(monkeypatch: pytest.MonkeyPatch, _empty_config_file: Path) -> None:
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(_empty_config_file))
