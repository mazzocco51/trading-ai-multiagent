# Guida completa — Trading AI Multi-Agent

> Documento di dettaglio. Per la panoramica veloce vedi il [README](README.md).
> Pensato per essere comprensibile anche a chi programma ma sa poco di trading/cripto.
> **Solo paper trading. Nessun soldo reale. Stack 100% gratuito.**

---

## 1. Cos'è, in una frase

Un piccolo sistema distribuito in cui **un team di agenti AI** analizza il mercato in modo
indipendente, vota, e un livello di rischio **deterministico** trasforma quel voto in
operazioni **simulate** (paper). Gira da solo nel cloud, a costo zero. Default: **crypto**
(BTC, ETH, SOL); supporto **azioni** USA opzionale.

L'idea nasce dalla serie YouTube di **Simone Rizzo** *"Creo il mio Trading AI Agent"*, che
costruisce **un solo** agente. Qui la novità è il **team di agenti** — il "prossimo passo"
suggerito alla fine della serie.

---

## 2. Come funziona un ciclo (passo per passo)

```
1. Raccoglie i dati di mercato     → prezzi, indicatori, previsione, umore, news
2. Costruisce la "lavagna"         → MarketContext (un riassunto per ogni asset)
3. Seleziona gli agenti            → per crypto tutti e 5; per azioni esclude on-chain/sentiment
4. Gli agenti leggono e votano     → ognuno: direzione + quanto è sicuro (via LLM)
5. Il Gestore aggrega i voti       → li pesa e propone un'idea (apri/chiudi/fermo)
6. Il Risk Manager controlla       → regole fisse: SL/TP, limiti, kill-switch, uscita a tempo
7. Esegue sul broker simulato      → apre/chiude posizioni paper
8. Salva tutto su Postgres (Neon)  → decisioni, voti, equity, stato del portafoglio
9. Ricostruisce e pubblica la dashboard → HTML statica su GitHub Pages
```

Ad ogni ciclo il programma stampa anche una **spiegazione in italiano** di cosa è successo.

---

## 3. I cinque agenti specialisti

Ognuno guarda **solo il suo pezzo** (prompt corto = meno errori) e restituisce un'opinione
comparabile: `long / short / neutral` + confidenza + motivazione.

| Agente | Cosa guarda | Peso default | In parole semplici |
|---|---|---|---|
| **Tecnico** | MACD, RSI, Pivot | **0.35** | Momentum/struttura del grafico recente |
| **Previsione** | Modello Prophet | 0.20 | Stima statistica del prossimo movimento + incertezza |
| **Sentiment** | Fear & Greed Index | 0.20 | Umore del mercato; *contrarian* agli estremi |
| **On-chain** | Whale Alert | 0.15 | Le "balene" comprano o vendono (solo crypto) |
| **Notizie** | RSS / headline | **0.10** | Rischio dalle notizie (fonte rumorosa → peso basso) |

Per le **azioni**, gli agenti solo-crypto (on-chain, Fear & Greed) vengono **esclusi
automaticamente** e i pesi ri-normalizzati (vedi `app/agents/agent_selector.py`).

---

## 4. Come si decide (la matematica del voto)

Il **Gestore (PortfolioManager)** pesa ogni voto per **peso dell'agente × confidenza**, dove
rialzo = +1, ribasso = −1, **neutro = 0**, poi normalizza. **Importante:** la normalizzazione
avviene sul **peso degli agenti che hanno realmente prodotto un segnale** (`active_weight`),
non sul totale. Così se Technical/Forecast mancano (dati assenti), gli altri raggiungono
comunque una conviction sensata invece di restare schiacciati a zero.

**Esempio.** Tecnico, Previsione e Sentiment dicono RIALZO al 70%; On-chain e Notizie neutri:

```
Tecnico:    +1 × 0,70 × 0,35 = +0,245
Previsione: +1 × 0,70 × 0,20 = +0,140
Sentiment:  +1 × 0,70 × 0,20 = +0,140
On-chain:    0 (neutro)
Notizie:     0 (neutro)
peso attivo = 0,35+0,20+0,20 = 0,75
score normalizzato = 0,525 / 0,75 ≈ 0,70
```

Il Gestore apre quando lo score è chiaramente direzionale (soglia ~0,25); sotto, resta fermo.
È prudenza voluta: meglio non operare che operare su un segnale debole.

> Nota sui pesi: i pesi fissi sono un compromesso. La letteratura suggerisce che pesi
> **adattivi al regime** (news su in fasi volatili, tecnici su in mercati stabili) funzionano
> meglio — possibile estensione futura.

