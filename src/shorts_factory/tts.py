from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from .config import AppConfig


def synthesize(config: AppConfig, text: str, output_dir: Path) -> tuple[Path, Path]:
    audio_path = output_dir / "narration.mp3"
    subtitle_path = output_dir / "narration.srt"
    channel = config.section("channel")
    voice = str(channel["voice"])
    rate = str(channel.get("voice_rate", "+15%"))
    asyncio.run(_save(text, voice, rate, audio_path, subtitle_path))
    return audio_path, subtitle_path


async def _save(
    text: str,
    voice: str,
    rate: str,
    audio_path: Path,
    subtitle_path: Path,
) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    submaker = edge_tts.SubMaker()
    with audio_path.open("wb") as audio:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
    subtitle_path.write_text(submaker.get_srt(), encoding="utf-8")
