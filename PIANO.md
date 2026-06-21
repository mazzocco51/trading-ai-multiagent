# PIANO PER PI — Multi-Agent AI Trading System (paper/testnet, costo €0)

> **Destinatario:** lo swarm di agenti "PI".
> **Autore del piano:** assistente di Marco (studente Ing. Informatica).
> **Obiettivo:** replicare il progetto "Trading AI Agent" della serie in 4 parti di **Simone Rizzo**, migliorandolo trasformando il **singolo agente in un sistema multi-agent**, eseguito **solo in paper/testnet** (nessun denaro reale) e con **stack 100% gratuito** (nessuna API key a pagamento).
> **Stile del piano:** ibrido — architettura + decisioni motivate ad alto livello, con **task atomici dettagliati** per le parti critiche (multi-agent, risk, exchange/broker, LLM gateway).

---

## 0. Da dove nasce il progetto (estratto dai 4 video)

Serie **"Creo il mio Trading AI Agent"** di Simone Rizzo (canale YouTube, nov 2025). Architettura ricostruita dai capitoli/descrizioni dei 4 episodi:

**Parte 1 — Da Hyperliquid a Python**
- Exchange scelto: **Hyperliquid** (DEX di perpetual crypto). Generazione API key, prime operazioni buy/sell da Python per capire flussi e latenza.
- Disegno dell'architettura dati: news, **forecasting con Prophet (Meta)**, indici/statistiche di mercato, stato del portafoglio → segnali robusti.
- Roadmap: feature engineering dei segnali, risk management, backtesting.

**Parte 2 — Dalla teoria all'Agent**
- Concetti: **Pivot Point**, **Volumi/Order book**, **Whale tracking (Whale Alert)**, impatto **News**.
- Codice delle fonti dati: **Prophet** (forecasting), **API Sentiment Fear & Greed**, **Whale Alert gratis**, **indicatori tecnici MACD/RSI**, **News feed**, **calcolo Pivot Point**.
- Problema noto: volumi/order book via **CoinGlass** (limiti del free tier).
- **Creazione del System Prompt** dell'agente.
- **Confronto LLM**: Gemini vs GPT vs Claude vs DeepSeek → strategie diverse.
- Script finale automatizzato. Prossimi passi: testnet e "pesi" (weighting dei segnali).

**Parte 3 — The Launch**
- Strategia, **timeframe** e accenno al **Multi-Agent**.
- Test pratico su **Hyperliquid Testnet**.
- Selezione modello LLM e **costi**.
- **Database Postgres** (struttura).
- Simulazione completa del workflow.
- **Deploy e automazione su Railway**.
- **Frontend dashboard** (vibe coding). Limiti operativi attuali.

**Parte 4 — Primi risultati (+6% in 7 giorni)**
- Analisi strategia short e bear market.
- **Volatilità → necessari stop loss e take profit**.
- Refactoring dashboard con AI; nuove **metriche e win rate**.
- Accuratezza forecasting su **BTC**, errori su **ETH**, crash inatteso su **SOL**.
- Confronto **forecast 1h vs dati 15m** (mismatch di timeframe = fonte di errore).
- Conclusione: il prossimo passo è proprio un **Multi-Agent System**.

> **Conclusione chiave:** lo stesso autore indica il multi-agent come evoluzione naturale. La miglioria richiesta da Marco è quindi allineata e ben motivabile nel README del portfolio.

---

## 1. Decisioni architetturali (con motivazione)

Queste decisioni recepiscono i vincoli di Marco: **€0**, **niente API key a pagamento**, **PC leggero (GPU integrata, 16 GB RAM)**, **solo cloud gratuito**, **paper/testnet sicuro**.

### 1.1 Asset & "exchange": broker astratto, default SIMULATO
- **Decisione:** introdurre un'interfaccia `Broker` con **due implementazioni**:
  1. `PaperBroker` (DEFAULT) — simulatore locale: portafoglio fittizio in DB, esecuzione ordini a prezzo di mercato reale (preso dalle API pubbliche/`ccxt`), con fee e slippage simulati. **Zero barriere, zero rischi, zero costi.**
  2. `HyperliquidTestnetBroker` (OPZIONALE) — usa l'SDK ufficiale `hyperliquid-python-sdk` contro la **testnet**.
