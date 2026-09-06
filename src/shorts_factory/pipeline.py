from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .planner import demo_plan, generate_plan, generate_topic_batch, generate_trending_topic
from .queue import QueueStore
from .render import probe_video, render_video
from .stock import fetch_scene_images
from .tts import synthesize
from .visuals import create_frames


def build_short(config: AppConfig, topic: str, *, demo: bool = False) -> tuple[int, Path]:
    queue = QueueStore(config.root / "data" / "queue.db")
    if queue.exists(topic):
        raise ValueError(
            "Такая тема уже есть в очереди; измените формулировку или удалите дубль вручную"
        )
    plan = demo_plan(topic) if demo else generate_plan(config, topic)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9а-яё]+", "-", topic.casefold(), flags=re.IGNORECASE).strip("-")[:48]
    output_dir = config.root / "output" / f"{stamp}-{slug or 'short'}"
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    backgrounds = fetch_scene_images(config, plan, output_dir)
    frames = create_frames(config, plan, output_dir, backgrounds=backgrounds)
    audio, _subtitles = synthesize(config, plan.narration, output_dir)
    video = render_video(config, frames, audio, output_dir)
    probe = probe_video(video)
    (output_dir / "probe.json").write_text(
        json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    item_id = queue.add(topic, output_dir)
    return item_id, output_dir


def next_topic(config: AppConfig) -> str:
    topics_path = config.root / "topics.txt"
    queue = QueueStore(config.root / "data" / "queue.db")
    topic_lines = (
        topics_path.read_text(encoding="utf-8-sig").splitlines() if topics_path.exists() else []
    )
    evergreen = [raw.strip() for raw in topic_lines if raw.strip() and not raw.startswith("#")]
    rows = queue.rows()
    fresh_every = int(config.section("content").get("fresh_topic_every", 4))
    if fresh_every > 0 and (len(rows) + 1) % fresh_every == 0:
        excluded = [str(row["topic"]) for row in rows] + evergreen
        try:
            return generate_trending_topic(config, excluded)
        except RuntimeError as exc:
            print(f"Свежий Dota-feed недоступен, беру вечнозелёную тему: {exc}")
    for topic in evergreen:
        if not queue.exists(topic):
            return topic
    generated = refill_topics(config)
    return generated[0]


def refill_topics(config: AppConfig, count: int | None = None) -> list[str]:
    topics_path = config.root / "topics.txt"
    queue = QueueStore(config.root / "data" / "queue.db")
    existing_lines = (
        topics_path.read_text(encoding="utf-8-sig").splitlines() if topics_path.exists() else []
    )
    existing = [
        line.strip() for line in existing_lines if line.strip() and not line.startswith("#")
    ]
    excluded = [str(row["topic"]) for row in queue.rows()] + existing
    batch_size = count or int(config.section("content").get("topic_batch_size", 50))
    generated = generate_topic_batch(config, excluded, count=batch_size)
    prefix = "" if not topics_path.exists() or topics_path.stat().st_size == 0 else "\n"
    with topics_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{prefix}# Автоматически предложено DeepSeek\n")
        handle.write("\n".join(generated) + "\n")
    return generated
