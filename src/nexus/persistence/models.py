"""SQLAlchemy ORM models.

Money values use unconstrained ``NUMERIC`` so Decimals round-trip exactly.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
    # Written by the alerts worker only (never by the scanner's state saves).
    alert_message_id: Mapped[str | None] = mapped_column(String(64))
    """Telegram message of the episode: NEW sends it, UPDATE and CLOSED edit it."""
    alert_evaluation_id: Mapped[int | None] = mapped_column(BigInteger)
    """Evaluation behind the last rendering of the message (CLOSED re-renders from it)."""
    alert_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """AlertContext payload of the last rendering (volume / transfer blocks are not persisted
    anywhere else)."""


class AlertHourBudgetRow(Base):
    """NEW-message budget of one clock hour and its "N more suppressed" summary message."""

    __tablename__ = "alert_hour_budget"

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    sent: Mapped[int] = mapped_column(Integer, server_default="0")
    suppressed: Mapped[int] = mapped_column(Integer, server_default="0")
    summary_message_id: Mapped[str | None] = mapped_column(String(64))


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