- **Perché:** il faucet **testnet ufficiale di Hyperliquid richiede un piccolo deposito su mainnet** con lo stesso address (quindi NON è davvero €0). Con il broker astratto, Marco parte 100% gratis col simulatore e, **se** vuole, attiva la testnet in un secondo momento cambiando una variabile d'ambiente. Mostrare un **broker abstraction layer** è anche un forte segnale di buona ingegneria nel portfolio.
- **Asset di default:** BTC, ETH, SOL (gli stessi del video) su timeframe coerente (vedi §1.5).

### 1.2 LLM: gateway multi-provider 100% gratuito con fallback
- **Decisione:** un modulo `llm_gateway` che astrae il provider e fa **routing + fallback automatico** tra backend gratuiti:
  - **Google Gemini (AI Studio)** — chiave **gratuita, senza carta**. Free tier 2026: ~**15 richieste/min, 1500 richieste/giorno**, solo modelli **Flash** (i Pro sono usciti dal free tier ad aprile 2026). Marco ha già Gemini → primo provider.
  - **Groq** — free tier velocissimo (Llama/Qwen/others). Ottimo come secondo provider.
  - **OpenRouter** — espone diversi **modelli `:free`**. Terzo provider/fallback.
- **Importante (verificato):** i limiti Gemini sono **per progetto Google Cloud**, non per chiave; **NON abilitare il billing** sul progetto (azzererebbe il free tier). Generare più chiavi nello stesso progetto **non** aumenta la quota.
- **Niente Ollama locale:** con GPU integrata e 16 GB RAM sarebbe lento e fragile. Resta come nota nel README ("estendibile a inferenza locale"), ma **non** nel percorso principale.
- **Budget richieste:** poiché si gira a **cron ogni 15–60 min** su pochi asset, anche con multi-agent (5–6 chiamate/ciclo per asset) si resta **largamente dentro** i 1500 req/giorno gratuiti. Vedi §2.5 per il "request budget".

### 1.3 Persistenza: Postgres gratuito gestito
- **Decisione:** **Neon** (Postgres serverless, free tier) o **Supabase** (free). Connessione via `DATABASE_URL`. ORM con **SQLAlchemy** + migrazioni con **Alembic**.
- **Perché non SQLite:** serve un DB raggiungibile dal runner cloud (GitHub Actions) e dalla dashboard; Neon/Supabase sono gratis e gestiti.

### 1.4 Esecuzione & scheduling: GitHub Actions cron (NON Railway)
- **Decisione:** il loop di trading gira come **GitHub Actions scheduled workflow** (`cron`).
- **Perché non Railway:** **Railway ha rimosso il free tier** (solo trial $5). GitHub Actions è **gratis** (minuti gratuiti, di fatto illimitati su repo pubblici), ideale per un job a intervalli. Inoltre il repo pubblico È il portfolio.
- **Secrets:** chiavi LLM, `DATABASE_URL` ecc. nei **GitHub Actions Secrets**.
- **Nota timeframe:** il cron minimo affidabile di GitHub Actions è ~5 min (spesso ritardato). Per il progetto va benissimo (timeframe 15m–1h). Per esecuzioni più fitte in locale, fornire anche un runner `python -m app.run --loop`.

### 1.5 Timeframe coerente (lezione della Parte 4)
- **Decisione:** **allineare forecast e dati operativi sullo stesso timeframe.** Nel video il mismatch (forecast 1h vs dati 15m) causava errori. Default consigliato: **candele 1h, decisione ogni 1h** (o 15m/15m). Un solo parametro `TIMEFRAME` in config, usato ovunque.

### 1.6 Dashboard: Streamlit Community Cloud (free)
- **Decisione:** dashboard in **Streamlit**, deploy su **Streamlit Community Cloud** (gratis) leggendo dallo stesso Postgres. Alternativa statica: pagina generata e pubblicata su **GitHub Pages**.
- **Contenuti:** equity curve, posizioni aperte, storico decisioni con il *reasoning* di ogni agente, win rate, accuratezza forecast per asset, log errori.

---

