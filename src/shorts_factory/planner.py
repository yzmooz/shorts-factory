from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .config import AppConfig
from .dota import discovery_context, planning_context
from .models import Scene, VideoPlan

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topic", "title", "description", "tags", "scenes"],
    "properties": {
        "topic": {"type": "string"},
        "title": {"type": "string", "maxLength": 100},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["narration", "screen_text", "visual_hint"],
                "properties": {
                    "narration": {"type": "string"},
                    "screen_text": {"type": "string", "maxLength": 60},
                    "visual_hint": {"type": "string"},
                },
            },
        },
    },
}


def generate_topic_batch(config: AppConfig, excluded: list[str], *, count: int = 50) -> list[str]:
    load_dotenv(config.root / ".env")
    provider = str(config.section("content")["provider"])
    prompt = _topic_prompt(config, excluded, count=count, trending=False)
    try:
        payload = (
            _generate_openai_topics(config, prompt, count)
            if provider == "openai"
            else _generate_deepseek_topics(config, prompt)
        )
    except (APIConnectionError, APITimeoutError) as exc:
        raise RuntimeError(f"Не удалось получить темы от {provider}: {exc}") from exc
    except APIStatusError as exc:
        raise RuntimeError(f"API {provider} вернул HTTP {exc.status_code}: {exc.message}") from exc

    excluded_keys = {_topic_key(topic) for topic in excluded}
    result: list[str] = []
    seen = set(excluded_keys)
    for value in payload.get("topics", []):
        topic = _clean_topic(value)
        key = _topic_key(topic)
        if topic and key not in seen:
            result.append(topic)
            seen.add(key)
    if not result:
        raise RuntimeError(f"{provider} не предложил ни одной новой темы")
    return result[:count]


def generate_trending_topic(config: AppConfig, excluded: list[str]) -> str:
    """Generate one current, source-grounded patch or news topic."""
    load_dotenv(config.root / ".env")
    provider = str(config.section("content")["provider"])
    prompt = _topic_prompt(config, excluded, count=1, trending=True)
    try:
        payload = (
            _generate_openai_topics(config, prompt, 1)
            if provider == "openai"
            else _generate_deepseek_topics(config, prompt)
        )
    except (APIConnectionError, APITimeoutError) as exc:
        raise RuntimeError(f"Не удалось получить свежую тему от {provider}: {exc}") from exc
    except APIStatusError as exc:
        raise RuntimeError(f"API {provider} вернул HTTP {exc.status_code}: {exc.message}") from exc
    excluded_keys = {_topic_key(topic) for topic in excluded}
    for value in payload.get("topics", []):
        topic = _clean_topic(value)
        if topic and _topic_key(topic) not in excluded_keys:
            return topic
    raise RuntimeError(f"{provider} не предложил новую новостную тему")


def _topic_prompt(
    config: AppConfig,
    excluded: list[str],
    *,
    count: int,
    trending: bool,
) -> str:
    excluded_text = "\n".join(f"- {topic}" for topic in excluded[-250:]) or "- нет"
    live_context = discovery_context()
    direction = (
        "Все темы должны быть про свежий патч, обновление или официальную новость из блока "
        "ниже. Не используй сведения, которых нет в блоке."
        if trending
        else """
Распредели темы примерно так: 25% фишки, механики и комбинации конкретных героев;
20% типичные ошибки и решения для carry/mid/offlane/support; 15% предметы и выбор билда;
15% макро, линии, варды, Roshan, руны и тайминги; 15% лор героев; 10% свежие патчи
и официальные новости. Не делай подряд темы одного типа.
""".strip()
    )
    return f"""
Придумай ровно {count} цепляющих тем для русскоязычных YouTube Shorts ТОЛЬКО про Dota 2.
Аудитория — действующие игроки Dota 2 примерно 16–35 лет: они знают базовые термины,
но хотят лучше играть и любят интересный лор. {direction}

Каждая тема должна обещать один конкретный законченный ответ за 20–30 секунд и попадать
в реальную боль дотера: проигранная линия, неверный предмет, плохой тайминг, непонятная
механика, контрпик или любопытная история героя. Формулируй через ошибку, неожиданный
выбор, скрытую механику или сильный вопрос, но без ложного кликбейта. Используй официальные
английские имена героев и предметов. Для вечнозелёных тем не указывай номер патча и точные
цифры, которые могут измениться. Не предлагай другие игры, ставки, читы, бустинг, смурфинг,
слухи или киберспортивные результаты без источника. Одна короткая строка без нумерации,
эмодзи и хэштегов, желательно до 100 знаков.

Официальный live-контекст:
{live_context}

Не повторяй уже использованные темы:
{excluded_text}

Верни только JSON-объект вида {{"topics": ["тема 1", "тема 2"]}}.
""".strip()


