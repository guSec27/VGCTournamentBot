# Bot Telegram Pokémon VGC Tournament

Bot Python che controlla il calendario pubblico usato da [Pokémon Event Locator but better](https://shairaba.github.io/pokemon-events-italia/index.html), una vista italiana che raccoglie dati dal [localizzatore ufficiale Pokémon](https://events.pokemon.com/EventLocator/). Il bot usa il JSON pubblicato dal sito per ottenere in un'unica richiesta eventi di tutte le regioni; i messaggi includono anche il collegamento al locator ufficiale per consultazione. Il locator ufficiale espone una ricerca geografica per città e raggio, non un elenco nazionale per regione, quindi il bot non effettua scraping dell'interfaccia ufficiale.

## Funzioni

- `/start` sceglie la regione e attiva gli avvisi nella chat (anche gruppi).
- `/regione` (alias `/region`) permette di cambiare la regione anche dopo la configurazione iniziale, anche nei gruppi.
- Per impostazione predefinita considera solo gli eventi Video Game con tag Sfida di Lega o Coppa di Lega.
- Un controllo periodico invia un messaggio quando appare un nuovo evento corrispondente. I tornei già pubblicati al momento dell'iscrizione vengono registrati come baseline e non generano messaggi arretrati.
- `/recap` invia in un unico messaggio le Sfide e Coppe di Lega VGC del mese corrente nella regione selezionata.
- `/cerca` apre una ricerca una tantum con scelta di gioco e tipo evento; non cambia i filtri degli avvisi automatici.
- Il recap automatico mensile è opzionale e disattivato per impostazione predefinita.

Ogni chat ha una sola regione. In un gruppo, avviare `/start` nel gruppo per configurare gli avvisi lì. Il bot deve essere in esecuzione perché polling e notifiche siano attivi.

## Avvio

1. Crea un bot tramite [@BotFather](https://t.me/BotFather) e copia il token.
2. Crea un ambiente e installa le dipendenze:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Copia `.env.example` in `.env` e imposta `TELEGRAM_BOT_TOKEN`.
4. Avvia il processo:

   ```sh
   python bot.py
   ```

5. Apri il bot su Telegram e usa `/start`.

## Configurazione

| Variabile | Default | Descrizione |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | Token richiesto da BotFather |
| `DATABASE_PATH` | `./data/bot.sqlite3` | Database SQLite delle chat e degli invii già fatti |
| `POLL_INTERVAL_SECONDS` | `300` | Intervallo di aggiornamento (minimo 60 secondi) |
| `TIMEZONE` | `Europe/Rome` | Fuso per il recap automatico |
| `AUTO_MONTHLY_RECAP` | `false` | Invia il recap ogni mese senza comando |
| `MONTHLY_RECAP_DAY` | `1` | Giorno del mese per il recap automatico (1–28) |
| `MONTHLY_RECAP_HOUR` | `9` | Ora locale per il recap automatico |

Le date degli eventi sono mostrate in `Europe/Rome`. `/recap` produce un solo messaggio Telegram; se l'elenco supera il limite, mostra gli eventi che entrano nel messaggio e indica quanti ne restano nel catalogo.

## Avvisi

Gli avvisi dipendono dalla frequenza di aggiornamento del JSON pubblicato dal catalogo. La funzione `first_seen_at` distingue gli eventi nuovi nel catalogo; il bot memorizza gli ID già notificati per non ripetere gli avvisi dopo un riavvio. Un'interruzione del processo sospende temporaneamente il monitoraggio.
