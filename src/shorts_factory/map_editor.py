"""Local-only map editor, persistent templates and background MP4 rendering."""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import load_config
from .tactical import HEROES, default_story, render_story, validate_story

logger = logging.getLogger(__name__)


def serve(config_path: Path, port=8790):
    config = load_config(config_path)
    root = config.root
    templates = root / "data/tactical-templates"
    templates.mkdir(parents=True, exist_ok=True)
    jobs = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, payload, status=200):
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/default":
                return self.respond(default_story())
            if path == "/api/heroes":
                return self.respond(HEROES)
            if path == "/api/templates":
                result = []
                for file in templates.glob("*.json"):
                    try:
                        data = json.loads(file.read_text(encoding="utf-8"))
                        result.append({"id": file.stem, "title": data.get("title", file.stem)})
                    except (ValueError, OSError):
                        continue
                return self.respond(result)
            if re.fullmatch(r"/api/templates/[a-f0-9]{32}", path):
                target = templates / f"{path.rsplit('/', 1)[-1]}.json"
                if target.is_file():
                    return self.respond(json.loads(target.read_text(encoding="utf-8")))
                return self.respond({"error": "Шаблон не найден"}, 404)
            if re.fullmatch(r"/api/jobs/[a-f0-9]{32}", path):
                with lock:
                    job = jobs.get(path.rsplit("/", 1)[-1])
                return self.respond(job or {"error": "Задание не найдено"}, 200 if job else 404)
            if path in ("/", "/index.html"):
                target = root / "editor/index.html"
            elif path.startswith("/editor/"):
                target = root / path.lstrip("/")
                if target.resolve().parent != (root / "editor").resolve():
                    return self.send_error(404)
            elif (
                re.fullmatch(r"/assets/tactical/[a-zA-Z0-9_.-]+", path)
                or path == "/assets/ready-helper-banner.png"
            ):
                target = root / path.lstrip("/")
            elif re.fullmatch(r"/renders/[a-f0-9]{32}/short.mp4", path):
                target = root / "output" / f"map-{path.split('/')[2]}" / "short.mp4"
            else:
                return self.send_error(404)
            if not target.is_file():
                return self.send_error(404)
            size = target.stat().st_size
            start = 0
            end = size - 1
            status = 200
            range_header = self.headers.get("Range", "")
            if range_header:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
                if not match:
                    return self.send_error(416)
                start = int(match[1])
                end = min(end, int(match[2])) if match[2] else end
                if start > end:
                    return self.send_error(416)
                status = 206
            self.send_response(status)
            self.send_header(
                "Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                with target.open("rb") as handle:
                    handle.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = handle.read(min(remaining, 1024 * 256))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                return self.respond({"error": "Недопустимый источник запроса"}, 403)
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 2_000_000:
                    return self.respond({"error": "Слишком большой шаблон"}, 400)
                payload = json.loads(self.rfile.read(size))
                story = validate_story(payload["story"])
                if self.path == "/api/save":
                    template_id = payload.get("id")
                    if not template_id or not re.fullmatch(r"[a-f0-9]{32}", template_id):
                        template_id = uuid.uuid4().hex
                    dest = templates / f"{template_id}.json"
                    temp = dest.with_suffix(".tmp")
                    temp.write_text(
                        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    temp.replace(dest)
                    return self.respond({"id": template_id, "title": story["title"]})
                if self.path == "/api/render":
                    with lock:
                        if any(j["status"] == "running" for j in jobs.values()):
                            return self.respond({"error": "Один ролик уже собирается"}, 409)
                        job_id = uuid.uuid4().hex
                        jobs[job_id] = {"status": "running", "message": "Подготовка озвучки"}

                    def run():
                        def progress(message):
                            with lock:
                                jobs[job_id]["message"] = message

                        try:
                            output = render_story(
                                config, story, root / "output" / f"map-{job_id}", progress
                            )
                            with lock:
                                jobs[job_id] = {
                                    "status": "done",
                                    "message": "Готово",
                                    "url": f"/renders/{job_id}/short.mp4",
                                    "path": str(output),
                                }
                        except Exception as exc:
                            logger.exception("Map render failed")
                            with lock:
                                jobs[job_id] = {"status": "error", "message": str(exc)}

                    threading.Thread(target=run, daemon=True).start()
                    return self.respond({"id": job_id})
                return self.respond({"error": "Неизвестное действие"}, 404)
            except (KeyError, TypeError, ValueError) as exc:
                return self.respond({"error": str(exc)}, 400)

    print(f"Dota Map Studio: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dota Map Studio")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    serve(args.config, args.port)