def _generate_deepseek_topics(config: AppConfig, prompt: str) -> dict[str, Any]:
    content = config.section("content")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Нет DEEPSEEK_API_KEY в .env")
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=float(content.get("api_timeout_seconds", 180)),
        max_retries=2,
    )
    last_error: json.JSONDecodeError | None = None
    for temperature in (1.1, 0.7):
        response = client.chat.completions.create(
            model=str(content["deepseek_model"]),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты редактор русскоязычного Dota 2-канала. "
                        "Не предлагай темы вне Dota 2. Верни строгий JSON без markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=4500,
            temperature=temperature,
            extra_body={"thinking": {"type": "disabled"}},
        )
        value = response.choices[0].message.content
        if not value:
            continue
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error:
        raise RuntimeError("DeepSeek дважды вернул повреждённый список тем") from last_error
    raise RuntimeError("DeepSeek вернул пустой список тем")


def _generate_openai_topics(config: AppConfig, prompt: str, count: int) -> dict[str, Any]:
    content = config.section("content")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Нет OPENAI_API_KEY в .env")
    client = OpenAI(
        api_key=api_key,
        timeout=float(content.get("api_timeout_seconds", 180)),
        max_retries=2,
    )
    response = client.responses.create(
        model=str(content["openai_model"]),
        instructions=(
            "Создай разнообразный список тем только для русскоязычного Dota 2-канала "
            "и верни его по заданной схеме."
        ),
        input=prompt,
        reasoning={"effort": str(content.get("reasoning_effort", "low"))},
        max_output_tokens=3000,
        text={
            "format": {
                "type": "json_schema",
                "name": "topic_batch",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["topics"],
                    "properties": {
                        "topics": {
                            "type": "array",
                            "minItems": count,
                            "maxItems": count,
                            "items": {"type": "string", "maxLength": 140},
                        }
                    },
                },
            },
            "verbosity": "low",
        },
    )
    if not response.output_text:
        raise RuntimeError("OpenAI вернул пустой список тем")
    return json.loads(response.output_text)


def _topic_key(topic: str) -> str:
    return " ".join(topic.casefold().replace("ё", "е").split())


def _clean_topic(value: Any, max_length: int = 140) -> str:
    topic = " ".join(str(value).split()).strip(" -–—.\t")
    if len(topic) <= max_length:
        return topic
    for separator in (" — ", ": ", " – "):
        short = topic.split(separator, 1)[0].strip()
        if 30 <= len(short) <= max_length:
            return short
    return topic[:max_length].rsplit(" ", 1)[0].rstrip(" -–—.,:;!?")


