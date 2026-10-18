"""Async engine and session factory."""

from __future__ import annotations

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from nexus.config.groups import DatabaseSettings


def database_url(settings: DatabaseSettings, *, driver: str = "postgresql+asyncpg") -> URL:
    """Build a SQLAlchemy URL (password is escaped and never rendered in ``str(url)``)."""
    return URL.create(
        drivername=driver,
        username=settings.user,
        password=settings.password.get_secret_value(),
        host=settings.host,
        port=settings.port,
        database=settings.db,
    )


def create_engine(settings: DatabaseSettings, *, pooled: bool = True) -> AsyncEngine:
    """Create an async engine.

    Use ``pooled=False`` for short-lived event loops (e.g. Celery tasks running
    ``asyncio.run`` per task) to avoid sharing connections across loops.
    """
    if pooled:
        return create_async_engine(
            database_url(settings),
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_pre_ping=True,
            echo=settings.echo,
        )
    return create_async_engine(database_url(settings), poolclass=NullPool, echo=settings.echo)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to ``engine``."""
    return async_sessionmaker(engine, expire_on_commit=False)
