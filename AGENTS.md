# AGENTS.md — Regole operative per pi (progetto Multi-Agent Trading AI)

## Contesto
Il piano completo del progetto è in `PIANO.md` (stessa cartella). È la specifica da realizzare.
Obiettivo: sistema multi-agent di trading in paper/testnet, stack 100% gratuito.

## REGOLE OPERATIVE (vincolanti)
1. **Agisci, non chiedere.** NON chiedere mai "vuoi che inizi?" o conferme. Se l'istruzione è chiara, esegui subito con i tool (`write`, `edit`, `bash`).
2. **Non terminare il turno dopo la sola esplorazione.** Leggere/cercare file NON è "aver lavorato". Dopo aver letto ciò che ti serve, **continua** fino a creare/modificare i file richiesti.
3. **Una milestone alla volta**, nell'ordine di `PIANO.md`: M0 → M1 → M2 … Completa M0 (struttura repo + `config.py` + `ci.yml`) prima di passare oltre.
4. **Definition of Done di ogni task:** i file esistono, `ruff check` è pulito, `pytest` passa. Solo allora vai al task successivo.
5. **Se sei bloccato**, NON inventare e NON fermarti in silenzio: scrivi UNA riga in `BLOCKERS.md` e prosegui col prossimo task non bloccato.
6. **Niente segreti nel codice.** Tutto via env/`.env` (in `.gitignore`). In test/CI usa sempre il `PaperBroker` simulato: nessun ordine reale.
7. **Working directory = questa cartella.** Tutti i percorsi sono relativi a `trading-ai-multiagent/`.

## Delega ai sub-agent
- Per ricerche/lettura massiva usa l'agente **Explore** (read-only, veloce).
- Per il coordinamento e la suddivisione usa l'agente **Plan**.
- M0 è **sequenziale** (non delegare). Da M1 in poi, i task indipendenti (es. i provider dati T1.x, i broker T2.x, il gateway T3.x) possono essere **delegati in parallelo** ai sub-agent worker; poi integra e fai girare `pytest` sull'insieme.

## Comandi utili
- Lint: `ruff check .`
- Test: `pytest -q`
- Esecuzione di un ciclo: `python -m app.run`

## Stato
Aggiorna `PROGRESS.md` alla fine di ogni milestone con: cosa è fatto, cosa manca, prossimo task.
