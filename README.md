# PlayPal

PlayPal è una web app mobile-first (iOS/Android via browser + desktop responsive) per trovare compagni di gioco quando manca qualcuno per una partita.

## Funzionalità incluse nel prototipo

- **Autenticazione**: signup/login con rate limiting, verifica email obbligatoria (demo con token), reset password.
- **Profilo & Avatar**: selezione sport preferiti, ruoli per sport, avatar editor demo (stile cartoon), affidabilità e fair play.
- **Match/Eventi**: creazione partite (1v1 o squadre), ruoli obbligatori, visibilità pubblica/privata, stato match.
- **Bacheca geo-localizzata**: feed con ordinamento distanza/data e filtri principali.
- **Inviti partite private**: predisposti link token, codice invito e lista inviti diretti.
- **Chat**: chat di partita e chat 1-to-1.
- **Risultati**: inserimento, conferma, contestazione, modifica, timeout 24h e audit trail.
- **Ranking**: punteggio custom con funzione deterministica basata su outcome/rating/affidabilità + badge King of the Court.
- **Affidabilità**: decremento manuale 1 volta al mese con cooldown.

> Nota: questo è un prototipo **in-memory** (senza DB persistente o servizi esterni).

## Avvio locale

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run src/main.py
```

## Stack

- Python
- Streamlit