---

## 5. La spiegazione in chiaro

Ad ogni ciclo, per ogni asset, il bot stampa un blocco come questo:

```
================================================================
📊 ETH/USDT — prezzo attuale: 1,715.06
----------------------------------------------------------------
Cosa pensano i 5 analisti:
  • Tecnico     → RIALZO  (sicurezza  70%): gli indicatori puntano al rialzo
  • Previsione  → RIALZO  (sicurezza  70%): il modello prevede il prezzo in salita
  • Sentiment   → RIALZO  (sicurezza  70%): mercato in 'paura' → possibile rimbalzo
  • On-chain    → NEUTRO  (sicurezza  10%): nessun grande movimento di 'balene'
  • Notizie     → NEUTRO  (sicurezza  10%): nessuna notizia rilevante

Voti: 3 RIALZO · 0 RIBASSO · 2 NEUTRO  → convinzione pesata 70%
  🟢 APERTA posizione LONG su ETH/USDT.
================================================================
```

La stessa motivazione, per ogni agente, è visibile anche in dashboard (passando il mouse).

---

## 6. Il Risk Manager (la sicurezza)

È **codice Python deterministico**, separato dall'AI: l'LLM non può "convincerlo" ad alzare il
rischio. Regole sempre applicate:

- **Stop-loss e Take-profit obbligatori** su ogni posizione (default: SL −3%, TP +6%).
- Max **20%** del capitale per posizione, max **80%** di esposizione totale, max **5** aperte.
- **Kill-switch**: se la perdita giornaliera supera il **5%**, blocca ogni nuova apertura.
- **Uscita a tempo**: chiude una posizione più vecchia di `max_holding_hours` (default 48h).
- **Niente prezzi sporchi**: con prezzo ≤ 0 non apre né chiude (evita P&L finti).

Il Gestore è anche **position-aware**: sa cosa è aperto e può **chiudere** su ribaltamento del
consenso o per prendere profitto, non solo via SL/TP.

---

## 7. Il "cervello" gratuito (LLM Gateway)

Gli agenti chiamano un LLM senza spendere nulla. Il gateway prova i provider in ordine con
**fallback automatico** e un **budget giornaliero** per restare nel free tier:

1. **Gemini 2.5 Flash** (Google AI Studio) — gratis, ~1500 richieste/giorno.
2. **Groq** (Llama) — subentra quando Gemini va in rate-limit.
3. **OpenRouter** (modelli `:free`) — ultima rete di sicurezza.

Se tutti falliscono, il Gestore usa una **logica a regole** come ultima risorsa: non si ferma mai.

---

## 8. Il livello dati (resiliente)

- **Crypto**: OHLCV via `ccxt` con **catena di fallback** `kraken → coinbase → kucoin →
  binance`. Serve perché **Binance è geo-bloccata sui runner GitHub (USA)**: con il fallback
  il bot ottiene i prezzi anche nel cloud. (`app/data/prices.py`)
- **Azioni** (opzionale): OHLCV via **yfinance** + orari di mercato. (`app/data/stocks.py`)
- Indicatori (MACD/RSI/pivot), forecast (Prophet), Fear & Greed, whale, news — ognuno **degrada
  con grazia**: una fonte rotta indebolisce un solo agente, non l'intero ciclo.

---

## 9. Perché multi-agent invece di un solo agente

| Problema con un agente unico | Soluzione qui |
|---|---|
| Un prompt gigante deve ragionare su tutto → più allucinazioni | Ogni specialista riceve solo i suoi dati, prompt corto |
| Una fonte rotta corrompe tutta la decisione | Degrada **un solo** agente; gli altri proseguono |
| L'LLM è anche il risk manager → si può "convincere" | Le regole di rischio sono Python puro, separate dall'LLM |
| Aggiungere un segnale = riscrivere il prompt monolitico | Aggiungere una capacità = aggiungere una classe agente |

**Bonus**: un unico parametro `TIMEFRAME` usato da tutti i componenti elimina il bug di
*timeframe mismatch* (Prophet su 1h vs decisioni su 15m) della serie originale.

---

## 10. Setup completo

### Prerequisiti
- Python 3.11+ · Git

### Installazione
```bash
git clone https://github.com/mazzocco51/trading-ai-multiagent
cd trading-ai-multiagent
pip install -e ".[all]"
```

