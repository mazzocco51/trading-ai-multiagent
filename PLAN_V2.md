# PLAN v2 — for Claude Code (build with subagents)

> Repo: `mazzocco51/trading-ai-multiagent`. Stack: Python 3.11, pydantic/pydantic-settings,
> ccxt, Prophet, SQLAlchemy + Neon (Postgres), Streamlit + static HTML dashboard,
> GitHub Actions cron + cron-job.org trigger, deploy to GitHub Pages.
> Default broker is a simulated `PaperBroker` — **paper trading only, no real money.**
>
> Conventions: one branch per task `feat/<id>`; every code task ships its own pytest;
> `ruff check .` clean; CI (lint+test) green before merge. The HTML dashboard is built by
> `python -m dashboard.build_html` from a `dashboard/template.html` (the template is NOT
> linted — keep long lines there, not in .py files). Do NOT trade/close on a price <= 0.

This plan has 3 independent workstreams. They touch mostly different files and can be
assigned to **parallel subagents**, with a short integration pass at the end.

---

## Workstream A — Make the bot actually trade (HIGHEST PRIORITY)

**Problem (diagnosed):** over ~48 hourly cloud runs the bot opened/closed nothing.
Root cause: prices come from **Binance via ccxt**, and **Binance is geo-blocked on GitHub
Actions US runners** → `app/data/prices.py:get_ohlcv` returns empty → no indicators, no
forecast → `TechnicalAgent` and `ForecastAgent` sit at 0% confidence (50% of the vote
weight is dead) → weighted conviction never reaches the action threshold. Sentiment/News
work (global APIs), which is why only those show up. Locally (Italy) Binance works, so it
looks fine on the dev machine but is data-starved in the cloud.

### A1 — Fix the market-data source (the key fix)
- Replace the single hard-coded `ccxt.binance` with a **fallback chain of exchanges that
  are reachable from US/CI**, e.g. try in order: `kraken`, `coinbase`, `kucoin`, then
  `binance` last. Return the first non-empty OHLCV.
- Map symbols per exchange (e.g. Kraken/Coinbase use `BTC/USD`, not `BTC/USDT`). Add a
  small symbol-normalisation helper; keep config assets as today and translate internally.
- Files: `app/data/prices.py` (+ tests with mocked ccxt for each fallback path).
- **Acceptance:** in a US-network environment (simulate by forcing the first exchange to
  raise), `get_ohlcv` still returns ≥150 candles from a fallback. Add a CI test.
- **Verify the real cause first:** add a one-off debug log of which exchange/source served
  the data, and confirm in a GitHub Actions run that candles are non-empty and TEC/FOR are
  no longer 0%.

### A2 — Don't let missing agents kill conviction
- In `PortfolioManagerAgent.aggregate`, **re-normalise the weighted score by the weight of
  agents that actually produced a signal** (confidence > 0), instead of dividing by the
  full weight sum. So if Technical/Forecast are missing, the remaining agents still reach
  a meaningful conviction.
- Keep a floor: if fewer than N agents have data, cap conviction (avoid acting on 1 source).
- Files: `app/agents/portfolio_manager.py` (+ tests).
- **Acceptance:** with only Sentiment present at 0.9, conviction is materially higher than
  today; with only 1 agent present, it still prefers `hold`.

### A3 — More active exits (so positions actually close)
Currently exits happen only via SL (−3%) / TP (+6%) or a consensus flip. Add:
- **Time-based exit:** close a position older than `MAX_HOLDING_HOURS` (config, default e.g.
  48h) if not already at SL/TP. Uses `opened_at` already stored on the position.
- **Trailing take-profit (optional):** once unrealised PnL ≥ +3%, move a trailing stop to
  lock in gains.
- Ensure the position-aware `close` path (already added: manager sees `current_position`)
  works end-to-end and is covered by a test.
- Files: `app/agents/risk_manager.py` or `app/orchestrator.py`, `app/config.py` (+ tests).
- **Acceptance:** a position past `MAX_HOLDING_HOURS` is closed on the next cycle; tests
  cover time-exit and consensus-flip exit.

### A4 — Tune thresholds (small)
- Re-check the open threshold (currently ~0.25 conviction / 0.15 fallback) AFTER A1+A2 are
  in, and adjust so the desk takes a few trades per day in normal conditions without
  overtrading. Document the chosen values in `GUIDA.md`.

---

## Workstream B — Mobile-friendly dashboard

**Problem:** on phones the layout is cramped (fixed multi-column grids, oversized CRT
header, tap targets small). Make `dashboard/template.html` responsive.

