"""Human-readable, plain-Italian explanation of each trading cycle.

Designed for a reader who knows programming but little about crypto/trading:
every decision (open, close, or stay flat) is narrated in simple language.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.base import AgentView
    from app.agents.portfolio_manager import TradeIdea
    from app.agents.risk_manager import ValidatedOrder

# Friendly labels for each specialist agent.
_AGENT_LABEL = {
    "technical": "Tecnico",
    "forecast": "Previsione",
    "sentiment": "Sentiment",
    "onchain": "On-chain",
    "news": "Notizie",
}

# Plain-Italian sentence per agent depending on its signal.
_AGENT_SENTENCE = {
    "technical": {
        "long": "gli indicatori tecnici (MACD/RSI) puntano al rialzo",
        "short": "gli indicatori tecnici (MACD/RSI) puntano al ribasso",
        "neutral": "gli indicatori tecnici sono incerti",
    },
    "forecast": {
        "long": "il modello statistico (Prophet) prevede il prezzo in salita",
        "short": "il modello statistico (Prophet) prevede il prezzo in discesa",
        "neutral": "il modello statistico prevede un prezzo quasi piatto",
    },
    "sentiment": {
        "long": "il mercato è in 'paura' → spesso segnale di rimbalzo (contrarian)",
        "short": "il mercato è 'avido' → possibile eccesso, rischio di correzione",
        "neutral": "l'umore del mercato è neutro",
    },
    "onchain": {
        "long": "i grandi portafogli ('balene') stanno comprando",
        "short": "i grandi portafogli ('balene') stanno vendendo",
        "neutral": "nessun grande movimento di 'balene' rilevato",
    },
    "news": {
        "long": "le notizie recenti sono positive",
        "short": "le notizie recenti sono negative / rischiose",
        "neutral": "nessuna notizia rilevante",
    },
}

_SIGNAL_IT = {"long": "RIALZO", "short": "RIBASSO", "neutral": "NEUTRO"}


def _agent_line(view: "AgentView") -> str:
    label = _AGENT_LABEL.get(view.agent, view.agent.capitalize())
    sentence = _AGENT_SENTENCE.get(view.agent, {}).get(
        view.signal, view.rationale[:90]
    )
    pct = int(round(view.confidence * 100))
    signal_it = _SIGNAL_IT.get(view.signal, view.signal)
    return f"  • {label:<11} → {signal_it:<7} (sicurezza {pct:>3}%): {sentence}"


def explain_cycle(
    asset: str,
    mark_price: float,
    views: list["AgentView"],
    idea: "TradeIdea",
    order: "ValidatedOrder",
    balance: float,
) -> str:
    """Return a plain-Italian block explaining what happened for one asset."""
    line = "=" * 64
    out: list[str] = [line, f"📊 {asset} — prezzo attuale: {mark_price:,.2f}", "-" * 64]

    out.append("Cosa pensano i 5 analisti:")
    if views:
        out.extend(_agent_line(v) for v in views)
    else:
        out.append("  (nessun analista disponibile in questo ciclo)")

    n_long = sum(1 for v in views if v.signal == "long")
    n_short = sum(1 for v in views if v.signal == "short")
    n_neutral = sum(1 for v in views if v.signal == "neutral")
    conv = int(round(idea.conviction * 100))
    out.append("")
    out.append(
        f"Voti: {n_long} RIALZO · {n_short} RIBASSO · {n_neutral} NEUTRO  "
        f"→ convinzione pesata {conv}%"
    )
    out.append(
        "  (ogni voto pesa per importanza dell'agente × sicurezza; "
        "i NEUTRO valgono 0 e abbassano la media)"
    )

    if order.veto:
        out.append(f"  🔴 OPERAZIONE BLOCCATA dal Risk Manager. Motivo: {order.veto_reason}")
        out.append(f"  Capitale invariato (saldo {balance:,.2f}).")
    elif order.action == "hold":
        out.append(
            f"  🟡 NESSUNA OPERAZIONE. La convinzione pesata ({conv}%) è sotto la soglia "
            "che il gestore richiede per rischiare capitale: resta liquido."
        )
        out.append(f"  Saldo invariato: {balance:,.2f}.")
    elif order.action in ("open_long", "open_short"):
        if order.action == "open_long":
            verso = "LONG (scommette che SALE)"
        else:
            verso = "SHORT (scommette che SCENDE)"
        out.append(f"  🟢 APERTA posizione {verso} su {asset}.")
        out.append(f"     Quanto: {order.size_pct * 100:.1f}% del capitale.")
        out.append(
            f"     Stop-loss a {order.sl_price:,.2f} "
            f"(esce in perdita ~{order.sl_pct * 100:.1f}% se va male)."
        )
        out.append(
            f"     Take-profit a {order.tp_price:,.2f} "
            f"(incassa il guadagno ~{order.tp_pct * 100:.1f}% se va bene)."
        )
        out.append(f"  Saldo dopo l'operazione: {balance:,.2f}.")
    elif order.action == "close":
        out.append(f"  🔵 CHIUSA la posizione su {asset} al prezzo {mark_price:,.2f}.")
        out.append(f"  Saldo aggiornato: {balance:,.2f}.")

    out.append(line)
    return "\n".join(out)