## 2. Architettura Multi-Agent (il cuore della miglioria)

Si sostituisce **un singolo LLM che decide tutto** con un **team di agenti specialisti** + un **orchestratore**. Pattern: **blackboard** (lavagna condivisa) con **output strutturati JSON** e **aggregazione/risk-gating** finale.

### 2.1 Diagramma logico

```
                         +------------------------------------------+
   DATA LAYER  ------->  |              BLACKBOARD (dict/DB)        |
 (feature providers)     |  prezzi, indicatori, forecast, sentiment,|
                         |  whale, news, pivot, stato portafoglio   |
                         +------------------------------------------+
                              |        |        |        |       |
                 +------------+        |        |        |       +-----------+
                 v                     v        v        v                   v
        +---------------+   +---------------+ +--------------+ +------------+ +--------------+
        | TechnicalAgent|   | ForecastAgent | | SentimentAg. | | OnChainAg. | |  NewsAgent   |
        | MACD/RSI/Pivot|   | Prophet trend | | Fear&Greed   | | Whale flows| | headline risk|
        +-------+-------+   +------+--------+ +------+-------+ +-----+------+ +------+-------+
                |  view+score(JSON)|                 |               |               |
                +------------------+--------+--------+---------------+---------------+
                                           v
                                 +--------------------+
                                 |  PortfolioManager  |  (orchestratore/LLM)
                                 |  aggrega le view,  |
                                 |  pesa, sceglie idea|
                                 +---------+----------+
                                           v
                                 +--------------------+
                                 |    RiskManager     |  (regole deterministiche + LLM check)
                                 | sizing, SL/TP, max |
                                 | exposure, veto     |
                                 +---------+----------+
                                           v
                                 +--------------------+
                                 |   Broker (Paper /  |
                                 | HyperliquidTestnet)|
                                 +--------------------+
```

### 2.2 Ruoli degli agenti

**Specialisti (uno per "competenza", LLM-backed con output JSON):**
1. **TechnicalAgent** — input: MACD, RSI, pivot point, struttura prezzo. Output: `{bias: long|short|neutral, confidence: 0-1, rationale, key_levels}`.
2. **ForecastAgent** — input: previsione **Prophet** sul timeframe scelto + errore storico del modello per quell'asset. Output: `{expected_move_pct, direction, confidence, rationale}`. Deve **dichiarare l'incertezza** (lezione Parte 4: Prophet sbagliava su ETH/SOL).
3. **SentimentAgent** — input: **Fear & Greed Index** (API gratuita `alternative.me`) + eventuale sentiment news. Output: `{regime: fear|greed|neutral, contrarian_signal, confidence, rationale}`.
4. **OnChainAgent** — input: **Whale Alert** (movimenti grandi) e flussi. Output: `{pressure: buy|sell|neutral, notable_events, confidence, rationale}`.
5. **NewsAgent** — input: feed news (RSS/CryptoPanic free). Output: `{headline_risk: low|med|high, summary, confidence, rationale}`.

**Coordinamento:**
6. **PortfolioManagerAgent (orchestratore)** — riceve le view JSON di tutti gli specialisti + stato portafoglio, le **pesa** (pesi configurabili, "weighting" citato nei video) e produce un'**idea di trade**: `{asset, action: open_long|open_short|close|hold, target_size_pct, conviction, combined_rationale}`. Strategia di aggregazione: *weighted vote* + sintesi LLM con prompt che cita esplicitamente le view discordanti.
7. **RiskManagerAgent** — **gate finale**. Prima **regole deterministiche** (no-LLM, non aggirabili): max esposizione per asset/totale, max posizioni concorrenti, **stop loss & take profit obbligatori** (lezione Parte 4), max drawdown giornaliero (kill-switch), no overlap di posizioni opposte. Poi un **check LLM** opzionale che può solo **declassare/vetare**, mai aumentare il rischio. Output: ordine finale validato o veto motivato.

### 2.3 Perché multi-agent è meglio (da scrivere nel README)
- **Separazione delle responsabilità** → prompt più piccoli, più affidabili, meno allucinazioni.
- **Spiegabilità**: la dashboard mostra il *perché* di ogni decisione, view per view.
- **Robustezza**: una fonte rotta (es. CoinGlass) degrada un solo agente, non l'intero sistema.
- **Estendibilità**: aggiungere una competenza = aggiungere un agente.
- **Risk gating deterministico** separato dall'LLM → sicurezza.

