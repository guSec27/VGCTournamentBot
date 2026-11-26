"""Fetch and filter events from the community mirror of the official locator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

EVENTS_URL = "https://shairaba.github.io/pokemon-events-italia/data/events.json"
ITALY_TZ = ZoneInfo("Europe/Rome")
ALLOWED_DEFAULT_TYPES = {"league_challenge", "league_cup"}


class EventSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    id: str
    name: str
    venue: str
    address: str
    region: str
    start: datetime
    products: frozenset[str]
    tags: frozenset[str]
    category: str
    activity_type: str
    url: str | None
    admission: str | None


def fetch_events() -> list[Event]:
    try:
        response = httpx.get(EVENTS_URL, timeout=30, headers={"User-Agent": "pokemon-vgc-telegram-bot/1.0"})
        response.raise_for_status()
        payload = response.json()
        records = payload["events"]
        if isinstance(records, dict):
            records = records.values()
        result = []
        for raw in records:
            try:
                start = datetime.fromisoformat(str(raw["start_date"]).replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=ITALY_TZ)
                result.append(Event(
                    id=str(raw.get("guid") or raw["display_id"]),
                    name=str(raw.get("name") or raw.get("series_name") or raw.get("activity_group_name") or "Torneo Pokémon"),
                    venue=str(raw.get("venue_name") or raw.get("activity_group_name") or "Sede da confermare"),
                    address=str(raw.get("full_address") or "Indirizzo non disponibile"),
                    region=str(raw.get("region") or "").strip().casefold(),
                    start=start,
                    products=frozenset(str(x).casefold() for x in raw.get("products", [])),
                    tags=frozenset(str(x).casefold() for x in raw.get("event_type_tags", [])),
                    category=str(raw.get("category") or "").casefold(),
                    activity_type=str(raw.get("activity_type") or "").casefold(),
                    url=raw.get("event_website") or raw.get("third_party_registration_website"),
                    admission=raw.get("admission"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return result
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise EventSourceError(f"Unable to load event catalog: {exc}") from exc


def _is_in_region(event: Event, region: str) -> bool:
    return event.region == region.strip().casefold()


def _is_current_month(event: Event, month: date) -> bool:
    local_start = event.start.astimezone(ITALY_TZ)
    return local_start.year == month.year and local_start.month == month.month


def is_default_vgc_event(event: Event, region: str) -> bool:
    """Only Video Game League Challenges and League Cups."""
    return (
        _is_in_region(event, region)
        and "vg" in event.products
        and bool(event.tags.intersection(ALLOWED_DEFAULT_TYPES))
    )


def monthly_events(events: list[Event], region: str, month: date) -> list[Event]:
    return sorted(
        (e for e in events if is_default_vgc_event(e, region) and _is_current_month(e, month)),
        key=lambda event: event.start,
    )


def search_events(
    events: list[Event], region: str, games: set[str], types: set[str], month: date
) -> list[Event]:
    matched = []
    for event in events:
        if not _is_in_region(event, region) or not _is_current_month(event, month):
            continue
        has_game = bool(event.products.intersection(games))
        has_type = bool(event.tags.intersection(types)) or ("tournament" in types and event.activity_type == "tournament")
        if has_game and has_type:
            matched.append(event)
    return sorted(matched, key=lambda event: event.start)


def format_event(event: Event) -> str:
    local_start = event.start.astimezone(ITALY_TZ)
    type_labels = []
    if "league_cup" in event.tags:
        type_labels.append("Coppa di Lega")
    if "league_challenge" in event.tags:
        type_labels.append("Sfida di Lega")
    if not type_labels:
        type_labels.append("Torneo")
    lines = [
        f"📍 {event.name}",
        f"🎮 {', '.join(type_labels)} · Video Game" if "vg" in event.products else f"🎮 {', '.join(type_labels)}",
        f"📅 {local_start.strftime('%d/%m/%Y alle %H:%M')}",
        f"🏬 {event.venue}",
        f"📌 {event.address}",
    ]
    if event.admission:
        lines.append(f"💶 Quota: {event.admission}")
    if event.url:
        safe_url = event.url.replace("(", "%28").replace(")", "%29")
        lines.append(f"🔗 {safe_url}")
    return "\n".join(lines)
