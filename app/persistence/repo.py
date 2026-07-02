from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.base import AgentView
from app.persistence.models import (
    AgentViewLog,
    BrokerState,
    DebateLog,
    Decision,
    EquitySnapshot,
    Lesson,
)


def load_broker_state(session: Session) -> dict | None:
    """Return the persisted broker state (balance + positions), or None."""
    row = session.get(BrokerState, 1)
    if row is None:
        return None
    try:
        return json.loads(row.state_json)
    except Exception:
        return None


def save_broker_state(session: Session, state: dict) -> None:
    """Upsert the single broker-state row with the latest serialised state."""
    payload = json.dumps(state)
    now = datetime.now(tz=UTC).isoformat()
    row = session.get(BrokerState, 1)
    if row is None:
        session.add(BrokerState(id=1, state_json=payload, updated_at=now))
    else:
        row.state_json = payload
        row.updated_at = now


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


def save_debate(
    session: Session,
    decision_id: int | None,
    asset: str,
    bull_summary: str,
    bear_summary: str,
    transcript: list[dict],
) -> None:
    """Persist a bull-vs-bear debate transcript linked to a decision."""
    session.add(
        DebateLog(
            decision_id=decision_id,
            asset=asset,
            timestamp=datetime.now(tz=UTC).isoformat(),
            bull_summary=bull_summary,
            bear_summary=bear_summary,
            transcript_json=json.dumps(transcript),
        )
    )


def get_recent_debates(session: Session, limit: int = 20) -> list[dict]:
    """Return the most-recent debate transcripts as plain dicts."""
    rows = (
        session.query(DebateLog)
        .order_by(DebateLog.id.desc())
        .limit(limit)
        .all()
    )
    results: list[dict] = []
    for r in rows:
        try:
            transcript = json.loads(r.transcript_json)
        except Exception:
            transcript = []
        results.append(
            {
                "id": r.id,
                "decision_id": r.decision_id,
                "asset": r.asset,
                "timestamp": r.timestamp,
                "bull_summary": r.bull_summary,
                "bear_summary": r.bear_summary,
                "transcript": transcript,
            }
        )
    return results


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


def add_lessons(session: Session, texts: list[str]) -> None:
    """Persist a batch of lesson strings from the reflection agent."""
    now = datetime.now(tz=UTC).isoformat()
    for text in texts:
        session.add(Lesson(created_at=now, text=text))


def get_recent_lessons(session: Session, limit: int = 8) -> list[str]:
    """Return the most-recent lesson texts (newest first)."""
    rows = (
        session.query(Lesson)
        .order_by(Lesson.id.desc())
        .limit(limit)
        .all()
    )
    return [r.text for r in rows]
