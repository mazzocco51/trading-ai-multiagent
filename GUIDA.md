# Guida completa — Trading AI Multi-Agent

> Documento di dettaglio. Per la panoramica veloce vedi il [README](README.md).
> Pensato per essere comprensibile anche a chi programma ma sa poco di trading/cripto.
> **Solo paper trading. Nessun soldo reale. Stack 100% gratuito.**

---

## 1. Cos'è, in una frase

Un sistema che ogni ora guarda BTC, ETH e SOL, fa "ragionare" cinque agenti AI specializzati, mette insieme i loro pareri, decide se comprare/vendere/stare fermo, ed esegue l'operazione su un portafoglio **finto** (paper trading). Tutto con strumenti gratuiti.

L'idea nasce dalla serie YouTube di **Simone Rizzo** *"Creo il mio Trading AI Agent"*, che costruisce **un solo** agente. Qui la novità è trasformarlo in un **team di agenti** — che è proprio il "prossimo passo" suggerito alla fine della serie.

---

## 2. Come funziona un ciclo (passo per passo)

```
1. Raccoglie i dati di mercato     → prezzi, indicatori, previsioni, umore, news
2. Costruisce la "lavagna"         → MarketContext (un riassunto per ogni asset)
3. 5 agenti la leggono e votano    → ognuno dà: direzione + quanto è sicuro
4. Il Gestore aggrega i voti       → li pesa e propone un'idea (compra/vendi/fermo)
5. Il Risk Manager controlla       → regole fisse di sicurezza (stop-loss, limiti)
6. Esegue sul portafoglio finto    → apre/chiude posizioni simulate
7. Salva tutto nel database        → decisioni, voti, equity → visibili in dashboard
```

Ad ogni ciclo il programma stampa anche una **spiegazione in italiano** di cosa è successo e perché (vedi sezione 5).

---

## 3. I cinque agenti specialisti

Ognuno guarda **solo il suo pezzo** di realtà (prompt corto e focalizzato = meno errori).

| Agente | Cosa guarda | In parole semplici |
|---|---|---|
| **Tecnico** | MACD, RSI, Pivot Point | Pattern matematici sul grafico del prezzo |
| **Previsione** | Modello Prophet (Meta) | Una stima statistica di dove andrà il prezzo |
| **Sentiment** | Fear & Greed Index (0–100) | L'umore del mercato. Logica *contrarian*: "paura" estrema spesso = occasione di acquisto |
| **On-chain** | Whale Alert | Movimenti dei grandi portafogli ("balene") |
| **Notizie** | Feed RSS / CryptoPanic | Rischio legato alle notizie recenti |

Ogni agente produce una "view" strutturata: `{ direzione: long/short/neutral, sicurezza: 0–100%, motivazione }`.

---

## 4. Come si decide (la matematica del voto)

Il **Gestore (PortfolioManager)** non fa una media semplice: pesa ogni voto per **importanza dell'agente × sicurezza**, dove rialzo = +1, ribasso = −1, **neutro = 0**.

Pesi di default (modificabili in `.env`):

| Agente | Peso |
|---|---|
| Tecnico | 30% |
| Previsione | 20% |
| Sentiment | 20% |
| On-chain | 15% |
| Notizie | 15% |

**Esempio reale.** Tecnico, Previsione e Sentiment dicono RIALZO al 70%; On-chain e Notizie sono neutri:

```
Tecnico:    +1 × 0,70 × 0,30 = +0,21
Previsione: +1 × 0,70 × 0,20 = +0,14
Sentiment:  +1 × 0,70 × 0,20 = +0,14
On-chain:    0 × 0,15        =  0
Notizie:     0 × 0,15        =  0
----------------------------------------
Punteggio pesato = 0,49  (scala da −1 a +1)
```

Due cose abbassano il punteggio: la sicurezza è 70% (non 100%) e i due neutri "occupano" il 30% del peso senza spingere. Se anche On-chain e Notizie fossero stati rialzisti, il punteggio sarebbe salito a ~0,70.

