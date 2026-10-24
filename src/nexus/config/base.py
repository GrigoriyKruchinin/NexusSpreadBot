"""Shared base class and helpers for all settings groups."""

from __future__ import annotations

import os
from typing import Annotated, Any

from pydantic import BeforeValidator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from nexus.config.file import toml_source

RUNTIME_ENV_VAR = "NEXUS_RUNTIME"
"""Set to ``container`` in Docker images: disables ``.env`` file loading entirely."""


class NexusBaseSettings(BaseSettings):
    """Base class for every settings group.

    Each subclass declares its own ``env_prefix`` so that it reads only the variables of
    its domain. Unknown variables are ignored, which lets several groups share one
    process environment (or one local ``.env`` file) without leaking into each other.

    Inside containers (``NEXUS_RUNTIME=container``) the ``.env`` file is never read, so a
    stray mounted ``.env`` cannot bypass the per-service environment isolation.
    Validation errors never echo input values (they may contain secrets).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        env_ignore_empty=True,  # docker compose passes unset optional vars as ""
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Priority env > ``.env`` > ``config/nexus.toml`` > code default.

        The dotenv source is dropped inside a container. The TOML source runs the fail-closed
        guard of :mod:`nexus.config.file` on every load.
        """
        toml_settings = toml_source(settings_cls)
        if os.environ.get(RUNTIME_ENV_VAR, "").strip().lower() == "container":
            return init_settings, env_settings, toml_settings, file_secret_settings
        return init_settings, env_settings, dotenv_settings, toml_settings, file_secret_settings


def _split_csv_or_json(value: Any) -> Any:
    """Accept both ``a,b,c`` and ``["a","b","c"]`` for list-like env variables."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.startswith("["):
            import json

            return json.loads(stripped)
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return value


StrTuple = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_split_csv_or_json)]
"""Tuple of strings parsed from a comma-separated or JSON-array env variable."""
