from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .config import AppConfig
from .models import VideoPlan

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"


def fetch_scene_images(config: AppConfig, plan: VideoPlan, output_dir: Path) -> list[Path | None]:
    visuals = config.section("visuals")
    if visuals["provider"] == "gradient":
        return [None] * len(plan.scenes)
    load_dotenv(config.root / ".env")
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Нет PEXELS_API_KEY в .env")

    asset_dir = output_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    credits: list[dict[str, Any]] = []
    paths: list[Path | None] = []
    used_ids: set[int] = set()
    for index, scene in enumerate(plan.scenes, start=1):
        query = _clean_query(scene.visual_hint, plan.topic)
        if bool(visuals.get("prefer_videos", True)):
            video = _search_video(config, api_key, query, used_ids)
            video_file = _best_video_file(video)
            if video and video_file:
                target = asset_dir / f"scene-{index:02d}.mp4"
                max_bytes = int(float(visuals.get("max_video_mb", 28)) * 1024 * 1024)
                if _download(str(video_file["link"]), target, max_bytes=max_bytes):
                    used_ids.add(int(video["id"]))
                    paths.append(target)
                    user = video.get("user") or {}
                    credits.append(
                        {
                            "scene": index,
                            "kind": "video",
                            "query": query,
                            "pexels_id": video["id"],
                            "photographer": user.get("name", ""),
                            "photo_url": video.get("url", ""),
                            "local_file": str(target),
                        }
                    )
                    continue
        photo = _search_photo(config, api_key, query, used_ids)
        if photo is None:
            paths.append(None)
            continue
        used_ids.add(int(photo["id"]))
        image_url = _best_image_url(photo)
        target = asset_dir / f"scene-{index:02d}.jpg"
        if not _download(image_url, target):
            paths.append(None)
            continue
        paths.append(target)
        credits.append(
            {
                "scene": index,
                "kind": "photo",
                "query": query,
                "pexels_id": photo["id"],
                "photographer": photo.get("photographer", ""),
                "photographer_url": photo.get("photographer_url", ""),
                "photo_url": photo.get("url", ""),
                "local_file": str(target),
            }
        )
    (output_dir / "credits.json").write_text(
        json.dumps({"provider": "Pexels", "items": credits}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths


def _search_video(
    config: AppConfig, api_key: str, query: str, used_ids: set[int]
) -> dict[str, Any] | None:
    visuals = config.section("visuals")
    params = urllib.parse.urlencode(
        {
            "query": query,
            "orientation": visuals.get("orientation", "portrait"),
            "size": "medium",
            "per_page": int(visuals.get("results_per_query", 12)),
        }
    )
    payload = _api_json(f"{PEXELS_VIDEO_SEARCH_URL}?{params}", api_key)
    return next(
        (video for video in payload.get("videos", []) if int(video["id"]) not in used_ids),
        None,
    )


def _search_photo(
    config: AppConfig, api_key: str, query: str, used_ids: set[int]
) -> dict[str, Any] | None:
    visuals = config.section("visuals")
    params = urllib.parse.urlencode(
        {
            "query": query,
            "orientation": visuals.get("orientation", "portrait"),
            "size": "large",
            "per_page": int(visuals.get("results_per_query", 12)),
        }
    )
    payload = _api_json(f"{PEXELS_SEARCH_URL}?{params}", api_key)
    photos = payload.get("photos", [])
    return next((photo for photo in photos if int(photo["id"]) not in used_ids), None)


def _api_json(url: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Authorization": api_key, "User-Agent": "ShortsFactory/0.2"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("Pexels отклонил API-ключ (HTTP 401)") from exc
        if exc.code == 403:
            raise RuntimeError(
                "Pexels запретил API-запрос (HTTP 403). Проверьте активацию ключа в Pexels."
            ) from exc
        raise RuntimeError(f"Pexels API вернул HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Не удалось подключиться к Pexels: {exc}") from exc
    return payload


def _best_image_url(photo: dict[str, Any]) -> str:
    sources = photo.get("src", {})
    for name in ("large2x", "original", "portrait", "large"):
        if sources.get(name):
            return str(sources[name])
    raise RuntimeError("Pexels не вернул URL изображения")


def _best_video_file(video: dict[str, Any] | None) -> dict[str, Any] | None:
    if not video:
        return None
    candidates = [
        item
        for item in video.get("video_files", [])
        if item.get("link")
        and item.get("file_type") == "video/mp4"
        and int(item.get("width") or 0) > 0
        and int(item.get("height") or 0) > int(item.get("width") or 0)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            0 if 720 <= int(item["width"]) <= 1080 else 1,
            abs(int(item["width"]) - 1080),
            -int(item["height"]),
        ),
    )


def _download(url: str, target: Path, *, max_bytes: int = 32 * 1024 * 1024) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": "ShortsFactory/0.1"})
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            declared = int(response.headers.get("Content-Length", "0") or 0)
            if declared > max_bytes:
                return False
            total = 0
            with temporary.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        return False
                    handle.write(chunk)
            temporary.replace(target)
            return True
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Не удалось скачать изображение Pexels: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _clean_query(hint: str, topic: str) -> str:
    query = " ".join(hint.replace(":", " ").split()).strip()
    return query[:100] or topic


def description_credits(output_dir: Path) -> str:
    path = output_dir / "credits.json"
    if not path.exists():
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = sorted(
        {item.get("photographer", "").strip() for item in payload.get("items", [])} - {""}
    )
    suffix = f" Photos: {', '.join(names)}." if names else ""
    return f"Visuals provided by Pexels.{suffix} https://www.pexels.com"