def demo_plan(topic: str) -> VideoPlan:
    return VideoPlan(
        topic=topic,
        title="Почему Pudge промахивается хуком? #dota2 #shorts",
        description=(
            "Простая привычка помогает Pudge чаще попадать Meat Hook и не отдавать линию. "
            "Короткий разбор для игроков Dota 2."
        ),
        tags=["shorts", "dota2", "дота2", "pudge", "meat hook", "гайды дота 2"],
        scenes=[
            Scene(
                "Твой хук выдаёт не рука, а движение героя.",
                "ПОЧЕМУ ХУК МИМО?",
                "hero:pudge",
            ),
            Scene(
                "Если резко идёшь вперёд, враг заранее ждёт бросок.",
                "ТЫ ВЫДАЁШЬ МОМЕНТ",
                "hero:pudge",
            ),
            Scene(
                "Сначала двигайся так, будто просто добиваешь крипа.",
                "СПРЯЧЬ НАМЕРЕНИЕ",
                "hero:pudge",
            ),
            Scene(
                "Бросай после поворота врага: менять направление ему сложнее.",
                "ЛОВИ НА ПОВОРОТЕ",
                "hero:pudge",
            ),
            Scene(
                "Короткая дистанция надёжнее красивого хука через весь экран.",
                "БЛИЖЕ — НАДЁЖНЕЕ",
                "hero:pudge",
            ),
            Scene(
                "Скрывай намерение и целься в следующий шаг. Ты так делаешь?",
                "ЦЕЛЬСЯ В СЛЕДУЮЩИЙ ШАГ",
                "hero:pudge",
            ),
        ],
    )


def generate_plan(config: AppConfig, topic: str) -> VideoPlan:
    load_dotenv(config.root / ".env")
    provider = str(config.section("content")["provider"])
    prompt = _prompt(config, topic)
    try:
        raw_plan = (
            _generate_openai(config, prompt)
            if provider == "openai"
            else _generate_deepseek(config, prompt)
        )
        if bool(config.section("content").get("editorial_review", True)):
            review_prompt = _review_prompt(config, topic, raw_plan)
            raw_plan = (
                _generate_openai(config, review_prompt)
                if provider == "openai"
                else _generate_deepseek_review(config, review_prompt)
            )
    except (APIConnectionError, APITimeoutError) as exc:
        raise RuntimeError(f"Не удалось подключиться к API {provider}: {exc}") from exc
    except APIStatusError as exc:
        raise RuntimeError(f"API {provider} вернул HTTP {exc.status_code}: {exc.message}") from exc
    plan = VideoPlan.from_dict(raw_plan)
    plan.topic = topic
    _apply_dota_branding(plan)
    _validate_plan(plan, int(config.section("channel").get("scenes", 6)))
    return plan


def _generate_deepseek(config: AppConfig, prompt: str) -> dict[str, Any]:
    content = config.section("content")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Нет DEEPSEEK_API_KEY. Скопируйте .env.example в .env и вставьте ключ.")
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=float(content.get("api_timeout_seconds", 180)),
        max_retries=2,
    )
    response = client.chat.completions.create(
        model=str(content["deepseek_model"]),
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты опытный русскоязычный редактор Dota 2-контента. "
                    "Пишешь для действующих игроков и всегда отвечаешь валидным JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=2500,
        temperature=1.1,
        extra_body={"thinking": {"type": "disabled"}},
    )
    result = response.choices[0].message.content
    if not result:
        raise RuntimeError("DeepSeek вернул пустой ответ; повторите запрос")
    return json.loads(result)


def _generate_deepseek_review(config: AppConfig, prompt: str) -> dict[str, Any]:
    content = config.section("content")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Нет DEEPSEEK_API_KEY в .env")
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=float(content.get("api_timeout_seconds", 180)),
        max_retries=2,
    )
    response = client.chat.completions.create(
        model=str(content["deepseek_model"]),
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты строгий фактчекер и retention-редактор Dota 2. "
                    "Исправь сценарий и верни только валидный JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=2500,
        temperature=0.25,
        extra_body={"thinking": {"type": "disabled"}},
    )
    result = response.choices[0].message.content
    if not result:
        raise RuntimeError("DeepSeek-редактор вернул пустой ответ")
    return json.loads(result)


