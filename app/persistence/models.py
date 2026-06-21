from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(
        default=lambda: datetime.now(tz=UTC).isoformat()
    )
    balance: Mapped[float]
    open_pnl: Mapped[float | None] = mapped_column(nullable=True, default=None)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asset: Mapped[str]
    side: Mapped[str]
    entry_price: Mapped[float]
    exit_price: Mapped[float | None] = mapped_column(nullable=True, default=None)
    size: Mapped[float]
    pnl: Mapped[float | None] = mapped_column(nullable=True, default=None)
    opened_at: Mapped[str]
    closed_at: Mapped[str | None] = mapped_column(nullable=True, default=None)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asset: Mapped[str]
    timestamp: Mapped[str] = mapped_column(
        default=lambda: datetime.now(tz=UTC).isoformat()
    )
    action: Mapped[str]
    conviction: Mapped[float]
    combined_rationale: Mapped[str]
    veto: Mapped[bool] = mapped_column(default=False)
    veto_reason: Mapped[str] = mapped_column(default="")

    agent_views: Mapped[list[AgentViewLog]] = relationship(
        "AgentViewLog", back_populates="decision", cascade="all, delete-orphan"
    )


class AgentViewLog(Base):
    __tablename__ = "agent_views_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("decisions.id"), nullable=True, default=None
    )
    agent: Mapped[str]
    asset: Mapped[str]
    timestamp: Mapped[str] = mapped_column(
        default=lambda: datetime.now(tz=UTC).isoformat()
    )
    signal: Mapped[str]
    confidence: Mapped[float]
    rationale: Mapped[str]

    decision: Mapped[Decision | None] = relationship(
        "Decision", back_populates="agent_views"
    )


def init_db(database_url: str):
    """Create all tables and return the engine."""
    from sqlalchemy import Engine

    engine: Engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    return engine
