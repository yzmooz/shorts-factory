from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Any

DOTA_DATAFEED = "https://www.dota2.com/datafeed"
DOTA_MEDIA = "https://cdn.cloudflare.steamstatic.com/apps/dota2"
STEAM_NEWS = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"

POPULAR_HEROES = (
    "pudge",
    "invoker",
    "nevermore",
    "juggernaut",
    "phantom_assassin",
    "axe",
    "crystal_maiden",
    "sniper",
    "slark",
    "rubick",
    "windrunner",
    "legion_commander",
)

ENTITY_ALIASES = {
    "пудж": ("hero", "pudge"),
    "инвокер": ("hero", "invoker"),
    "сф": ("hero", "nevermore"),
    "шадоу финд": ("hero", "nevermore"),
    "джаггер": ("hero", "juggernaut"),
    "фантомка": ("hero", "phantom_assassin"),
    "акс": ("hero", "axe"),
    "цм": ("hero", "crystal_maiden"),
    "снайпер": ("hero", "sniper"),
    "сларк": ("hero", "slark"),
    "рубик": ("hero", "rubick"),
    "виндренжер": ("hero", "windrunner"),
    "легионка": ("hero", "legion_commander"),
    "бкб": ("item", "black_king_bar"),
    "bkb": ("item", "black_king_bar"),
    "блинк": ("item", "blink"),
    "аганим": ("item", "ultimate_scepter"),
    "шард": ("item", "aghanims_shard"),
    "манта": ("item", "manta"),
    "даст": ("item", "dust"),
    "сентри": ("item", "ward_sentry"),
    "обсервер": ("item", "ward_observer"),
}