### Chiavi API gratuite
Per partire basta **una** chiave LLM (Gemini). Le altre sono opzionali.

| Servizio | Dove | Note |
|---|---|---|
| **Gemini** (LLM principale) | [aistudio.google.com](https://aistudio.google.com) → "Get API key" | Gratis, niente carta. **Non** abilitare il billing |
| **Groq** (fallback) | [console.groq.com](https://console.groq.com) | Free tier |
| **OpenRouter** (fallback) | [openrouter.ai](https://openrouter.ai) | Modelli `:free` |
| **Neon** (Postgres) | [neon.tech](https://neon.tech) | Serve per il 24/7 (stato persistente) |
| Whale Alert / CryptoPanic | rispettivi siti | Opzionali — il bot degrada senza |

### File `.env`
```env
GEMINI_API_KEY=la_tua_chiave
GEMINI_MODEL=gemini-2.5-flash
# GROQ_API_KEY=...            (consigliata come fallback)
# DATABASE_URL=...            (vuoto = SQLite locale; Neon per il cloud)
# ASSETS=BTC/USDT,ETH/USDT,SOL/USDT,AAPL   (aggiungi titoli se vuoi)
# ASSET_CLASSES=AAPL:stock                 (marca i titoli come 'stock')
```

---

## 11. Eseguire

```bash
python -m app.run                 # un singolo ciclo
python -m app.run --loop --interval 3600   # loop continuo sul tuo PC
```

## 12. Dashboard

```bash
python -m dashboard.build_html    # genera public/index.html (poi aprilo nel browser)
```
È una pagina **HTML statica autonoma**: prende i dati del bot dal DB (baked al build) e i
prezzi live dal browser. Mostra: equity curve **+ benchmark BTC buy & hold (alpha vs mercato)**,
KPI (**net P&L realizzato, profit factor**, equity, cassa), posizioni aperte con P&L live,
ultime 50 chiuse, e il **consenso degli agenti con il ragionamento** di ognuno.

Esiste anche una vecchia dashboard **Streamlit** (`dashboard/app.py`) come alternativa locale.

## 13. Backtest e risultati

### Come funziona
```bash
# singola finestra
python -m app.backtest --start 2024-01-01 --end 2024-06-30
# confronto filtro di trend ON vs OFF su una finestra
python -m app.backtest --start 2022-01-01 --end 2022-06-30 --compare-trend-filter
```
Il backtest rigioca dati storici (OHLCV via ccxt) nello **stesso orchestrator** del live e
salva un report in `reports/*.{md,json}` con: PnL%, rendimento buy & hold, **alpha**, Sharpe
(annualizzato), max drawdown, win rate, profit factor, n. trade.

**Modalità deterministica.** In backtest l'LLM è disattivato: ogni agente deriva il proprio
`AgentView` **direttamente dai dati** (technical da MACD/RSI/pivot, forecast da Prophet,
sentiment da F&G, ecc.) e il PortfolioManager aggrega via fallback a regole. Questo rende il
backtest veloce, deterministico e riproducibile (l'LLM serve in live, non per valutare la
strategia). Il forecast Prophet è **throttlato** (`forecast_refit_every`, default 24 barre):
ri-allenarlo ad ogni barra oraria renderebbe il backtest impraticabile (~4000 fit).

### Cosa dicono i numeri (onestamente)

Backtest su tre regimi di mercato (BTC/USDT, 1h, modalità deterministica):

| Finestra | Filtro | PnL% | Buy&Hold% | Alpha | Sharpe | MaxDD% | Win% | Profit factor | N trade |
|---|---|---|---|---|---|---|---|---|---|
| Bear 22 H1 | **ON** | −5.10 | −57.05 | **+51.95** | 1.38 | 17.1 | 36.4 | **1.02** | 184 |
| Bear 22 H1 | OFF | −5.17 | −57.05 | +51.88 | 0.87 | 15.8 | 30.9 | 0.76 | 97 |
| Bull 23→24 | **ON** | −6.53 | +158.87 | −165.40 | 1.57 | 13.6 | 29.5 | 0.99 | 254 |
| Bull 23→24 | OFF | −7.83 | +158.87 | −166.70 | 1.60 | 14.4 | 33.0 | 0.95 | 303 |
| Choppy 24 | **ON** | −0.14 | +50.00 | −50.14 | 1.66 | 13.3 | 35.3 | 0.93 | 153 |
| Choppy 24 | OFF | −7.92 | +50.00 | −57.92 | 1.65 | 13.6 | 30.2 | 0.92 | 192 |

**Interpretazione:**
- **È una strategia difensiva.** Perde poco in ogni regime (−5% / −6,5% / ~0%) e l'unico alpha
  positivo è nel **crash** (Bear: −5% mentre BTC fa −57%). L'edge è la **protezione al ribasso**
  (kill-switch + filtro di trend + stop obbligatori), non battere il mercato.
- **In bull sottoperforma** il buy & hold di molto: per scelta sta a bassa esposizione e viene
  cappata dal kill-switch → non cavalca i rialzi.
- **Il filtro di trend (A) migliora la qualità in tutte le finestre**: profit factor e win rate
  più alti ovunque (es. Bear 0.76→1.02), e PnL migliore in tutte e tre. È un miglioramento
  robusto, non da una singola finestra.
- **Net-negativo ovunque**: profit factor ~0,93–1,02 = sostanzialmente pari lordo, poi le fee
  (100–300 trade) lo spingono in leggera perdita. Non è una macchina da soldi — ed è giusto
  dichiararlo.

> Caveat metodologici: modalità deterministica (≠ comportamento LLM live), poche finestre, una
> sola coppia (BTC). Il backtest è **illustrativo del comportamento**, non una promessa di
> performance. La finestra "Choppy" 2024 in realtà ha fatto +50% b&h (non perfettamente laterale).

---

## 14. Deploy 24/7 (gratis)

Il workflow `.github/workflows/trade-loop.yml` esegue un ciclo, salva su Neon e **ripubblica
la dashboard su GitHub Pages**.

**Setup una tantum:**
1. Crea un database **Neon** gratuito e copia la `DATABASE_URL`. Serve perché su GitHub Actions
   il file SQLite non persiste tra i run — con Neon lo stato (equity, posizioni) continua.
2. GitHub → **Settings → Secrets and variables → Actions**: aggiungi `GEMINI_API_KEY`,
   `GROQ_API_KEY`, `DATABASE_URL`.
3. **Settings → Pages → Source: GitHub Actions**.

**Scheduling affidabile.** I cron di GitHub Actions sul free tier sono *best-effort* (spesso
saltati). Per esecuzioni puntuali si usa un **trigger esterno gratuito** (cron-job.org) che
chiama l'API `workflow_dispatch` di GitHub ogni ora — i dispatch non vengono throttlati come i
cron schedulati.

---

## 15. Struttura del progetto

```
app/
├── config.py          # impostazioni (.env), pesi agenti, limiti rischio
├── run.py             # entrypoint — un ciclo o --loop; carica/salva stato broker
├── orchestrator.py    # pipeline completa di un ciclo (routing per asset class)
├── explain.py         # spiegazione in italiano di ogni decisione
├── data/              # prices (multi-exchange), stocks (yfinance), indicators,
│                      #   forecast, sentiment, whale, news, context, asset_registry
├── agents/            # 5 specialisti + agent_selector + PortfolioManager + RiskManager
├── llm/               # gateway multi-provider con fallback + budget
├── broker/            # base, paper (crypto), paper_stock (azioni), hyperliquid (opz.)
└── persistence/       # modelli SQLAlchemy + repository (incl. stato broker)
dashboard/             # template.html + build_html.py (HTML statica) + app.py (Streamlit)
prompts/               # system prompt di ogni agente (.md versionati)
tests/                 # pytest (~60 test), sempre su broker paper
.github/workflows/     # ci.yml (lint+test) + trade-loop.yml (ciclo + deploy Pages)
```

---

## 16. Stack tecnologico (tutto gratuito)

Python · ccxt · yfinance · Prophet · pandas · pydantic · SQLAlchemy + Neon · Chart.js (dashboard
statica) + Streamlit · Gemini / Groq / OpenRouter (free tier) · GitHub Actions + GitHub Pages ·
pytest · ruff.

---

## 17. Disclaimer

Progetto **educativo / portfolio**. Nessun soldo reale movimentato (broker di default = paper,
saldo virtuale $10.000). Niente di tutto questo è consiglio finanziario. I mercati sono volatili;
le performance simulate passate non predicono quelle future.

## 18. Crediti

Ispirato alla serie *"Creo il mio Trading AI Agent"* di Simone Rizzo:
[Parte 1](https://youtu.be/tzsRaNytHZ0) · [Parte 2](https://youtu.be/_CpICOumgBc) · [Parte 3](https://youtu.be/-6jRLa-zjeg) · [Parte 4](https://youtu.be/U7V_QSRJfZI)
