from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class Scene:
    narration: str
    screen_text: str
    visual_hint: str = ""


@dataclass(slots=True)
class VideoPlan:
    topic: str
    title: str
    description: str
    scenes: list[Scene]
    tags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> VideoPlan:
        scenes = [Scene(**scene) for scene in value["scenes"]]
        return cls(
            topic=value["topic"],
            title=value["title"],
            description=value["description"],
            scenes=scenes,
            tags=list(value.get("tags", [])),
        )

    @property
    def narration(self) -> str:
        # Paragraph boundaries make Edge TTS pause naturally between visual beats.
        return "\n\n".join(scene.narration.strip() for scene in self.scenes)
