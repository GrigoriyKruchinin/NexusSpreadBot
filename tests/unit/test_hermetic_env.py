"""Unit tests must not see a developer's `.env` or Nexus variables (T11, todo 'Test isolation')."""

from pathlib import Path

from nexus.config.groups import KeyPolicySettings


def test_cwd_is_not_the_repo_root() -> None:
    assert not (Path.cwd() / "pyproject.toml").exists()
    assert not (Path.cwd() / ".env").exists()


def test_inherited_key_policy_variables_do_not_leak_in() -> None:
    # The fixture runs each test in an empty tmp dir, so defaults apply.
    assert KeyPolicySettings().strict is False
