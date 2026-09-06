from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AppConfig:
    root: Path
    raw: dict[str, Any]

    @property
    def audience(self) -> str:
        return str(self.raw["channel"]["audience"])

    @property
    def made_for_kids(self) -> bool:
        return self.audience == "kids"

    def section(self, name: str) -> dict[str, Any]:
        return self.raw[name]


def init_config(root: Path) -> Path:
    destination = root / "config.toml"
    if destination.exists():
        return destination
    source = root / "config.example.toml"
    if not source.exists():
        raise FileNotFoundError("config.example.toml не найден")
    shutil.copyfile(source, destination)
    return destination


def load_config(path: Path) -> AppConfig:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Нет {path}. Выполните: shorts-factory init")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    _validate(raw)
    return AppConfig(root=path.parent, raw=raw)


def _validate(raw: dict[str, Any]) -> None:
    required = {"channel", "content", "visuals", "render", "youtube", "automation"}
    missing = required.difference(raw)
    if missing:
        raise ValueError(f"В конфигурации отсутствуют секции: {', '.join(sorted(missing))}")
    audience = raw["channel"].get("audience")
    if audience not in {"general", "kids"}:
        raise ValueError("channel.audience должен быть 'general' или 'kids'")
    provider = raw["content"].get("provider")
    if provider not in {"deepseek", "openai"}:
        raise ValueError("content.provider должен быть 'deepseek' или 'openai'")
    visual_provider = raw["visuals"].get("provider")
    if visual_provider not in {"gradient", "pexels", "dota"}:
        raise ValueError("visuals.provider должен быть 'gradient', 'pexels' или 'dota'")
    privacy = raw["youtube"].get("privacy")
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("youtube.privacy должен быть private, unlisted или public")
    if int(raw["automation"].get("max_uploads_per_day", 0)) not in range(1, 5):
        raise ValueError("max_uploads_per_day должен быть от 1 до 4")
    fresh_every = int(raw["content"].get("fresh_topic_every", 4))
    if fresh_every not in range(1, 21):
        raise ValueError("content.fresh_topic_every должен быть от 1 до 20")
