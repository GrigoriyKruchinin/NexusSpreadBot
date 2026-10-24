"""SQLAlchemy ORM models.

Money values use unconstrained ``NUMERIC`` so Decimals round-trip exactly.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.simulation.portfolio import DEFAULT_PORTFOLIO_ID

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Money = Numeric()
"""Unbounded NUMERIC: exact Decimal round-trip."""


class Base(DeclarativeBase):
    """Declarative base with deterministic constraint names."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class MarketPairRow(Base):
    """Latest known metadata of a spot market on an exchange."""

    __tablename__ = "market_pairs"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_market_pairs_exchange_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(64))
    base: Mapped[str] = mapped_column(String(32))
    quote: Mapped[str] = mapped_column(String(32))
    taker_fee: Mapped[Decimal] = mapped_column(Money)
    taker_fee_is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    amount_step: Mapped[Decimal | None] = mapped_column(Money)
    min_amount: Mapped[Decimal | None] = mapped_column(Money)
    min_cost: Mapped[Decimal | None] = mapped_column(Money)
    active: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SpreadSnapshotRow(Base):
    """Top-of-book gross spread sample (top-K routes per sweep) for analytics."""

    __tablename__ = "spread_snapshots"
    __table_args__ = (
        Index("ix_spread_snapshots_captured_at", "captured_at"),
        Index("ix_spread_snapshots_symbol_captured_at", "symbol", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    symbol: Mapped[str] = mapped_column(String(64))
    buy_exchange: Mapped[str] = mapped_column(String(32))
    sell_exchange: Mapped[str] = mapped_column(String(32))
    ask: Mapped[Decimal] = mapped_column(Money)
    bid: Mapped[Decimal] = mapped_column(Money)
    gross_spread_pct: Mapped[Decimal] = mapped_column(Money)
    fee_bound_net_pct: Mapped[Decimal] = mapped_column(Money)


class SpreadEvaluationRow(Base):
    """Depth-aware evaluation of a candidate route (profitable or not)."""

    __tablename__ = "spread_evaluations"
    __table_args__ = (
        Index("ix_spread_evaluations_evaluated_at", "evaluated_at"),
        Index("ix_spread_evaluations_status_evaluated_at", "status", "evaluated_at"),
        Index("ix_spread_evaluations_symbol_evaluated_at", "symbol", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    symbol: Mapped[str] = mapped_column(String(64))
    base: Mapped[str] = mapped_column(String(32))
    quote: Mapped[str] = mapped_column(String(32))
    buy_exchange: Mapped[str] = mapped_column(String(32))
    sell_exchange: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text, default="")
    fees_estimated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notional_usd: Mapped[Decimal] = mapped_column(Money)
    gross_spread_pct: Mapped[Decimal | None] = mapped_column(Money)
    buy_book_age_ms: Mapped[int] = mapped_column(Integer)
    sell_book_age_ms: Mapped[int] = mapped_column(Integer)
    transfer_status: Mapped[str] = mapped_column(String(16))
    transfer_network: Mapped[str | None] = mapped_column(String(64))
    transfer_fee_base: Mapped[Decimal] = mapped_column(Money)
    transfer_note: Mapped[str] = mapped_column(Text, default="")
    # Breakdown (NULL when the evaluation stopped before simulating both legs)
    best_ask_buy: Mapped[Decimal | None] = mapped_column(Money)
    best_bid_sell: Mapped[Decimal | None] = mapped_column(Money)
    vwap_buy: Mapped[Decimal | None] = mapped_column(Money)
    vwap_sell: Mapped[Decimal | None] = mapped_column(Money)
    base_bought: Mapped[Decimal | None] = mapped_column(Money)
    base_received: Mapped[Decimal | None] = mapped_column(Money)
    base_sold: Mapped[Decimal | None] = mapped_column(Money)
    cost_quote: Mapped[Decimal | None] = mapped_column(Money)
    proceeds_quote: Mapped[Decimal | None] = mapped_column(Money)
    net_profit_usd: Mapped[Decimal | None] = mapped_column(Money)
    net_profit_pct: Mapped[Decimal | None] = mapped_column(Money)
    fee_buy_usd: Mapped[Decimal | None] = mapped_column(Money)
    fee_sell_usd: Mapped[Decimal | None] = mapped_column(Money)
    transfer_fee_usd: Mapped[Decimal | None] = mapped_column(Money)
    slippage_usd: Mapped[Decimal | None] = mapped_column(Money)
    episode_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("opportunity_episodes.id", ondelete="SET NULL"),
        index=True,
    )


class OpportunityEpisodeRow(Base):
    """A continuous run of one route meeting the thresholds (see ``domain.episodes``)."""

    __tablename__ = "opportunity_episodes"
    __table_args__ = (
        Index(
            "uq_opportunity_episodes_open_route",
            "symbol",
            "buy_exchange",
            "sell_exchange",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index("ix_opportunity_episodes_opened_at", "opened_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64))
    buy_exchange: Mapped[str] = mapped_column(String(32))
    sell_exchange: Mapped[str] = mapped_column(String(32))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(16))
    first_net_usd: Mapped[Decimal] = mapped_column(Money)
    peak_net_usd: Mapped[Decimal] = mapped_column(Money)
    last_net_usd: Mapped[Decimal] = mapped_column(Money)
    peak_net_pct: Mapped[Decimal] = mapped_column(Money)
    evaluations: Mapped[int] = mapped_column(Integer)
    transfer_status: Mapped[str] = mapped_column(String(16))
    transfer_network: Mapped[str | None] = mapped_column(String(64))
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alerted_net_usd: Mapped[Decimal | None] = mapped_column(Money)
    realerts: Mapped[int] = mapped_column(Integer, server_default="0")
    survived_latency: Mapped[bool | None] = mapped_column(Boolean)
    unverified_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertLogRow(Base):
    """Delivery record of an opportunity alert (unique per evaluation: idempotency)."""

    __tablename__ = "alert_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("spread_evaluations.id", ondelete="CASCADE"), unique=True
    )
    channel: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    message_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExchangeHealthRow(Base):
    """Outcome of exchange calls (connectivity / latency history)."""

    __tablename__ = "exchange_health"
    __table_args__ = (Index("ix_exchange_health_exchange_checked_at", "exchange", "checked_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exchange: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class RouteQuarantineRow(Base):
    """History of route quarantines (the live state lives in Redis)."""

    __tablename__ = "route_quarantine"
    __table_args__ = (
        Index("ix_route_quarantine_started_at", "started_at"),
        Index("ix_route_quarantine_route", "symbol", "buy_exchange", "sell_exchange"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64))
    buy_exchange: Mapped[str] = mapped_column(String(32))
    sell_exchange: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperPortfolioRow(Base):
    """Registry of paper portfolio runs (one row per run; the latest row of a name is current).

    ``started_at`` is the portfolio's ``since``: unlike the snapshots it is never purged by
    retention. A changed definition (``config_hash``) starts a new run with fresh capital.
    """

    __tablename__ = "paper_portfolios"
    __table_args__ = (
        Index("ix_paper_portfolios_portfolio_started_at", "portfolio_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    """Run id."""
    portfolio_id: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venues: Mapped[str] = mapped_column(Text)
    """Sorted venue names, comma-separated (empty for the legacy pre-B15 run)."""
    capital_usd: Mapped[Decimal] = mapped_column(Money)
    config_hash: Mapped[str] = mapped_column(String(64))
    """SHA-256 of the run definition (``legacy`` for the backfilled pre-B15 run)."""


class PaperCapStatsRow(Base):
    """Hourly per-set cap-binding counters (is the candidate cap distorting a set?)."""

    __tablename__ = "paper_cap_stats"

    portfolio_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    sweeps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sweeps_cap_bound: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    """Sweeps in which the set's own top-N cut at least one eligible route."""
    dropped_routes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    """Eligible routes cut by the cap, summed over the hour's sweeps."""
    alerts_cap_excluded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    """Alerts on routes inside the set but outside its top-N that sweep (not paper-traded)."""


class PaperTradeRow(Base):
    """A simulated trade (executed or skipped with a reason)."""

    __tablename__ = "paper_trades"
    __table_args__ = (
        Index("ix_paper_trades_portfolio_executed_at", "portfolio_id", "executed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        String(32), default=DEFAULT_PORTFOLIO_ID, server_default=DEFAULT_PORTFOLIO_ID
    )
    """Venue set (shadow portfolio) the trade belongs to."""
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    episode_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("opportunity_episodes.id", ondelete="SET NULL")
    )
    symbol: Mapped[str] = mapped_column(String(64))
    base: Mapped[str] = mapped_column(String(32))
    buy_exchange: Mapped[str] = mapped_column(String(32))
    sell_exchange: Mapped[str] = mapped_column(String(32))
    executed: Mapped[bool] = mapped_column(Boolean)
    skip_reason: Mapped[str | None] = mapped_column(String(32))
    cost_quote: Mapped[Decimal | None] = mapped_column(Money)
    proceeds_quote: Mapped[Decimal | None] = mapped_column(Money)
    base_bought: Mapped[Decimal | None] = mapped_column(Money)
    base_sold: Mapped[Decimal | None] = mapped_column(Money)
    net_usd: Mapped[Decimal | None] = mapped_column(Money)
    net_pct: Mapped[Decimal | None] = mapped_column(Money)


class PaperRebalanceRow(Base):
    """A virtual inventory transfer (simulation only - nothing is ever transferred)."""

    __tablename__ = "paper_rebalances"
    __table_args__ = (
        Index("ix_paper_rebalances_portfolio_started_at", "portfolio_id", "started_at"),
        Index("ix_paper_rebalances_portfolio_status", "portfolio_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        String(32), default=DEFAULT_PORTFOLIO_ID, server_default=DEFAULT_PORTFOLIO_ID
    )
    asset: Mapped[str] = mapped_column(String(32))
    from_exchange: Mapped[str] = mapped_column(String(32))
    to_exchange: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal] = mapped_column(Money)
    fee_usd: Mapped[Decimal] = mapped_column(Money)
    network: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperBalanceSnapshotRow(Base):
    """Paper holdings of one venue at a point in time (the latest set restores the state)."""

    __tablename__ = "paper_balance_snapshots"
    __table_args__ = (
        Index("ix_paper_balance_snapshots_portfolio_captured_at", "portfolio_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        String(32), default=DEFAULT_PORTFOLIO_ID, server_default=DEFAULT_PORTFOLIO_ID
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exchange: Mapped[str] = mapped_column(String(32))
    asset: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Money)
    seed_amount: Mapped[Decimal | None] = mapped_column(Money)
    seed_price: Mapped[Decimal | None] = mapped_column(Money)
    price_usd: Mapped[Decimal | None] = mapped_column(Money)


class ExchangeMetadataStatsRow(Base):
    """Per-exchange metadata quality after each refresh (digest: transfer coverage)."""

    __tablename__ = "exchange_metadata_stats"
    __table_args__ = (
        Index("ix_exchange_metadata_stats_exchange_captured_at", "exchange", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exchange: Mapped[str] = mapped_column(String(32))
    markets: Mapped[int] = mapped_column(Integer)
    transfer_coverage_pct: Mapped[int | None] = mapped_column(Integer)
