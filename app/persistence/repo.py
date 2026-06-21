from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.base import AgentView
from app.persistence.models import AgentViewLog, Decision, EquitySnapshot


def save_decision(
    session: Session,
    asset: str,
    action: str,
    conviction: float,
    rationale: str,
    veto: bool,
    veto_reason: str,
    views: list[AgentView],
) -> int:
    """Persist a Decision row and all associated AgentViewLog rows.

    Returns the auto-generated decision_id.
    """
    now = datetime.now(tz=UTC).isoformat()

    decision = Decision(
        asset=asset,
        timestamp=now,
        action=action,
        conviction=conviction,
        combined_rationale=rationale,
        veto=veto,
        veto_reason=veto_reason,
    )
    session.add(decision)
    session.flush()  # populate decision.id without committing

    for v in views:
        log = AgentViewLog(
            decision_id=decision.id,
            agent=v.agent,
            asset=v.asset,
            timestamp=now,
            signal=v.signal,
            confidence=v.confidence,
            rationale=v.rationale,
        )
        session.add(log)

    return decision.id


def save_equity_snapshot(
    session: Session,
    balance: float,
    open_pnl: float = 0.0,
) -> None:
    """Persist a balance snapshot."""
    snapshot = EquitySnapshot(
        timestamp=datetime.now(tz=UTC).isoformat(),
        balance=balance,
        open_pnl=open_pnl,
    )
    session.add(snapshot)


def get_recent_decisions(session: Session, limit: int = 50) -> list[dict]:
    """Return the most-recent decisions with their agent views as plain dicts.

    Each dict has all Decision columns plus an ``agent_views`` list.
    """
    decisions = (
        session.query(Decision)
        .order_by(Decision.id.desc())
        .limit(limit)
        .all()
    )

    results: list[dict] = []
    for d in decisions:
        views = [
            {
                "agent": v.agent,
                "asset": v.asset,
                "timestamp": v.timestamp,
                "signal": v.signal,
                "confidence": v.confidence,
                "rationale": v.rationale,
            }
            for v in d.agent_views
        ]
        results.append(
            {
                "id": d.id,
                "asset": d.asset,
                "timestamp": d.timestamp,
                "action": d.action,
                "conviction": d.conviction,
                "combined_rationale": d.combined_rationale,
                "veto": d.veto,
                "veto_reason": d.veto_reason,
                "agent_views": views,
            }
        )
    return results


def get_equity_history(session: Session, limit: int = 200) -> list[dict]:
    """Return the most-recent equity snapshots as plain dicts."""
    snapshots = (
        session.query(EquitySnapshot)
        .order_by(EquitySnapshot.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": s.id,
            "timestamp": s.timestamp,
            "balance": s.balance,
            "open_pnl": s.open_pnl,
        }
        for s in snapshots
    ]
