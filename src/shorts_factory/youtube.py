from __future__ import annotations

import json
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import AppConfig
from .models import VideoPlan
from .stock import description_credits

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
]


def upload_video(
    config: AppConfig,
    plan: VideoPlan,
    video_path: Path,
    *,
    publish_at: str | None = None,
) -> str:
    youtube_config = config.section("youtube")
    privacy = str(youtube_config["privacy"])
    if publish_at and privacy != "private":
        raise ValueError("Для отложенной публикации youtube.privacy должен быть private")
    credentials = _credentials(config)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    status: dict[str, object] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": config.made_for_kids,
        "containsSyntheticMedia": bool(youtube_config.get("contains_synthetic_media", False)),
    }
    if publish_at:
        status["publishAt"] = publish_at
    description = build_description(config, plan, video_path.parent)
    body = {
        "snippet": {
            "title": plan.title,
            "description": description,
            "tags": plan.tags,
            "categoryId": str(youtube_config.get("category_id", "27")),
            "defaultLanguage": str(config.section("channel").get("language", "ru")),
        },
        "status": status,
    }
    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"Загрузка: {progress.progress() * 100:.0f}%")
    return str(response["id"])


def update_video_description(
    config: AppConfig, video_id: str, plan: VideoPlan, output_dir: Path
) -> None:
    credentials = _credentials(config)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = youtube.videos().list(part="snippet", id=video_id).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"YouTube не нашёл видео {video_id}")
    current = items[0]["snippet"]
    snippet: dict[str, object] = {
        "title": current["title"],
        "description": build_description(config, plan, output_dir),
        "categoryId": current["categoryId"],
    }
    for optional in ("tags", "defaultLanguage", "defaultAudioLanguage"):
        if optional in current:
            snippet[optional] = current[optional]
    youtube.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()


def build_description(config: AppConfig, plan: VideoPlan, output_dir: Path) -> str:
    base_description = re.sub(r"(?<!\w)#[\w]+", "", plan.description, flags=re.UNICODE)
    base_description = re.sub(r"[ \t]+", " ", base_description).strip()
    parts = [base_description, " ".join(_hashtags(plan.tags))]
    if bool(config.section("visuals").get("credit_in_description", False)):
        credits = description_credits(output_dir)
        if credits:
            parts.append(credits)
    return "\n\n".join(part for part in parts if part)


def _hashtags(tags: list[str], limit: int = 5) -> list[str]:
    normalized = [_hashtag(tag) for tag in tags]
    candidates = ["shorts"]
    if "наука" in normalized:
        candidates.append("наука")
    candidates.extend(normalized)
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.casefold()
        if candidate and key not in seen:
            result.append(f"#{candidate}")
            seen.add(key)
        if len(result) == limit:
            break
    return result


def _hashtag(value: str) -> str:
    return re.sub(r"[^\w]", "", value.casefold(), flags=re.UNICODE).strip("_")


def _credentials(config: AppConfig) -> Credentials:
    youtube_config = config.section("youtube")
    secrets_path = (config.root / str(youtube_config["client_secrets"])).resolve()
    token_path = (config.root / str(youtube_config["token_file"])).resolve()
    if not secrets_path.exists():
        raise FileNotFoundError(
            f"Нет {secrets_path.name}. Скачайте OAuth Client ID типа Desktop app из Google Cloud."
        )
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path))
        if not credentials.has_scopes(SCOPES):
            credentials = None
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
        credentials = flow.run_local_server(port=0, open_browser=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def load_plan(output_dir: Path) -> VideoPlan:
    data = json.loads((output_dir / "plan.json").read_text(encoding="utf-8"))
    return VideoPlan.from_dict(data)
