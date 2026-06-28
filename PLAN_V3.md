# PLAN v3 — Performance & reasoning upgrades (for Claude Code)

> Repo: `mazzocco51/trading-ai-multiagent`. Paper trading only — **no real money**, default
> `PaperBroker`. Conventions: branch per task `feat/<id>`; each code task ships pytest;
> `ruff check .` clean; CI green before merge. Never trade/close on price <= 0. Don't commit
> this file or `.claude/`.
>
> **Honest framing (put a short version in GUIDA.md):** an LLM-vote bot on hourly crypto is
> not expected to beat buy & hold; the goal here is *better decisions, less bleed, and
> portfolio-grade engineering*, inspired by TradingAgents (bull/bear debate) and FinMem
> (reflection memory). No profit is guaranteed.

## Diagnosis (why it sits at a persistent loss)
- **Structural long bias**: SentimentAgent is contrarian on Fear & Greed; in persistent "fear"
  it votes long almost always → the desk buys dips in downtrends and gets stopped at −3%.
- **No trend filter**: it opens against the dominant direction.
- **No memory**: every decision is stateless; it never learns from repeated stop-outs.
- **Fees+slippage churn** with no real edge → slow bleed.

Work in this order: A (biggest bleed fix) → B (learning) → D (measure) → C (optional, the
"wow" feature). A, B, C touch mostly different files and can be split across subagents; keep
`orchestrator.py`/`config.py` edits coordinated.

---

## Workstream A — Stop the bleed (trend filter + cooldown + de-bias)

### A1 — Trend filter / regime gate
- In `app/data/indicators.py` add a slow trend reference to the indicators dict, e.g.
  `trend_ema` = EMA(close, period=`trend_ema_period`, default 50) and `last_close`.
- Enforce in the decision path (in `PortfolioManagerAgent` or a gate in `orchestrator.py`):
  - allow `open_long` only if `last_close > trend_ema`;
  - allow `open_short` only if `last_close < trend_ema`;
  - if the proposed action fights the trend → downgrade to `hold`.
- Config: `trend_filter_enabled: bool = True`, `trend_ema_period: int = 50`.
- Tests: long blocked when price below trend EMA; short blocked when above.

### A2 — Cooldown after stop-loss
- Don't re-open the same asset within `cooldown_hours_after_stop` (config, default 6) of a
  stop-loss exit. Track per-asset last-stop timestamp (extend broker state / a small dict
  persisted in `broker_state`, or a `last_stop_at` map in the DB).
- Tests: a stop on BTC blocks a new BTC open for the cooldown window.

### A3 — Reduce the long bias
- Either lower SentimentAgent weight, or make Sentiment only emit a non-neutral signal on
  **extreme** Fear & Greed (e.g. <25 or >75); otherwise neutral. Make it config-driven.
- Re-check weights still sum to 1.0.

**A acceptance:** over a backtest on a downtrend window, number of stop-outs and net loss drop
materially vs current `main`.

---

## Workstream B — Reflection / memory loop (learn from outcomes)

Goal: after every N closed trades, an LLM distils lessons that feed future decisions.

### B1 — Storage
- New SQLAlchemy model `Lesson(id, created_at, text)` in `app/persistence/models.py` + repo
  helpers `add_lessons(session, texts)` and `get_recent_lessons(session, limit=8)`.

### B2 — Reflection agent
- New `app/agents/reflection.py` + `prompts/reflection.md`. Input: the last K closed trades
  (asset, side, entry, exit, pnl, holding time, the decision rationale) + current lessons.
  Output: 3–6 short, concrete rules — what worked, anti-patterns, recurring mistakes.
- Trigger: in `orchestrator.py`/`run.py`, after closed-trade count crosses a multiple of
  `reflection_every_n_trades` (config, default 5), run reflection and store the lessons.

### B3 — Inject into decisions
- Pass the latest lessons into `PortfolioManagerAgent.aggregate` (new optional arg) and append
  them to its prompt/user message: "Lessons learned so far: ...". The PM must consider them.
- Tests: reflection produces/stores lessons (LLM mocked); PM receives lessons in its payload.

**B acceptance:** after enough trades, `lessons` table populates and the PM prompt includes
them; deterministic tests with a mocked gateway.

---

## Workstream D — Backtest & evaluation report (measure A/B)

Complete `app/backtest.py` so the team can prove whether A/B help.
- Replay historical OHLCV through the same orchestrator with the LLM mockable/cached.
- Produce a report: total return, **return vs BTC buy & hold**, Sharpe (simplified), max
  drawdown, win rate, profit factor, # trades.
- A CLI: `python -m app.backtest --start ... --end ... [--no-llm]`. Save a small markdown/JSON
  report under `reports/`.
- Tests: backtest runs end-to-end on a fixed fixture and emits all metrics.

**D acceptance:** one command yields a reproducible report comparing the desk to BTC b&h.

---

## Workstream C — Bull vs Bear debate (optional, the headline feature)

Mirror TradingAgents' dialectical step before aggregation.
- New `app/agents/debate.py` (or `bull.py` + `bear.py`) + prompts. Given the 5 `AgentView`s and
  the context, a **Bull** argues the long case and a **Bear** the short case (1–2 rounds).
- The `PortfolioManager` (acting as judge) then synthesizes the debate transcript **plus** the
  weighted votes into the final `TradeIdea`. Persist the transcript for the dashboard.
- Keep it behind a config flag `debate_enabled: bool = False` so it can be A/B-tested vs the
  plain vote via the backtest (Workstream D).
- Tests: debate produces a transcript; PM consumes it; flag off → behaviour unchanged.
- Dashboard (optional): show the bull/bear summary under each decision.

---

## Subagent split
- **Subagent 1 → A** (indicators, config, orchestrator/PM gate, broker cooldown). Do first.
- **Subagent 2 → B** (persistence model, reflection agent, prompt, PM injection).
- **Subagent 3 → D** (backtest + report) — depends loosely on A/B contracts; can start in
  parallel and integrate after.
- **Subagent 4 → C** (debate) — optional, after A/B merge to avoid orchestrator conflicts.

## Global definition of done
- `ruff` clean, `pytest` green (existing ~60 + new), CI green.
- Weights still sum to 1.0; paper-only; no real orders; price<=0 guard intact.
- Update `GUIDA.md` (and a line in README) describing the trend filter, the reflection memory,
  the honest "not expected to beat the market" note, and (if shipped) the debate stage.
- Backtest report committed under `reports/` showing before/after on a fixed window.

## Verify locally
```
py -m pytest -q
py -m ruff check .
py -m app.run
py -m app.backtest --start 2024-01-01 --end 2024-06-30 --no-llm
py -m dashboard.build_html
```