Il Gestore apre una posizione quando il punteggio è chiaramente direzionale (soglia ~0,25); sotto, resta fermo. È prudenza voluta: meglio non operare che operare su un segnale debole.

---

## 5. La spiegazione in chiaro

Ad ogni ciclo, per ogni asset, il bot stampa un blocco come questo:

```
================================================================
📊 ETH/USDT — prezzo attuale: 1,715.06
----------------------------------------------------------------
Cosa pensano i 5 analisti:
  • Tecnico     → RIALZO  (sicurezza  70%): gli indicatori tecnici puntano al rialzo
  • Previsione  → RIALZO  (sicurezza  70%): il modello statistico prevede il prezzo in salita
  • Sentiment   → RIALZO  (sicurezza  70%): mercato in 'paura' → possibile rimbalzo
  • On-chain    → NEUTRO  (sicurezza  10%): nessun grande movimento di 'balene'
  • Notizie     → NEUTRO  (sicurezza  10%): nessuna notizia rilevante

Voti: 3 RIALZO · 0 RIBASSO · 2 NEUTRO  → convinzione pesata 49%
  🟢 APERTA posizione LONG su ETH/USDT.
     Quanto: 10% del capitale.
     Stop-loss a 1,663.6 (esce in perdita ~3% se va male).
     Take-profit a 1,818.0 (incassa il guadagno ~6% se va bene).
================================================================
```

---

## 6. Il Risk Manager (la sicurezza)

È **codice Python deterministico**, separato dall'AI: l'LLM non può "convincerlo" ad alzare il rischio. Regole sempre applicate:

- **Stop-loss e Take-profit obbligatori** su ogni posizione (default: SL −3%, TP +6%).
- Max **20%** del capitale per singola posizione.
- Max **80%** di esposizione totale.
- Max **5** posizioni aperte insieme.
- **Kill-switch**: se la perdita giornaliera supera il **5%**, blocca ogni nuova apertura.

---

## 7. Il "cervello" gratuito (LLM Gateway)

Gli agenti chiamano un LLM, ma senza spendere nulla. Il gateway prova i provider in ordine e **fa fallback automatico** se uno è esaurito:

1. **Gemini 2.5 Flash** (Google AI Studio) — gratis, ~1500 richieste/giorno.
2. **Groq** (Llama) — free tier velocissimo, subentra quando Gemini va in rate-limit.
3. **OpenRouter** (modelli `:free`) — ultima rete di sicurezza.

Se tutti falliscono, il Gestore usa una **logica a regole** come ultima risorsa: il sistema non si ferma mai.

---

## 8. Perché multi-agent invece di un solo agente

| Problema con un agente unico | Soluzione qui |
|---|---|
| Un prompt gigante deve ragionare su tutto insieme → più allucinazioni | Ogni specialista riceve solo i suoi dati, in un prompt corto |
| Una fonte dati rotta corrompe tutta la decisione | La fonte rotta degrada **un solo** agente; gli altri proseguono |
| L'LLM è anche il risk manager → si può "convincere" a rischiare | Le regole di rischio sono Python puro, separate dall'LLM |
| Aggiungere un segnale = riscrivere il prompt monolitico | Aggiungere una capacità = aggiungere una classe agente |

**Bonus**: la serie originale aveva un bug di *timeframe* (Prophet allenato su candele da 1h, decisioni su dati da 15m). Qui un unico parametro `TIMEFRAME` è usato da tutti i componenti.

---

## 9. Setup completo