### B1 — Responsive layout
- Coins: 3 cols → **1 col on ≤560px**, 2 cols on ≤880px (already), 3 on desktop.
- KPIs: 4 → 2 → keep 2 on phones (or 1 if too tight).
- `.layout` already collapses to 1 col ≤880px — verify ordering on mobile is: header →
  coins → KPIs → equity → agent consensus → open → closed.
- Use `clamp()` for the CRT header font so "Multi Agent Trading Desk" fits without ugly
  wrapping on small screens (and reduce screen padding on mobile).
- Make tables scroll horizontally on narrow screens (`overflow-x:auto` wrapper) instead of
  squishing.

### B2 — Touch & readability
- Min tap target ~40px on interactive bits; bump base font slightly on mobile.
- Ensure the agent-consensus rationale text and vote chips wrap cleanly.
- Test at 360px, 390px, 768px widths.
- Files: `dashboard/template.html` only (CSS + media queries). No Python changes.
- **Acceptance:** at 390px the page has no horizontal overflow, header readable on one/two
  lines, coins stacked, tables scroll rather than overflow.

---

## Workstream C — Extend to real stocks (not just crypto)

**Feasibility: moderate, not hard.** The architecture is already asset-class agnostic
(Broker interface, agent contract, gateway). The clean path is **Alpaca** (free paper
trading account + free market data API): real paper fills, real stock data, US equities.

### C1 — Asset-class abstraction
- Add an `asset_class` notion (`crypto` | `stock`) in config and on each asset
  (e.g. `ASSETS=BTC/USDT:crypto,ETH/USDT:crypto,AAPL:stock,MSFT:stock`).
- Route data + broker by asset class.
- Files: `app/config.py`, small registry in `app/data/context.py`.

### C2 — Stock data provider
- New `app/data/stocks.py`: OHLCV for stocks via **Alpaca market data** (free) or
  `yfinance` (free, no key) as a simple fallback for prices.
- Reuse the same `compute_indicators` / Prophet pipeline (they're price-agnostic).
- Handle **market hours**: stocks trade ~Mon–Fri 09:30–16:00 ET. Skip stock cycles when
  the market is closed (config + a small calendar check); crypto keeps running 24/7.

### C3 — Stock broker
- New `app/broker/alpaca.py` implementing the `Broker` interface against **Alpaca paper
  trading** (real paper account, free API keys), OR extend `PaperBroker` to price stocks
  via `stocks.py`. Recommend Alpaca paper for realism; keep `PaperBroker` as the default
  zero-setup option.

### C4 — Agent applicability per asset class
- `OnChainAgent` (whales) and crypto Fear&Greed are **crypto-only**. For stocks, either
  disable them (re-normalise weights — ties into A2) or swap in equivalents (e.g. a stock
  news/sentiment source, VIX as "fear"). Minimum viable: disable crypto-only agents for
  stocks and let Technical/Forecast/News drive.
- Files: `app/orchestrator.py` (select agents by asset class), `app/data/sentiment.py`.

### C5 — Dashboard + docs
- Dashboard: show a small `crypto`/`stock` tag on each asset; live prices for stocks need a
  data source the browser can hit (Alpaca data API with a public-safe key, or render last
  close from the DB and skip live ticking when market closed).
- Update `GUIDA.md` and `README.md` to document multi-asset setup + Alpaca keys.

---

## Suggested subagent split
- **Subagent 1 → Workstream A** (data fix + conviction + exits). Most important; do first
  or in parallel. Files: `app/data/prices.py`, `app/agents/portfolio_manager.py`,
  `app/agents/risk_manager.py`, `app/orchestrator.py`, `app/config.py`, tests.
- **Subagent 2 → Workstream B** (mobile). File: `dashboard/template.html` only → zero
  conflict with others, fully parallel.
- **Subagent 3 → Workstream C** (stocks). New files `app/data/stocks.py`,
  `app/broker/alpaca.py` + touches `config.py`/`orchestrator.py` — coordinate the
  `config.py`/`orchestrator.py` edits with Subagent 1 (or do C after A merges).

## Global definition of done
- `ruff check .` clean, `pytest -q` green, CI green.
- A GitHub Actions run shows non-empty candles and TEC/FOR with real confidence (A1 fixed).
- The desk opens AND closes positions over a day of runs (A1–A4).
- Dashboard usable at 390px width (B).
- (If C shipped) at least one stock (e.g. AAPL) flows through the same pipeline in paper.
- Never trade/close on price ≤ 0 (keep existing guard). No secrets in code; `.env` only.

## How to run / verify locally
```
py -m pytest -q
py -m ruff check .
py -m app.run                 # one cycle
py -m dashboard.build_html    # regenerate public/index.html
```
Reset paper state to $10k (Neon SQL editor):
```sql
TRUNCATE broker_state, equity_snapshots, agent_views_log, decisions, trades RESTART IDENTITY CASCADE;
```