def _generate_openai(config: AppConfig, prompt: str) -> dict[str, Any]:
    content = config.section("content")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Нет OPENAI_API_KEY. Скопируйте .env.example в .env и вставьте ключ.")
    client = OpenAI(
        api_key=api_key,
        timeout=float(content.get("api_timeout_seconds", 180)),
        max_retries=2,
    )
    response = client.responses.create(
        model=str(content["openai_model"]),
        instructions=(
            "Ты опытный русскоязычный редактор Dota 2-контента. "
            "Верни цепляющий и проверяемый сценарий по заданной схеме."
        ),
        input=prompt,
        reasoning={"effort": str(content.get("reasoning_effort", "low"))},
        max_output_tokens=2500,
        text={
            "format": {
                "type": "json_schema",
                "name": "video_plan",
                "strict": True,
                "schema": PLAN_SCHEMA,
            },
            "verbosity": "low",
        },
    )
    if not response.output_text:
        raise RuntimeError("OpenAI вернул пустой ответ")
    return json.loads(response.output_text)


def _prompt(config: AppConfig, topic: str) -> str:
    channel = config.section("channel")
    content = config.section("content")
    scene_count = int(channel.get("scenes", 6))
    reference = planning_context(topic)
    return f"""
Создай цепляющий вертикальный YouTube Short ТОЛЬКО про Dota 2 на русском языке.
Тема: {topic!r}. Ниша: {channel["niche"]}. Аудитория — действующие игроки Dota 2
примерно 16–35 лет: можно использовать нормальный игровой сленг, но без токсичности.
Стиль: {content["style"]}. Ровно {scene_count} сцен и около
{channel["video_seconds"]} секунд речи.

Удержание и структура:
- сцена 1: сильный хук до 8 слов через боль, ошибку, парадокс или трудный выбор;
- сцена 2: сразу обозначь конкретную ставку — что игрок теряет или получает;
- сцена 3: дай первую полезную часть и создай естественное ожидание решения;
- между сценами 3 и 4 будет короткая реклама READY HELPER — не произноси название
  продукта и не обещай его функций в озвучке;
- сцены 4–5: главное решение и действие, которое можно применить в следующем матче;
- сцена 6: чёткий вывод, затем короткий вопрос-ситуация для комментариев.

Не растягивай интригу: ролик обязан дать полный ответ. Каждая сцена — 5–8 слов,
вся озвучка — не более 48 слов. Одна конкретная мысль, активные глаголы. Не начинай
с приветствия и не используй фразы
«а вы знали», «досмотри до конца», «секрет, о котором молчат». Не выдумывай патчи,
цифры, способности, цитаты, мету или результаты матчей. Патчевые и новостные факты
бери только из официального блока ниже. Лор можно пересказывать живо, не меняя факты.
Совет должен объяснять не только ЧТО делать, но и ПОЧЕМУ это работает.

screen_text — 2–5 коротких слов, смысл сцены, а не дубль озвучки. Без цифр сцен,
«шаг 1» и служебных надписей. В финале вопрос должен ставить дотера перед выбором:
например герой A или B, ранний BKB или урон, драться или фармить. Не спрашивай
«какой факт удивил». Направление CTA: {content["call_to_action"]}.
Не проси подписку или лайк и не пиши в финальном screen_text «подписывайся»,
«ставь лайк» или «пиши комментарий»: сам конкретный выбор должен вызывать ответ.

Верни JSON: topic, title до 100 символов обязательно с #dota2 и #shorts,
description, tags и scenes. description — 1–2 предложения с главным поисковым запросом,
без хэштегов и общих фраз. tags — 6–10 точных ключей, обязательно dota2, дота2, shorts,
а также герой, предмет, роль или механика из темы. Никаких тегов других игр.

Каждая сцена: narration, screen_text до 60 символов и visual_hint. visual_hint должен
быть только одним указателем официального Dota-ассета: hero:internal_name или
item:internal_name. Для героя используй внутреннее английское имя без npc_dota_hero_,
например hero:pudge, hero:nevermore, hero:windrunner. Для предмета — имя без item_,
например item:black_king_bar или item:blink. Выбирай героя или предмет, связанного со
сценой; используй минимум 2 разных ассета за ролик, если тема это позволяет.

Официальная справка, полученная непосредственно перед генерацией:
{reference}
""".strip()


