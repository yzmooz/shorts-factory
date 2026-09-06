from shorts_factory.config import AppConfig
from shorts_factory.pipeline import next_topic, refill_topics
from shorts_factory.planner import generate_topic_batch
from shorts_factory.queue import QueueStore


def app_config(tmp_path):
    return AppConfig(
        root=tmp_path,
        raw={
            "channel": {"audience": "general", "niche": "наука"},
            "content": {"provider": "deepseek", "topic_batch_size": 3},
        },
    )


def test_topic_batch_removes_duplicates(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    monkeypatch.setattr(
        "shorts_factory.planner._generate_deepseek_topics",
        lambda *_args: {"topics": ["  Почему лёд плавает? ", "почему лед плавает?", "Новая тема"]},
    )

    result = generate_topic_batch(config, ["Почему лёд плавает?"], count=3)

    assert result == ["Новая тема"]


def test_refill_writes_only_new_topics(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    (tmp_path / "topics.txt").write_text("Старая тема\n", encoding="utf-8")
    queue = QueueStore(tmp_path / "data" / "queue.db")
    queue.add("Уже опубликовано", tmp_path / "old")
    captured = {}

    def fake_generate(_config, excluded, *, count):
        captured["excluded"] = excluded
        captured["count"] = count
        return ["Новая тема 1", "Новая тема 2"]

    monkeypatch.setattr("shorts_factory.pipeline.generate_topic_batch", fake_generate)

    result = refill_topics(config)

    assert result == ["Новая тема 1", "Новая тема 2"]
    assert "Старая тема" in captured["excluded"]
    assert "Уже опубликовано" in captured["excluded"]
    assert captured["count"] == 3
    text = (tmp_path / "topics.txt").read_text(encoding="utf-8")
    assert "# Автоматически предложено DeepSeek" in text
    assert "Новая тема 2" in text


def test_next_topic_refills_when_queue_is_empty(tmp_path, monkeypatch):
    config = app_config(tmp_path)
    (tmp_path / "topics.txt").write_text("# пусто\n", encoding="utf-8")
    monkeypatch.setattr(
        "shorts_factory.pipeline.refill_topics", lambda _config: ["Тема от DeepSeek"]
    )

    assert next_topic(config) == "Тема от DeepSeek"