### 2.4 Contratti dati (IMPORTANTE per la parallelizzazione)
Tutti gli agenti rispettano interfacce comuni così che PI possa svilupparli **in parallelo** senza conflitti:

```python
# app/agents/base.py
class AgentView(BaseModel):          # pydantic
    agent: str
    asset: str
    signal: str                      # es. long|short|neutral
    confidence: float                # 0..1
    rationale: str
    extra: dict = {}

class BaseAgent(ABC):
    name: str
    @abstractmethod
    def analyze(self, ctx: "MarketContext") -> AgentView: ...
```

`MarketContext` è la **lavagna**: un oggetto/`dict` con tutte le feature già calcolate dal data layer (gli agenti **non** chiamano le API dati direttamente: ricevono dati pronti → testabili e deterministici).

### 2.5 Request budget LLM (stare nel free tier)
- Chiamate/ciclo ≈ `(n_specialisti=5 + manager=1 + risk<=1) x n_asset`. Con 3 asset ≈ **18–21 chiamate/ciclo**.
- A 1 ciclo/ora → ~**500 chiamate/giorno** << 1500/giorno di Gemini free. Anche a 15m si resta gestibili distribuendo sui provider (Gemini→Groq→OpenRouter).
- **Mitigazioni:** caching delle view per dati invariati; possibilità di accorpare gli specialisti meno critici in una sola chiamata "batch" se serve risparmiare quota.

---

## 3. Stack tecnologico (tutto gratuito)