def _review_prompt(config: AppConfig, topic: str, raw_plan: dict[str, Any]) -> str:
    scene_count = int(config.section("channel").get("scenes", 6))
    reference = planning_context(topic)
    draft = json.dumps(raw_plan, ensure_ascii=False, indent=2)
    choice_note = (
        "Эта тема про выбор: сцена 4 должна содержать условие «если — то», а сцена 5 — "
        "контрастный случай, когда альтернативное решение лучше."
        if any(word in topic.casefold() for word in ("когда", "выбрать", "или", "между"))
        else ""
    )
    return f"""
Отредактируй черновик Dota 2 Short перед публикацией. Верни тот же JSON-формат,
ровно {scene_count} сцен и не добавляй поля.

Проверь и исправь:
1. Любое название способности, предмета, эффект, число и патч должны соответствовать
   официальной справке ниже. Не называй героя «неуязвимым», если эффект лишь даёт
   debuff immunity или имеет исключения. Не переводи английские названия Dota-предметов
   буквально. Если подтверждения нет — убери цифру или абсолют.
2. Хук в первой сцене — до 8 слов, конкретная боль или неожиданный выбор дотера.
3. Уже во второй сцене ясно, что зритель получит. Сцены 4–5 дают применимое решение
   и объясняют, почему оно работает. Для выбора предмета дай условие «если — то», а не
   универсальный приказ после одной неудачной драки. Никакой воды, повторов и общих советов.
   {choice_note}
4. Между сценами 3 и 4 будет READY HELPER: сохрани естественную интригу, но не упоминай
   продукт и не приписывай ему функции.
5. Финал сначала завершает совет, потом задаёт один короткий игровой выбор для комментария.
   В каждой narration 5–8 слов, суммарно не более 48 слов. Финальный screen_text —
   конкретный выбор или «ТВОЙ ВЫБОР?», без просьб подписаться, поставить лайк или написать.
6. title содержит #dota2 и #shorts; tags относятся только к Dota 2.
7. visual_hint — только корректный hero:slug или item:slug. По возможности используй
   хотя бы два разных релевантных ассета.
8. Не оскорбляй зрителя и не пиши «включи мозг», «ты нуб», «хватит руинить» или похожие
   токсичные фразы. Тон уверенный и свой для дотеров, но не высокомерный.

Официальная справка:
{reference}

Черновик:
{draft}
""".strip()


def _apply_dota_branding(plan: VideoPlan) -> None:
    """Keep YouTube metadata in the Dota niche even if the model omits a marker."""
    normalized = {_topic_key(tag).replace(" ", "") for tag in plan.tags}
    required = (("dota2", "dota2"), ("дота2", "дота2"), ("shorts", "shorts"))
    for key, value in required:
        if key not in normalized:
            plan.tags.append(value)
            normalized.add(key)
    hashtags = plan.title.casefold()
    suffix = ""
    if "#dota2" not in hashtags:
        suffix += " #dota2"
    if "#shorts" not in hashtags:
        suffix += " #shorts"
    if suffix:
        plan.title = (plan.title[: 100 - len(suffix)].rstrip() + suffix).strip()
    if plan.scenes:
        final_text = plan.scenes[-1].screen_text.casefold()
        generic_cta = ("подпис", "ставь лайк", "пиши коммент", "напиши коммент")
        if any(marker in final_text for marker in generic_cta):
            plan.scenes[-1].screen_text = "ТВОЙ ВЫБОР?"


def _validate_plan(plan: VideoPlan, scene_count: int) -> None:
    if len(plan.scenes) != scene_count:
        raise ValueError(f"Модель вернула {len(plan.scenes)} сцен вместо {scene_count}")
    if not plan.title or len(plan.title) > 100:
        raise ValueError("Заголовок пустой или длиннее 100 символов")
    if any(not scene.narration.strip() or not scene.screen_text.strip() for scene in plan.scenes):
        raise ValueError("В сценарии есть пустая сцена")
    if any(len(scene.screen_text.split()) > 6 for scene in plan.scenes):
        raise ValueError("Экранный текст должен состоять максимум из 6 слов")