def discovery_context() -> str:
    """Return a compact live editorial feed for Dota topic generation."""
    try:
        heroes = hero_catalog()
        patch = latest_patch()
        news = steam_news()
    except (OSError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
        return "Официальный live-feed сейчас недоступен: предлагай только вечнозелёные темы."

    hero_names = ", ".join(str(row.get("name_loc", "")) for row in heroes if row.get("name_loc"))
    patch_digest = _patch_digest(patch, heroes, max_lines=18)
    news_digest = "\n".join(
        f"- {item.get('title', '').strip()}"
        for item in news[:6]
        if item.get("title", "").strip()
    )
    return (
        f"Официальный последний патч: {patch.get('patch_number', 'неизвестен')}.\n"
        f"Выжимка патча:\n{patch_digest or '- нет данных'}\n"
        f"Свежие записи Dota 2 в Steam:\n{news_digest or '- нет данных'}\n"
        f"Допустимые официальные имена героев: {hero_names}"
    )[:15000]


def planning_context(topic: str) -> str:
    """Ground a script in current official hero, item, patch, and news data."""
    try:
        heroes = hero_catalog()
        items = item_catalog()
        hero = _match_entity(topic, heroes, "npc_dota_hero_")
        item = _match_entity(topic, items, "item_")
        sections: list[str] = []

        patch_list = patch_list_data()
        latest_version = str(patch_list[-1]["patch_number"]) if patch_list else "неизвестен"
        sections.append(f"Последний официальный патч на момент генерации: {latest_version}.")

        if hero:
            details = hero_data(int(hero["id"]))
            sections.append(_hero_reference(details))
        if item:
            details = item_data(int(item["id"]))
            sections.append(_item_reference(details))

        normalized = _normalize(topic)
        wants_patch = bool(re.search(r"\bпатч|обновлен|7\s*\d", normalized))
        wants_news = any(word in normalized for word in ("новост", "анонс", "ивент", "турнир"))
        if wants_patch:
            patch = latest_patch()
            sections.append(
                "Данные последнего патча:\n"
                + _patch_digest(patch, heroes, hero_id=int(hero["id"]) if hero else None)
            )
        if wants_news:
            sections.append("Свежие официальные новости:\n" + _news_digest(steam_news()))

        sections.append(
            "Используй только сведения выше и устойчивые базовые механики Dota 2. "
            "Если конкретной цифры в источнике нет, не придумывай её."
        )
        return "\n\n".join(section for section in sections if section)[:14000]
    except (OSError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
        return (
            "Официальные данные сейчас недоступны. Делай вечнозелёный качественный разбор "
            "без номеров патчей, точных чисел, дат и заявлений о текущей мете."
        )


def resolve_visual_asset(hint: str, topic: str, scene_index: int) -> dict[str, str]:
    """Resolve `hero:slug` or `item:slug` to official Dota media."""
    requested_kind, requested_slug = _parse_asset_hint(hint)
    try:
        heroes = hero_catalog()
        items = item_catalog()
        hero_by_slug = {
            str(row.get("name", "")).removeprefix("npc_dota_hero_"): row for row in heroes
        }
        item_by_slug = {str(row.get("name", "")).removeprefix("item_"): row for row in items}
        if requested_kind == "hero" and requested_slug in hero_by_slug:
            row = hero_by_slug[requested_slug]
            return _hero_asset(requested_slug, str(row.get("name_loc", requested_slug)))
        if requested_kind == "item" and requested_slug in item_by_slug:
            row = item_by_slug[requested_slug]
            return _item_asset(requested_slug, str(row.get("name_loc", requested_slug)))
    except (OSError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
        pass

    alias = _alias_entity(hint + " " + topic)
    if alias:
        kind, slug = alias
        return _item_asset(slug, slug) if kind == "item" else _hero_asset(slug, slug)
    digest = hashlib.sha256(f"{topic}:{scene_index}".encode()).digest()
    slug = POPULAR_HEROES[int.from_bytes(digest[:2], "big") % len(POPULAR_HEROES)]
    return _hero_asset(slug, slug)


@lru_cache(maxsize=1)
def hero_catalog() -> list[dict[str, Any]]:
    payload = _json_url(f"{DOTA_DATAFEED}/herolist?language=russian")
    return list(payload["result"]["data"]["heroes"])


@lru_cache(maxsize=1)
def item_catalog() -> list[dict[str, Any]]:
    payload = _json_url(f"{DOTA_DATAFEED}/itemlist?language=russian")
    return list(payload["result"]["data"]["itemabilities"])


@lru_cache(maxsize=1)
def patch_list_data() -> list[dict[str, Any]]:
    payload = _json_url(f"{DOTA_DATAFEED}/patchnoteslist?language=russian")
    return list(payload["patches"])


@lru_cache(maxsize=1)
def latest_patch() -> dict[str, Any]:
    patches = patch_list_data()
    if not patches:
        raise ValueError("Dota 2 не вернула список патчей")
    version = urllib.parse.quote(str(patches[-1]["patch_number"]))
    return _json_url(f"{DOTA_DATAFEED}/patchnotes?version={version}&language=russian")


@lru_cache(maxsize=64)
def hero_data(hero_id: int) -> dict[str, Any]:
    payload = _json_url(
        f"{DOTA_DATAFEED}/herodata?language=russian&hero_id={int(hero_id)}"
    )
    return dict(payload["result"]["data"]["heroes"][0])


@lru_cache(maxsize=128)
def item_data(item_id: int) -> dict[str, Any]:
    payload = _json_url(
        f"{DOTA_DATAFEED}/itemdata?language=russian&item_id={int(item_id)}"
    )
    return dict(payload["result"]["data"]["items"][0])


@lru_cache(maxsize=1)
def steam_news() -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"appid": 570, "count": 8, "maxlength": 1200, "format": "json"}
    )
    payload = _json_url(f"{STEAM_NEWS}?{query}")
    return list(payload["appnews"]["newsitems"])


def _json_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "ShortsFactory/0.3"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _match_entity(
    topic: str, rows: list[dict[str, Any]], internal_prefix: str
) -> dict[str, Any] | None:
    normalized_topic = f" {_normalize(topic)} "
    candidates: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        internal = str(row.get("name", "")).removeprefix(internal_prefix)
        aliases = {
            _normalize(internal),
            _normalize(str(row.get("name_loc", ""))),
            _normalize(str(row.get("name_english_loc", ""))),
        }
        for alias in aliases - {""}:
            if f" {alias} " in normalized_topic:
                candidates.append((len(alias), row))
    alias = _alias_entity(topic)
    if alias:
        kind, slug = alias
        expected_kind = "hero" if internal_prefix.startswith("npc_dota_hero") else "item"
        if kind == expected_kind:
            for row in rows:
                if str(row.get("name", "")).removeprefix(internal_prefix) == slug:
                    candidates.append((1000, row))
                    break
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def _alias_entity(value: str) -> tuple[str, str] | None:
    normalized = f" {_normalize(value)} "
    for alias, target in sorted(ENTITY_ALIASES.items(), key=lambda pair: -len(pair[0])):
        if f" {_normalize(alias)} " in normalized:
            return target
    return None


def _parse_asset_hint(hint: str) -> tuple[str, str]:
    match = re.search(r"\b(hero|item)\s*:\s*([a-z0-9_]+)", hint.casefold())
    return (match.group(1), match.group(2)) if match else ("", "")


def _hero_asset(slug: str, display_name: str) -> dict[str, str]:
    return {
        "kind": "hero",
        "slug": slug,
        "name": display_name,
        "url": f"{DOTA_MEDIA}/videos/dota_react/heroes/renders/{slug}.webm",
    }


def _item_asset(slug: str, display_name: str) -> dict[str, str]:
    return {
        "kind": "item",
        "slug": slug,
        "name": display_name,
        "url": f"{DOTA_MEDIA}/images/dota_react/items/{slug}.png",
    }


def _hero_reference(hero: dict[str, Any]) -> str:
    lines = [f"Официальные данные героя {hero.get('name_loc', hero.get('name', ''))}:"]
    if hero.get("bio_loc"):
        lines.append("Лор: " + _plain(str(hero["bio_loc"])))
    if hero.get("hype_loc"):
        lines.append("Роль и стиль: " + _plain(str(hero["hype_loc"])))
    for ability in hero.get("abilities", [])[:8]:
        name = _plain(str(ability.get("name_loc", ability.get("name", ""))))
        description = _plain(str(ability.get("desc_loc", "")))
        if name and description:
            lines.append(f"Способность {name}: {description}")
    return "\n".join(lines)


def _item_reference(item: dict[str, Any]) -> str:
    lines = [f"Официальные данные предмета {item.get('name_loc', item.get('name', ''))}:"]
    if str(item.get("name", "")) == "item_black_king_bar":
        lines.append(
            "Важно для фактчека: Black King Bar даёт debuff immunity и сопротивление "
            "магии, но не делает владельца полностью неуязвимым; существуют эффекты, "
            "которые пробивают debuff immunity. Не говори «блокирует всю магию и контроль»."
        )
    for key in ("desc_loc", "lore_loc"):
        value = _plain(str(item.get(key, "")))
        if value:
            lines.append(value)
    return "\n".join(lines)


def _patch_digest(
    patch: dict[str, Any],
    heroes: list[dict[str, Any]],
    *,
    hero_id: int | None = None,
    max_lines: int = 28,
) -> str:
    hero_names = {int(row["id"]): str(row.get("name_loc", row.get("name", ""))) for row in heroes}
    lines: list[str] = []
    for note in _walk_notes(patch.get("general_notes", [])):
        lines.append("Общее: " + note)
    for row in patch.get("heroes", []):
        row_id = int(row.get("hero_id", 0))
        if hero_id is not None and row_id != hero_id:
            continue
        name = hero_names.get(row_id, f"hero_id={row_id}")
        for note in _walk_notes(row):
            lines.append(f"{name}: {note}")
    if hero_id is None:
        for row in patch.get("items", [])[:8]:
            for note in _walk_notes(row):
                lines.append("Предмет: " + note)
    cleaned = [line for line in lines if line.strip()]
    return "\n".join(f"- {line}" for line in cleaned[:max_lines])


def _walk_notes(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("note"), str):
            note = _plain(value["note"])
            if note:
                result.append(note)
        for key, child in value.items():
            if key != "note":
                result.extend(_walk_notes(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_walk_notes(child))
    return result


def _news_digest(news: list[dict[str, Any]], max_items: int = 5) -> str:
    lines: list[str] = []
    for item in news[:max_items]:
        title = _plain(str(item.get("title", "")))
        body = _plain(str(item.get("contents", "")))[:650]
        url = str(item.get("url", ""))
        if title:
            lines.append(f"- {title}: {body} Источник: {url}")
    return "\n".join(lines)


def _plain(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(value))
    without_tokens = re.sub(r"%[a-zA-Z0-9_]+%+", "", without_tags)
    return " ".join(without_tokens.split())


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-zа-яё0-9]+", " ", value.casefold()).split())
