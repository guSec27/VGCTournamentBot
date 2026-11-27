"""Telegram bot for Pokémon VGC events in Italy."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from events import (
    Event,
    EventSourceError,
    fetch_events,
    format_event,
    is_default_vgc_event,
    monthly_events,
    search_events,
)
from storage import Store

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("vgc_bot")

REGIONS = [
    "Abruzzo", "Basilicata", "Calabria", "Campania", "Emilia-Romagna",
    "Friuli-Venezia Giulia", "Lazio", "Liguria", "Lombardia", "Marche",
    "Molise", "Piemonte", "Puglia", "Sardegna", "Sicilia", "Toscana",
    "Trentino-Alto Adige", "Umbria", "Valle d'Aosta", "Veneto",
]
GAMES = {"vg": "Video Game", "tcg": "GCC", "pgo": "GO"}
EVENT_TYPES = {
    "league_challenge": "Sfida di Lega",
    "league_cup": "Coppa di Lega",
    "tournament": "Altri tornei",
}
SOURCE_URL = "https://shairaba.github.io/pokemon-events-italia/index.html"
OFFICIAL_SOURCE_URL = "https://events.pokemon.com/EventLocator/"
TELEGRAM_LIMIT = 4096
ITALIAN_MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def local_today() -> date:
    return datetime.now(ZoneInfo(os.getenv("TIMEZONE", "Europe/Rome"))).date()


def get_store() -> Store:
    return Store(os.getenv("DATABASE_PATH", "./data/bot.sqlite3"))


def region_keyboard(prefix: str = "region") -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(name, callback_data=f"{prefix}:{name}")
        for name in REGIONS
    ]
    return InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None:
        return
    context.user_data.pop("search_filters", None)
    region = context.application.bot_data["store"].get_region(update.effective_chat.id)
    region_status = f"Regione attuale: {region}. Puoi cambiarla qui sotto o con /regione.\n\n" if region else ""
    await update.message.reply_text(
        f"Ciao! {region_status}Scegli la regione per ricevere gli aggiornamenti sui tornei VGC.\n"
        "Riceverai avvisi per le nuove Sfide e Coppe di Lega; con /recap puoi "
        "ottenere il riepilogo del mese.\n\nComandi: /regione cambia area, /cerca sceglie filtri aggiuntivi.",
        reply_markup=region_keyboard(),
    )


async def set_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    current = context.application.bot_data["store"].get_region(update.effective_chat.id) if update.effective_chat else None
    prompt = f"Regione attuale: {current}. Scegli quella nuova:" if current else "Seleziona la regione:"
    await update.message.reply_text(prompt, reply_markup=region_keyboard())


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    store: Store = context.application.bot_data["store"]

    if query.data.startswith("region:"):
        await query.answer()
        region = query.data.partition(":")[2]
        if region not in REGIONS or query.message.chat_id is None:
            await query.edit_message_text("Regione non valida. Usa /start per riprovare.")
            return
        chat_id = query.message.chat_id
        previous_region = store.get_region(chat_id)
        store.set_region(chat_id, region)
        # The initial snapshot establishes a baseline and does not spam old listings.
        try:
            current = await asyncio.to_thread(fetch_events)
            store.mark_seen(chat_id, [e.id for e in current if is_default_vgc_event(e, region)])
        except EventSourceError:
            log.exception("Could not seed initial events for chat %s", chat_id)
        await query.edit_message_text(
            f"Regione {('aggiornata' if previous_region else 'impostata')}: {region}.\n"
            "Riceverai le nuove Sfide e Coppe di Lega VGC. Usa /recap per il mese "
            "corrente o /cerca per scegliere altri filtri.",
        )
        return

    if query.data.startswith("search:"):
        await handle_search_callback(update, context)


async def recap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None:
        return
    store: Store = context.application.bot_data["store"]
    region = store.get_region(update.effective_chat.id)
    if not region:
        await update.message.reply_text("Prima scegli la regione con /start.")
        return
    try:
        events = await asyncio.to_thread(fetch_events)
    except EventSourceError:
        log.exception("Event source unavailable while building recap")
        await update.message.reply_text("Non riesco a recuperare gli eventi in questo momento. Riprova più tardi.")
        return
    today = local_today()
    matches = monthly_events(events, region, today)
    await update.message.reply_text(render_recap(region, today, matches), disable_web_page_preview=True)


def render_recap(region: str, month: date, events: list[Event]) -> str:
    title = f"🏆 Tornei VGC — {ITALIAN_MONTHS[month.month - 1]} {month.year} · {region}"
    return render_event_list(title, events, "Nessuna Sfida o Coppa di Lega VGC trovata questo mese.")


def render_event_list(title: str, events: list[Event], empty_text: str = "Nessun evento trovato.") -> str:
    if not events:
        return (
            f"{title}\n\n{empty_text}\n\nDati: {SOURCE_URL}\n"
            f"Locator ufficiale: {OFFICIAL_SOURCE_URL}"
        )
    header = f"{title}\n\n"
    footer = (
        f"\nDati: {SOURCE_URL}\n"
        f"Locator ufficiale: {OFFICIAL_SOURCE_URL}"
    )
    entries = []
    for event in events:
        entry = format_event(event)
        current_size = len(header) + sum(len(item) + 2 for item in entries) + len(entry) + len(footer)
        # Leave room for the omission note if Telegram's single-message limit is reached.
        if current_size > TELEGRAM_LIMIT - 100:
            break
        entries.append(entry)
    message = header + "\n\n".join(entries)
    if len(entries) < len(events):
        message += f"\n\nAltri {len(events) - len(entries)} eventi non inclusi per il limite Telegram."
    return (message + footer)[:TELEGRAM_LIMIT]


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    store: Store = context.application.bot_data["store"]
    region = store.get_region(update.effective_chat.id) if update.effective_chat else None
    if not region:
        await update.message.reply_text("Prima scegli la regione con /start.")
        return
    context.user_data["search_filters"] = {
        "region": region,
        "selecting_region": False,
        "games": {"vg"},
        "types": {"league_challenge", "league_cup"},
    }
    await show_search_filters(update, context)


def search_keyboard(filters: dict) -> InlineKeyboardMarkup:
    rows = []
    rows.append([
        InlineKeyboardButton(
            f"🌍 Regione: {filters['region']} (solo questa ricerca)",
            callback_data="search:region",
        )
    ])
    for key, label in GAMES.items():
        mark = "☑" if key in filters["games"] else "☐"
        rows.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"search:game:{key}")])
    for key, label in EVENT_TYPES.items():
        mark = "☑" if key in filters["types"] else "☐"
        rows.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"search:type:{key}")])
    rows.append([InlineKeyboardButton("Cerca con questi filtri", callback_data="search:run")])
    return InlineKeyboardMarkup(rows)


def search_region_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(name, callback_data=f"search:region:{name}")
        for name in REGIONS
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("↩ Torna ai filtri", callback_data="search:region:back")])
    return InlineKeyboardMarkup(rows)


async def show_search_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filters = context.user_data["search_filters"]
    if filters["selecting_region"]:
        text = "Scegli la regione per questa ricerca. La regione configurata resterà invariata:"
        markup = search_region_keyboard()
    else:
        text = "Scegli regione e filtri per questa ricerca (non modifica avvisi o recap):"
        markup = search_keyboard(filters)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup)


async def handle_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    filters = context.user_data.get("search_filters")
    if filters is None:
        await query.edit_message_text("Ricerca scaduta. Usa /cerca per avviarne una nuova.")
        return
    parts = query.data.split(":")
    if query.data == "search:region":
        filters["selecting_region"] = True
        await query.answer()
        await show_search_filters(update, context)
        return
    if query.data.startswith("search:region:"):
        selected = query.data.split(":", 2)[2]
        if selected == "back":
            filters["selecting_region"] = False
        elif selected in REGIONS:
            filters["region"] = selected
            filters["selecting_region"] = False
        await query.answer()
        await show_search_filters(update, context)
        return
    if len(parts) == 3 and parts[1] in ("game", "type"):
        group, value = parts[1], parts[2]
        if value in filters["games" if group == "game" else "types"]:
            filters["games" if group == "game" else "types"].remove(value)
        else:
            filters["games" if group == "game" else "types"].add(value)
        await query.answer()
        await show_search_filters(update, context)
        return
    if query.data != "search:run":
        return
    await query.answer("Sto cercando…")
    region = filters["region"]
    try:
        events = await asyncio.to_thread(fetch_events)
    except EventSourceError:
        await query.edit_message_text("Catalogo non disponibile. Riprova più tardi.")
        return
    today = local_today()
    matches = search_events(events, region, filters["games"], filters["types"], today)
    context.user_data.pop("search_filters", None)
    body = render_event_list(
        f"🔎 Risultati di {ITALIAN_MONTHS[today.month - 1]} {today.year} · {region}",
        matches,
        "Nessun evento trovato con i filtri selezionati.",
    )
    await query.edit_message_text(body, disable_web_page_preview=True)


async def monitor(application: Application) -> None:
    store: Store = application.bot_data["store"]
    poll_seconds = max(60, int(os.getenv("POLL_INTERVAL_SECONDS", "300")))
    while True:
        try:
            events = await asyncio.to_thread(fetch_events)
            for chat_id, region in store.subscribers():
                unseen = [e for e in events if is_default_vgc_event(e, region) and not store.was_seen(chat_id, e.id)]
                for event in unseen:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🆕 Nuovo torneo VGC in {region}\n\n{format_event(event)}\n\n"
                            f"Dati: {SOURCE_URL}\nLocator ufficiale: {OFFICIAL_SOURCE_URL}"
                        ),
                        disable_web_page_preview=True,
                    )
                    store.mark_seen(chat_id, [event.id])
                store.mark_seen(chat_id, [e.id for e in unseen])
            await maybe_send_monthly_recap(application, events)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Error in event monitoring cycle")
        await asyncio.sleep(poll_seconds)


async def maybe_send_monthly_recap(application: Application, events: list[Event]) -> None:
    if os.getenv("AUTO_MONTHLY_RECAP", "false").lower() not in {"1", "true", "yes"}:
        return
    timezone = ZoneInfo(os.getenv("TIMEZONE", "Europe/Rome"))
    now = datetime.now(timezone)
    day = min(max(1, int(os.getenv("MONTHLY_RECAP_DAY", "1"))), 28)
    hour = min(max(0, int(os.getenv("MONTHLY_RECAP_HOUR", "9"))), 23)
    if now.day < day or (now.day == day and now.hour < hour):
        return
    month_key = now.strftime("%Y-%m")
    store: Store = application.bot_data["store"]
    for chat_id, region in store.subscribers():
        if store.recap_sent(chat_id, month_key):
            continue
        await application.bot.send_message(
            chat_id=chat_id,
            text=render_recap(region, now.date(), monthly_events(events, region, now.date())),
            disable_web_page_preview=True,
        )
        store.mark_recap_sent(chat_id, month_key)


async def post_init(application: Application) -> None:
    application.bot_data["store"] = get_store()
    application.create_task(monitor(application), name="event-monitor")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Imposta TELEGRAM_BOT_TOKEN nel file .env (vedi .env.example).")
    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("region", set_region))
    app.add_handler(CommandHandler("regione", set_region))
    app.add_handler(CommandHandler("recap", recap))
    app.add_handler(CommandHandler("cerca", search))
    app.add_handler(CallbackQueryHandler(callback))
    # Python 3.14 no longer creates a default event loop automatically.
    # python-telegram-bot's run_polling() expects one to exist in this thread.
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
