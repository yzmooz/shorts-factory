from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .config import AppConfig
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
    channel = config.section("channel")
    excluded_text = "\n".join(f"- {topic}" for topic in excluded[-200:]) or "- нет"
    prompt = f"""
Придумай ровно {count} разных тем для будущих русскоязычных YouTube Shorts.
Ниша: {channel["niche"]}. Аудитория: {"дети" if config.made_for_kids else "13+"}.
Темы должны вызывать любопытство, давать законченный ответ за 20–30 секунд и хорошо
иллюстрироваться короткими стоковыми видеоклипами. Смешивай космос, животных, природу,
человеческое тело, физику, технологии, историю изобретений и бытовую науку.
Не предлагай политику, трагедии, медсоветы, опасные эксперименты, чужие франшизы,
непроверяемые сенсации и темы, похожие друг на друга. Формулировка каждой темы —
одна короткая строка без нумерации, эмодзи и #shorts.

Не повторяй эти уже использованные темы:
{excluded_text}

Верни только JSON-объект вида {{"topics": ["тема 1", "тема 2"]}}.
""".strip()
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
        topic = " ".join(str(value).split()).strip(" -–—.\t")
        key = _topic_key(topic)
        if topic and len(topic) <= 140 and key not in seen:
            result.append(topic)
            seen.add(key)
    if not result:
        raise RuntimeError(f"{provider} не предложил ни одной новой темы")
    return result[:count]


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
                    "content": "Ты редактор тем для YouTube Shorts. Верни строгий JSON без markdown.",
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
        instructions="Создай разнообразный список тем и верни его по заданной схеме.",
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


def demo_plan(topic: str) -> VideoPlan:
    return VideoPlan(
        topic=topic,
        title="Почему небо на Марсе красное? #shorts #наука",
        description=(
            "Коротко разбираемся, почему Красная планета получила свой цвет. "
            "Оригинальный научно-популярный ролик."
        ),
        tags=["shorts", "наука", "космос", "марс"],
        scenes=[
            Scene(
                "Марс называют Красной планетой. Но почему он именно такого цвета?",
                "ПОЧЕМУ МАРС КРАСНЫЙ?",
                "Марс крупным планом",
            ),
            Scene(
                "В его грунте много железа — того же элемента, из которого делают сталь.",
                "ВСЕ ДЕЛО В ЖЕЛЕЗЕ",
                "железные частицы",
            ),
            Scene(
                "Когда железо реагирует с кислородом, появляется оксид железа.",
                "ЖЕЛЕЗО + КИСЛОРОД",
                "простая химическая схема",
            ),
            Scene(
                "По сути, это знакомая нам ржавчина, только в виде мельчайшей пыли.",
                "ПЫЛЬ, ПОХОЖАЯ НА РЖАВЧИНУ",
                "красная пыль",
            ),
            Scene(
                "Ветры разносят эту пыль по поверхности и поднимают ее в атмосферу.",
                "ВЕТЕР РАЗНОСИТ ПЫЛЬ",
                "пылевая буря",
            ),
            Scene(
                "Поэтому издалека весь Марс кажется красно-оранжевым. Какой факт удивил тебя больше всего?",
                "КРАСНЫЙ ДАЖЕ ИЗ КОСМОСА",
                "Марс в космосе",
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
    except (APIConnectionError, APITimeoutError) as exc:
        raise RuntimeError(f"Не удалось подключиться к API {provider}: {exc}") from exc
    except APIStatusError as exc:
        raise RuntimeError(f"API {provider} вернул HTTP {exc.status_code}: {exc.message}") from exc
    plan = VideoPlan.from_dict(raw_plan)
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
                "content": "Ты редактор оригинальных YouTube Shorts. Всегда отвечай валидным JSON.",
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
        instructions="Ты редактор оригинальных YouTube Shorts. Верни сценарий по заданной схеме.",
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
    audience = "детям" if config.made_for_kids else "общей аудитории 13+"
    scene_count = int(channel.get("scenes", 6))
    return f"""
Создай проверяемый сценарий вертикального YouTube Short на русском языке.
Тема: {topic!r}. Целевая аудитория: {audience}. Ниша: {channel["niche"]}.
Стиль: {content["style"]}. Ровно {scene_count} сцен, около {channel["video_seconds"]} секунд речи.
Построй цельный мини-сюжет: 1) хук-вопрос или парадокс, 2) короткий прямой ответ,
3–5) причинная цепочка с нарастающим интересом, 6) ясный вывод. Зритель должен получить
полный ответ на тему — нельзя обрывать объяснение ради комментариев.
Первая фраза — хук до 9 слов без приветствия. Каждая сцена — 7–12 слов, одна конкретная
мысль, активные глаголы, минимум вводных слов. Не повторяй одну мысль разными словами.
screen_text — 2–5 слов, это смысл сцены, а не дословный дубль озвучки. Не выдумывай
факты, источники, цитаты и статистику.
Не используй опасные задания, шок-контент, чужих персонажей или бренды.
В финальной сцене сначала закончи объяснение одним чётким выводом и только потом задай
очень короткий вопрос по теме с числом или 2–3 вариантами ответа. Не спрашивай
«какой факт удивил» и не подменяй ответ призывом к комментарию.
Общее направление финала: {content["call_to_action"]}.
Верни JSON: topic, title до 100 символов с #shorts, description, tags и scenes.
description — 1–2 уникальных предложения: в первой строке естественно используй
главные поисковые слова темы, без хэштегов и общих фраз. tags — 5–8 точных ключевых
слов по теме, включая науку и shorts; не добавляй нерелевантные популярные запросы.
Каждая сцена: narration, screen_text до 60 символов и visual_hint.
visual_hint — 3–7 конкретных английских слов для поиска живого стокового видеоклипа.
Описывай видимое действие, объект и среду; не пиши абстрактные понятия. Без слов
animation, illustration, diagram, text, logo и без имен брендов.
""".strip()


def _validate_plan(plan: VideoPlan, scene_count: int) -> None:
    if len(plan.scenes) != scene_count:
        raise ValueError(f"Модель вернула {len(plan.scenes)} сцен вместо {scene_count}")
    if not plan.title or len(plan.title) > 100:
        raise ValueError("Заголовок пустой или длиннее 100 символов")
    if any(not scene.narration.strip() or not scene.screen_text.strip() for scene in plan.scenes):
        raise ValueError("В сценарии есть пустая сцена")
    if any(len(scene.screen_text.split()) > 6 for scene in plan.scenes):
        raise ValueError("Экранный текст должен состоять максимум из 6 слов")