| Layer | Scelta | Perché gratis |
|---|---|---|
| Linguaggio | Python 3.11+ | — |
| Dati di mercato | `ccxt` (prezzi pubblici), API pubbliche | gratis, no key |
| Forecasting | `prophet` (Meta) | open source |
| Indicatori | `pandas-ta` (MACD, RSI, pivot) | open source |
| Sentiment | Fear & Greed `alternative.me/api` | gratis, no key |
| Whale | Whale Alert free / on-chain pubblico | free tier |
| News | RSS / CryptoPanic free | gratis |
| LLM | Gemini Flash (AI Studio) + Groq + OpenRouter `:free` | free tier, no carta |
| Validazione | `pydantic` v2 | open source |
| DB | Postgres su **Neon**/**Supabase** | free tier |
| ORM/migrazioni | SQLAlchemy + Alembic | open source |
| Scheduling/exec | **GitHub Actions cron** | gratis (repo pubblico) |
| Dashboard | **Streamlit** + Streamlit Community Cloud | gratis |
| Test | `pytest` | open source |
| Config | `pydantic-settings` + `.env` | open source |
| Broker reale (opz.) | `hyperliquid-python-sdk` (testnet) | gratis |

---

## 4. Struttura del repository

```
trading-ai-multiagent/
├── README.md                  # storytelling portfolio + architettura + disclaimer
├── ARCHITECTURE.md            # diagrammi, scelte, multi-agent
├── pyproject.toml / requirements.txt
├── .env.example
├── .github/workflows/
│   ├── trade-loop.yml         # cron del loop di trading
│   └── ci.yml                 # lint + pytest su ogni push
├── app/
│   ├── config.py              # settings (env): TIMEFRAME, ASSETS, BROKER, provider...
│   ├── run.py                 # entrypoint: un ciclo o --loop
│   ├── data/                  # feature providers (NON LLM)
│   │   ├── prices.py          # ccxt OHLCV
│   │   ├── indicators.py      # MACD/RSI/pivot (pandas-ta)
│   │   ├── forecast.py        # Prophet + tracking errore
│   │   ├── sentiment.py       # Fear & Greed
│   │   ├── whale.py           # Whale Alert
│   │   ├── news.py            # RSS/CryptoPanic
│   │   └── context.py         # costruisce MarketContext (la lavagna)
│   ├── llm/
│   │   ├── gateway.py         # router multi-provider + fallback + retry
│   │   └── providers/         # gemini.py, groq.py, openrouter.py
│   ├── agents/
│   │   ├── base.py            # BaseAgent, AgentView
│   │   ├── technical.py
│   │   ├── forecast_agent.py
│   │   ├── sentiment_agent.py
│   │   ├── onchain.py
│   │   ├── news_agent.py
│   │   ├── portfolio_manager.py
│   │   └── risk_manager.py
│   ├── broker/
│   │   ├── base.py            # interfaccia Broker
│   │   ├── paper.py           # PaperBroker (default)
│   │   └── hyperliquid.py     # testnet (opzionale)
│   ├── persistence/
│   │   ├── models.py          # tabelle: trades, decisions, agent_views, equity, forecasts
│   │   └── repo.py
│   └── orchestrator.py        # pipeline: context → agents → manager → risk → broker → DB
├── dashboard/
│   └── app.py                 # Streamlit
├── prompts/                   # system prompt di ogni agente (file .md versionati)
└── tests/                     # unit + integration (broker simulato, parser JSON)
```

---

## 5. Roadmap a milestone con task atomici (per lo swarm PI)

> Convenzioni per PI: ogni task ha **ID**, **dipendenze**, **file**, **criterio di accettazione (DoD)**, **comando di verifica**. I task con lo stesso prefisso milestone e **senza dipendenze incrociate** possono essere svolti **in parallelo**. Ogni task deve includere i propri **test pytest**. Branch per task `feat/<ID>`; merge solo con CI verde.

### M0 — Setup (sequenziale, blocca tutto)
- **T0.1** Init repo, `pyproject`/`requirements`, struttura cartelle, `pre-commit` (ruff+black). DoD: `pip install -e .` ok, `ruff check` pulito.
- **T0.2** `app/config.py` con `pydantic-settings`: `ASSETS`, `TIMEFRAME`, `BROKER=paper|hyperliquid_testnet`, `LLM_PROVIDER_ORDER`, chiavi, `DATABASE_URL`, limiti rischio. `.env.example`. DoD: import config senza errori, default sensati.
- **T0.3** `ci.yml` (ruff + pytest). DoD: workflow verde su push.

### M1 — Data layer / feature providers (parallelizzabile, dipende da M0)
Ogni provider espone una funzione pura `get_*(asset, timeframe) -> dict/DataFrame` + test con risposta mockata.
- **T1.1** `data/prices.py`: OHLCV via `ccxt` (exchange pubblico, no key). DoD: ritorna DataFrame con N candele.
- **T1.2** `data/indicators.py`: MACD, RSI, **pivot point** (formula classica P=(H+L+C)/3, R1/S1...). DoD: valori coerenti su serie nota.
- **T1.3** `data/forecast.py`: **Prophet** addestrato sulle ultime candele → previsione orizzonte = TIMEFRAME; salva anche **errore vs realizzato** per asset. DoD: ritorna `expected_move_pct` + metrica errore.
- **T1.4** `data/sentiment.py`: **Fear & Greed** da `alternative.me`. DoD: ritorna indice 0–100 + label.
- **T1.5** `data/whale.py`: Whale Alert / flussi on-chain pubblici (gestire assenza key con degradazione graceful). DoD: lista eventi o vuoto, mai eccezione.
- **T1.6** `data/news.py`: RSS/CryptoPanic free → headline recenti. DoD: lista titoli con timestamp.
- **T1.7** `data/context.py`: assembla tutto in `MarketContext` (la lavagna). DoD: oggetto pydantic completo per ogni asset; campi mancanti = `None` con flag `degraded`.

### M2 — Broker layer (parallelo a M1, dipende da M0) — CRITICO
- **T2.1** `broker/base.py`: interfaccia `Broker` (`get_balance`, `get_positions`, `place_order(side, size, sl, tp)`, `close`, `mark_price`). DoD: ABC + tipi.
- **T2.2** `broker/paper.py` (**default**): portafoglio simulato in DB, prezzo da `prices.py`, fee+slippage configurabili, gestione SL/TP, P&L. DoD: test end-to-end "apri long → prezzo sale → TP → equity aumenta".
- **T2.3** `broker/hyperliquid.py` (**opzionale**): wrapper su `hyperliquid-python-sdk` **testnet**; stessa interfaccia. DoD: con env testnet, `get_balance` risponde (skippato in CI senza credenziali).

### M3 — LLM gateway (parallelo a M1/M2, dipende da M0) — CRITICO
- **T3.1** `llm/providers/*`: client per **Gemini**, **Groq**, **OpenRouter** con metodo comune `complete(system, user, json_schema) -> dict`. DoD: ognuno parsa JSON valido (test con mock HTTP).
- **T3.2** `llm/gateway.py`: **router con ordine di preferenza + fallback** su rate-limit/errore, **retry con backoff**, **logging del provider usato e dei token**, **enforcement output JSON** (validazione pydantic + un retry "ripara JSON"). DoD: se il primo provider lancia 429, passa al successivo; test simula 429.
- **T3.3** Budget/guard: contatore richieste giornaliero per stare nel free tier; se quota esaurita → degrada (salta agenti non critici). DoD: test del contatore e della soglia.

### M4 — Agenti (dipende da M1 context + M3 gateway) — CRITICO, parallelizzabile per agente
Per ogni agente: system prompt in `prompts/`, classe in `app/agents/`, output `AgentView` validato, test con `MarketContext` fisso + LLM mockato.
- **T4.1** `agents/base.py`: `BaseAgent` + `AgentView` (pydantic). DoD: contratto stabile (blocca T4.2–T4.7).
- **T4.2** TechnicalAgent. **T4.3** ForecastAgent (deve esplicitare incertezza). **T4.4** SentimentAgent (logica contrarian su F&G). **T4.5** OnChainAgent. **T4.6** NewsAgent. — *paralleli tra loro*. DoD ciascuno: dato un context, ritorna `AgentView` valida e deterministica con LLM mockato.
- **T4.7** PortfolioManagerAgent: aggrega le view (weighted vote + sintesi LLM), pesi da config. DoD: con view discordanti note, output `action` atteso; rationale cita i disaccordi.

### M5 — Risk Manager (dipende da T4.7 + M2) — CRITICO
- **T5.1** `agents/risk_manager.py`: regole **deterministiche** prima di tutto — **SL e TP obbligatori**, max esposizione per asset/totale, max posizioni, **max drawdown giornaliero (kill-switch)**, no posizioni opposte sovrapposte, sizing (es. % equity per conviction). DoD: test parametrici: ordini che violano i limiti vengono **vetati**; sizing corretto.
- **T5.2** Check LLM opzionale che può **solo ridurre** il rischio (mai aumentarlo). DoD: test che un "veto" LLM blocca, un "ok" non aumenta size.

### M6 — Persistenza & orchestrazione (dipende da M1–M5)
- **T6.1** `persistence/models.py` + Alembic: tabelle `equity`, `trades`, `decisions`, `agent_views`, `forecasts(error)`. DoD: `alembic upgrade head` crea lo schema su Neon.
- **T6.2** `orchestrator.py`: pipeline completa context → agenti → manager → risk → broker → **persistenza di TUTTO** (anche le view, per spiegabilità). DoD: un ciclo completo su PaperBroker scrive righe coerenti nel DB.
- **T6.3** `run.py` + `.github/workflows/trade-loop.yml` (cron). DoD: workflow esegue un ciclo end-to-end con i Secrets; log leggibili.

### M7 — Dashboard (dipende da M6)
- **T7.1** `dashboard/app.py` (Streamlit): equity curve, posizioni, **storico decisioni con reasoning per-agente**, win rate, **accuratezza forecast per asset**, log errori/degradazioni. DoD: gira in locale leggendo dal DB.
- **T7.2** Deploy su Streamlit Community Cloud (Secrets = `DATABASE_URL` read-only). DoD: URL pubblico nel README.

### M8 — Backtest & valutazione (dipende da M1/M2/M4, parallelo a M7)
- **T8.1** `backtest`: replay storico su dati OHLCV, stesso orchestrator con LLM mockabile/cache, metriche (P&L, win rate, max DD, Sharpe semplificato, accuratezza forecast). DoD: report riproducibile su periodo fisso.
- **T8.2** Eval qualità agenti: dataset di scenari → controlli che le `AgentView` siano sensate (es. F&G estremo → segnale contrarian). DoD: suite verde.

### M9 — Polish portfolio (dipende da tutto)
- **T9.1** `README.md`: problema, **architettura multi-agent con diagramma**, scelte zero-cost, come girarlo, screenshot dashboard, **risultati backtest**, **disclaimer educativo / niente consigli finanziari / solo paper**, crediti alla serie di Simone Rizzo come ispirazione.
- **T9.2** `ARCHITECTURE.md` + diagrammi (Mermaid). DoD: rendering corretto su GitHub.
- **T9.3** Demo: GIF/screenshot, eventuale badge CI. DoD: repo "presentabile" a un recruiter.

---

## 6. Definition of Done globale
- `ruff` pulito, `pytest` verde in CI su ogni push.
- **Nessun denaro reale** in alcun percorso di default; `BROKER=paper` di default; testnet dietro env esplicito.
- **Nessuna API key a pagamento**; il sistema funziona col solo free tier (degradazione graceful se una fonte/provider manca).
- Ogni decisione è **persistita e spiegabile** (view per agente + rationale del manager + esito risk).
- SL/TP **sempre** presenti su ogni posizione aperta.
- README con disclaimer e diagramma multi-agent.

## 7. Rischi e mitigazioni
- **Quota LLM free esaurita** → router multi-provider + budget counter + accorpamento agenti non critici.
- **Fonte dati rotta (es. CoinGlass/order book)** → `degraded=True`, l'agente relativo si astiene, gli altri proseguono.
- **Prophet impreciso (ETH/SOL nel video)** → ForecastAgent dichiara incertezza; il manager pesa di meno i forecast a errore storico alto.
- **Mismatch di timeframe** → un solo parametro `TIMEFRAME` ovunque (lezione Parte 4).
- **Volatilità / drawdown** → SL/TP obbligatori + kill-switch giornaliero nel RiskManager.
- **Faucet testnet a pagamento implicito** → default su PaperBroker, testnet solo opzionale.
- **Secrets** → solo in GitHub/Streamlit Secrets, **mai** committati; `.env` in `.gitignore`.

## 8. Istruzioni operative per lo swarm PI
1. Eseguire **M0** per primo (sequenziale). Poi **M1, M2, M3 in parallelo**.
2. In M4 fare **T4.1 per primo** (contratto), poi T4.2–T4.6 in parallelo, infine T4.7.
3. **M5 dopo T4.7 + M2.** Poi M6 (sequenziale), poi M7/M8 in parallelo, infine M9.
4. Un branch per task `feat/<ID>`; PR piccola con test; merge **solo** con CI verde.
5. **Niente segreti nel codice.** Tutto via env. **Nessun ordine reale** in test/CI (usare sempre PaperBroker mockato).
6. Ogni agente LLM: prompt versionato in `prompts/`, output **JSON validato pydantic**, test con LLM mockato per determinismo.
7. Definire i **pesi** del PortfolioManager in config (riproducibilità + tuning come nei "pesi" citati nei video).

---

### Appendice A — Setup chiavi gratuite (per Marco)
- **Gemini:** Google AI Studio → "Get API key". Free, senza carta. **NON abilitare il billing** sul progetto.
- **Groq:** console.groq.com → API key gratuita.
- **OpenRouter:** openrouter.ai → key; usare modelli con suffisso `:free`.
- **Neon/Supabase:** crea progetto Postgres free → copia `DATABASE_URL`.
- **GitHub:** repo **pubblico** (è il portfolio) → Settings → Secrets and variables → Actions.

### Appendice B — Fonti video (ispirazione)
- Parte 1 — *Da Hyperliquid a Python*: https://youtu.be/tzsRaNytHZ0
- Parte 2 — *Dalla teoria all'Agent*: https://youtu.be/_CpICOumgBc
- Parte 3 — *The Launch*: https://youtu.be/-6jRLa-zjeg
- Parte 4 — *Primi risultati +6% / Multi-Agent*: https://youtu.be/U7V_QSRJfZI

> **Disclaimer:** progetto educativo per portfolio. Nessun consiglio finanziario. Esecuzione solo in paper/testnet.
