from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import init_config, load_config
from .pipeline import build_short, next_topic, refill_topics
from .queue import QueueStore
from .render import probe_video, render_video
from .stock import fetch_scene_images
from .tts import synthesize
from .visuals import create_frames
from .youtube import load_plan, update_video_description, upload_video


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="shorts-factory", description="Генератор и загрузчик YouTube Shorts"
    )
    result.add_argument("--config", default="config.toml", help="путь к config.toml")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="создать config.toml")
    doctor = commands.add_parser("doctor", help="проверить окружение")
    doctor.add_argument("--json", action="store_true")
    generate = commands.add_parser("generate", help="создать черновик ролика")
    generate.add_argument("--topic", required=True)
    generate.add_argument(
        "--demo", action="store_true", help="встроенный сценарий без платного API"
    )
    run_once = commands.add_parser("run-once", help="взять или придумать следующую тему")
    run_once.add_argument("--demo", action="store_true")
    commands.add_parser(
        "auto-run",
        help="самостоятельно создать и загрузить один ролик с лимитами и повтором после сбоя",
    )
    refill = commands.add_parser("refill-topics", help="попросить ИИ пополнить очередь тем")
    refill.add_argument("--count", type=int)
    upload = commands.add_parser("upload", help="загрузить одобренный черновик")
    upload.add_argument("id", type=int, help="ID из команды list")
    upload.add_argument("--publish-at", help="ISO 8601, например 2026-08-03T15:00:00+03:00")
    upload.add_argument(
        "--respect-limits", action="store_true", help="соблюдать автоматические лимиты"
    )
    commands.add_parser("can-upload", help="проверить автоматические лимиты публикации")
    commands.add_parser("list", help="показать очередь")
    inspect = commands.add_parser("inspect", help="проверить итоговый mp4")
    inspect.add_argument("id", type=int)
    rerender = commands.add_parser("rerender", help="пересобрать существующий черновик")
    rerender.add_argument("id", type=int)
    rerender.add_argument("--refresh-images", action="store_true")
    update_description = commands.add_parser(
        "update-description", help="обновить описание загруженного видео"
    )
    update_description.add_argument("id", type=int)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = Path.cwd()
    try:
        if args.command == "init":
            path = init_config(root)
            print(f"Конфигурация: {path}")
            return 0
        config = load_config(Path(args.config))
        queue = QueueStore(config.root / "data" / "queue.db")
        if args.command == "doctor":
            report = _doctor(config)
            print(
                json.dumps(report, ensure_ascii=False, indent=2)
                if args.json
                else _doctor_text(report)
            )
            return 0 if all(value["ok"] for value in report.values()) else 1
        if args.command == "refill-topics":
            topics = refill_topics(config, args.count)
            print(f"Добавлено тем: {len(topics)}")
            return 0
        if args.command == "auto-run":
            return _auto_run(config, queue)
        if args.command in {"generate", "run-once"}:
            auto_upload = args.command == "run-once" and bool(
                config.section("youtube").get("auto_upload", False)
            )
            if auto_upload:
                allowed, reason = queue.can_upload(config)
                if not allowed:
                    print(f"BLOCKED: {reason}")
                    return 0
            topic = args.topic if args.command == "generate" else next_topic(config)
            item_id, output_dir = build_short(config, topic, demo=args.demo)
            print(f"Черновик #{item_id}: {output_dir / 'short.mp4'}")
            if auto_upload:
                plan = load_plan(output_dir)
                youtube_id = upload_video(config, plan, output_dir / "short.mp4")
                queue.mark_uploaded(item_id, youtube_id)
                print(f"Автоматически загружено: https://youtu.be/{youtube_id}")
                return 0
            print("Просмотрите ролик, затем: shorts-factory upload", item_id)
            return 0
        if args.command == "list":
            for row in queue.rows():
                print(
                    f"#{row['id']}  {row['status']:<9}  {row['topic']}  {row['youtube_id'] or ''}"
                )
            return 0
        if args.command == "can-upload":
            allowed, reason = queue.can_upload(config)
            print("OK" if allowed else f"BLOCKED: {reason}")
            return 0 if allowed else 3
        row = queue.get(args.id)
        output_dir = Path(row["output_dir"])
        video_path = output_dir / "short.mp4"
        if args.command == "inspect":
            print(json.dumps(probe_video(video_path), ensure_ascii=False, indent=2))
            return 0
        if args.command == "rerender":
            plan = load_plan(output_dir)
            if args.refresh_images:
                backgrounds = fetch_scene_images(config, plan, output_dir)
            else:
                backgrounds = _stored_backgrounds(output_dir, len(plan.scenes))
            frames = create_frames(config, plan, output_dir, backgrounds=backgrounds)
            audio, _subtitles = synthesize(config, plan.narration, output_dir)
            render_video(config, frames, audio, output_dir)
            print(f"Пересобрано: {video_path}")
            return 0
        if args.command == "update-description":
            if not row["youtube_id"]:
                raise ValueError("Черновик ещё не загружен на YouTube")
            plan = load_plan(output_dir)
            update_video_description(config, str(row["youtube_id"]), plan, output_dir)
            print(f"Описание обновлено: https://youtu.be/{row['youtube_id']}")
            return 0
        if row["status"] == "uploaded":
            raise ValueError(f"Черновик уже загружен: https://youtu.be/{row['youtube_id']}")
        if args.respect_limits:
            allowed, reason = queue.can_upload(config)
            if not allowed:
                raise RuntimeError(reason)
        plan = load_plan(output_dir)
        youtube_id = upload_video(config, plan, video_path, publish_at=args.publish_at)
        queue.mark_uploaded(args.id, youtube_id)
        print(f"Загружено: https://youtu.be/{youtube_id}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI converts operational failures into exit code 2.
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


def _doctor(config) -> dict[str, dict[str, object]]:
    load_dotenv(config.root / ".env")
    youtube_config = config.section("youtube")
    secrets = config.root / str(youtube_config["client_secrets"])
    token_path = config.root / str(youtube_config["token_file"])
    token_has_refresh = False
    if token_path.exists():
        try:
            token_has_refresh = bool(
                json.loads(token_path.read_text(encoding="utf-8")).get("refresh_token")
            )
        except (OSError, ValueError):
            token_has_refresh = False
    provider = str(config.section("content")["provider"])
    key_name = "OPENAI_API_KEY" if provider == "openai" else "DEEPSEEK_API_KEY"
    visual_provider = str(config.section("visuals")["provider"])
    midroll_value = str(config.section("render").get("midroll_path", "")).strip()
    midroll_path = (config.root / midroll_value).resolve() if midroll_value else None
    return {
        "python": {"ok": sys.version_info[:2] >= (3, 11), "value": sys.version.split()[0]},
        "ffmpeg": {
            "ok": shutil.which("ffmpeg") is not None,
            "value": shutil.which("ffmpeg") or "не найден",
        },
        "ffprobe": {
            "ok": shutil.which("ffprobe") is not None,
            "value": shutil.which("ffprobe") or "не найден",
        },
        "oauth": {"ok": secrets.exists(), "value": str(secrets)},
        "youtube_token": {
            "ok": token_has_refresh,
            "value": "refresh token готов" if token_has_refresh else "нет refresh token",
        },
        "llm_api": {
            "ok": bool(os.getenv(key_name, "").strip()),
            "value": f"{provider} ({key_name})",
        },
        "visuals_api": {
            "ok": visual_provider == "gradient" or bool(os.getenv("PEXELS_API_KEY", "").strip()),
            "value": (
                "gradient (API key not needed)"
                if visual_provider == "gradient"
                else "pexels (PEXELS_API_KEY)"
            ),
        },
        "midroll": {
            "ok": bool(midroll_path and midroll_path.is_file()),
            "value": str(midroll_path) if midroll_path else "render.midroll_path не задан",
        },
        "audience": {"ok": config.audience in {"general", "kids"}, "value": config.audience},
    }


def _doctor_text(report: dict[str, dict[str, object]]) -> str:
    return "\n".join(
        f"[{'OK' if row['ok'] else '--'}] {name}: {row['value']}" for name, row in report.items()
    )


def _auto_run(config, queue: QueueStore) -> int:
    """Run one unattended publication and keep a retry marker across process failures."""
    allowed, reason = queue.can_upload(config)
    if not allowed:
        print(f"BLOCKED: {reason}")
        return 0

    pending_path = config.root / "data" / "auto-pending.json"
    item_id: int
    output_dir: Path
    if pending_path.exists():
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        item_id = int(pending["item_id"])
        row = queue.get(item_id)
        if row["status"] == "uploaded":
            pending_path.unlink(missing_ok=True)
            print(f"Восстановлено состояние уже загруженного ролика #{item_id}")
            return 0
        output_dir = Path(row["output_dir"])
        print(f"Повтор загрузки черновика #{item_id}")
    else:
        topic = next_topic(config)
        item_id, output_dir = build_short(config, topic)
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = pending_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"item_id": item_id}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(pending_path)
        print(f"Создан автоматический черновик #{item_id}: {output_dir / 'short.mp4'}")

    plan = load_plan(output_dir)
    youtube_id = upload_video(config, plan, output_dir / "short.mp4")
    queue.mark_uploaded(item_id, youtube_id)
    pending_path.unlink(missing_ok=True)
    _cleanup_uploaded_output(config, output_dir)
    print(f"Автоматически загружено: https://youtu.be/{youtube_id}")
    return 0


def _cleanup_uploaded_output(config, output_dir: Path) -> None:
    """Remove bulky reproducible artifacts after YouTube accepted the upload."""
    if not bool(config.section("automation").get("cleanup_after_upload", False)):
        return
    for directory in ("assets", "frames"):
        shutil.rmtree(output_dir / directory, ignore_errors=True)
    for filename in ("narration.mp3", "narration.srt", "short-original.mp4", "short.mp4"):
        (output_dir / filename).unlink(missing_ok=True)


def _stored_backgrounds(output_dir: Path, scene_count: int) -> list[Path | None]:
    assets = output_dir / "assets"
    extensions = (".mp4", ".jpg", ".jpeg", ".png")
    result: list[Path | None] = []
    for index in range(1, scene_count + 1):
        candidates = [assets / f"scene-{index:02d}{extension}" for extension in extensions]
        result.append(next((path for path in candidates if path.exists()), None))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