### Prerequisiti
- Python 3.11+
- Git

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
| **OpenRouter** (fallback) | [openrouter.ai](https://openrouter.ai) | Usa modelli `:free` |
| **Neon** (Postgres) | [neon.tech](https://neon.tech) | Serve solo per il deploy 24/7 |
| Whale Alert / CryptoPanic | rispettivi siti | Opzionali — il bot degrada senza |

### File `.env`
```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```
Compila almeno:
```env
GEMINI_API_KEY=la_tua_chiave
GEMINI_MODEL=gemini-2.5-flash
# GROQ_API_KEY=...        (consigliata come fallback)
# DATABASE_URL=...        (vuoto = SQLite locale)
```

---

## 10. Eseguire

```bash
# Un singolo ciclo (analisi + paper-trade)
python -m app.run

# Loop continuo (es. ogni ora) sul tuo PC
python -m app.run --loop --interval 3600
```

## 11. Dashboard

```bash
python -m streamlit run dashboard/app.py
```
Si apre su `http://localhost:8501`: equity curve, posizioni aperte, **storico decisioni con il ragionamento di ogni agente**, win rate, accuratezza delle previsioni.

> Avviala dalla cartella del progetto, così trova il database `paper_trading.db`.

Deploy gratis su **Streamlit Community Cloud**: [share.streamlit.io](https://share.streamlit.io) → New app → `dashboard/app.py` → aggiungi il secret `DATABASE_URL` (Neon).

## 12. Backtest

```bash
python -m app.backtest --start 2024-01-01 --end 2024-06-30
```
Riesegue dati storici nello stesso orchestrator e produce un report con P&L, win rate, max drawdown e accuratezza delle previsioni per asset.

---

## 13. Deploy 24/7 su GitHub Actions (gratis)

Il workflow `.github/workflows/trade-loop.yml` gira **ogni ora** da solo, anche a PC spento.

**Setup una tantum:**
1. Crea un database **Neon** gratuito ([neon.tech](https://neon.tech)) e copia la `DATABASE_URL`. Serve perché su GitHub Actions il file SQLite non si conserva tra un'esecuzione e l'altra — con Neon lo stato (equity, posizioni) persiste davvero.
2. Su GitHub: **Settings → Secrets and variables → Actions → New repository secret** e aggiungi:
   - `GEMINI_API_KEY`
   - `GROQ_API_KEY` (consigliato)
   - `DATABASE_URL` (Neon — necessario per il 24/7)
   - opzionali: `OPENROUTER_API_KEY`, `WHALE_ALERT_API_KEY`, `CRYPTOPANIC_API_KEY`
3. Tab **Actions → trade-loop → Run workflow** per un primo test manuale.

Da lì in poi gira automaticamente ogni ora.

---

## 14. Struttura del progetto

```
app/
├── config.py          # tutte le impostazioni (.env), con default sensati
├── run.py             # entrypoint — singolo ciclo o --loop
├── orchestrator.py    # pipeline completa di un ciclo
├── explain.py         # spiegazione in italiano di ogni decisione
├── data/              # fonti dati (prezzi, indicatori, forecast, sentiment, whale, news)
├── agents/            # 7 agenti (5 specialisti + PortfolioManager + RiskManager)
├── llm/               # gateway multi-provider con fallback
├── broker/            # PaperBroker (default) + Hyperliquid testnet (opzionale)
└── persistence/       # modelli SQLAlchemy + repository
dashboard/app.py       # Streamlit
prompts/               # system prompt di ogni agente (.md versionati)
tests/                 # pytest (unit + integration), sempre su PaperBroker
.github/workflows/     # CI (lint+test) + trade-loop (cron orario)
```

---

## 15. Stack tecnologico (tutto gratuito)

Python · ccxt · Prophet · pandas · pydantic · SQLAlchemy + Neon · Streamlit · Gemini / Groq / OpenRouter (free tier) · GitHub Actions · pytest · ruff.

---

## 16. Disclaimer

Progetto **educativo / portfolio**. Nessun soldo reale viene mai movimentato (broker di default = `PaperBroker`, saldo virtuale di 10.000). Niente di tutto questo è consiglio finanziario. I mercati cripto sono molto volatili; le performance simulate passate non predicono quelle future.

## 17. Crediti

Ispirato alla serie *"Creo il mio Trading AI Agent"* di Simone Rizzo:
[Parte 1](https://youtu.be/tzsRaNytHZ0) · [Parte 2](https://youtu.be/_CpICOumgBc) · [Parte 3](https://youtu.be/-6jRLa-zjeg) · [Parte 4](https://youtu.be/U7V_QSRJfZI)
