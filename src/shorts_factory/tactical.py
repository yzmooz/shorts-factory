"""Shared storyboard format and browser-independent animated map rendering."""

from __future__ import annotations

import copy
import json
import math
import subprocess
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .config import AppConfig
from .render import _apply_brand_overlay, insert_midroll, media_duration
from .tts import synthesize

HEROES = {
    "ursa": "Ursa",
    "crystal_maiden": "Crystal Maiden",
    "earthshaker": "Earthshaker",
    "lion": "Lion",
    "nevermore": "Shadow Fiend",
}
COLORS = {"ally": "#65f1c2", "enemy": "#ff6b76", "gold": "#ffd78b"}
MAP_BOX = (36, 290, 1044, 1270)


def default_story() -> dict:
    """An editable example; each graphic is a normal editor object."""

    def hero(asset, point, team="ally", end=None, hidden=False):
        return {
            "type": "hero",
            "asset": asset,
            "x": point[0],
            "y": point[1],
            "team": team,
            "hidden": hidden,
            "path": [list(point), list(end or point)],
        }

    def text(label, x, y, color="gold"):
        return {"type": "text", "text": label, "x": x, "y": y, "color": color}

    camera = {"x": 0.343, "y": 0.396, "zoom": 2.5}
    allies = [hero("ursa", (0.323, 0.405)), hero("crystal_maiden", (0.343, 0.448))]
    enemies = [
        hero("earthshaker", (0.449, 0.334), "enemy", (0.377, 0.367)),
        hero("lion", (0.457, 0.407), "enemy", (0.383, 0.420)),
    ]
    fog = {"type": "fog", "x": 0.452, "y": 0.350, "radius": 0.112, "color": "enemy"}
    ward = {"type": "ward", "x": 0.378, "y": 0.342, "color": "gold"}
    zone = {"type": "zone", "x": 0.378, "y": 0.342, "radius": 0.057, "color": "gold"}
    route = {
        "type": "arrow",
        "points": [[0.448, 0.334], [0.412, 0.347], [0.377, 0.367], [0.35, 0.39]],
        "color": "enemy",
        "reveal": True,
    }
    scenes = [
        (
            "БЕСПЛАТНЫЙ РОШАН?",
            "Враги исчезли. Ты продолжаешь бить Рошана?",
            "ВРАГОВ НЕ ВИДНО",
            allies
            + [
                fog,
                hero("earthshaker", (0.436, 0.34), "enemy", hidden=True),
                text("РОШАН", 0.289, 0.387),
            ],
        ),
        (
            "ЛОВУШКА У ВХОДА",
            "Пока ты смотришь на босса, они обходят вас.",
            "ВЗГЛЯД СО СТОРОНЫ",
            allies + enemies + [route, text("ОБХОД", 0.437, 0.302, "enemy")],
        ),
        (
            "ПЕРЕИГРАЕМ МОМЕНТ",
            "Отмотаем. Сначала обеспечь обзор подхода под прикрытием команды.",
            "ТОТ ЖЕ МОМЕНТ · ДРУГОЕ РЕШЕНИЕ",
            allies + [ward, zone, text("ОБЗОР ПОДХОДА", 0.385, 0.297)],
        ),
        (
            "ЗАМЕТИЛ ПОДХОД?",
            "Заметил врагов? Остановись и оцени, нужна ли драка.",
            "ИНФОРМАЦИЯ ДАЁТ ВЫБОР",
            allies
            + [
                ward,
                zone,
                hero("earthshaker", (0.439, 0.329), "enemy", (0.398, 0.337)),
                text("ВРАГ НА ПОДХОДЕ", 0.423, 0.306, "enemy"),
            ],
        ),
        (
            "ВЫХОД ЕЩЁ ЕСТЬ",
            "Не можешь принять бой — выходи вместе с командой.",
            "НЕ ОТДАВАЙ ЖИЗНИ СЛЕДОМ",
            [
                hero("ursa", (0.323, 0.405), end=(0.287, 0.475)),
                hero("crystal_maiden", (0.343, 0.448), end=(0.304, 0.487)),
                ward,
                {
                    "type": "arrow",
                    "points": [[0.323, 0.42], [0.315, 0.462], [0.287, 0.484]],
                    "color": "ally",
                    "reveal": True,
                },
            ],
        ),
        (
            "ДОБИВАТЬ ИЛИ УЙТИ?",
            "Рискнёшь ради Рошана или сохранишь команду?",
            "А ТЫ КАК ПОСТУПИШЬ?",
            [
                hero("ursa", (0.315, 0.433)),
                hero("crystal_maiden", (0.297, 0.478)),
                hero("earthshaker", (0.395, 0.373), "enemy"),
                text("РИСК", 0.34, 0.369, "enemy"),
                text("ВЫХОД", 0.267, 0.481, "ally"),
            ],
        ),
    ]
    return {
        "version": 1,
        "title": "Бесплатный Рошан — ловушка",
        "map": "terrain-740.jpg",
        "mapVersion": "7.40",
        "scenes": [
            {
                "id": f"scene-{i}",
                "headline": title,
                "narration": narration,
                "caption": caption,
                "duration": 4.5,
                "camera": copy.deepcopy(camera),
                "objects": [
                    {**copy.deepcopy(o), "id": f"obj-{i}-{j}"} for j, o in enumerate(objects)
                ],
            }
            for i, (title, narration, caption, objects) in enumerate(scenes)
        ],
    }


def validate_story(story: dict) -> dict:
    if not isinstance(story, dict) or story.get("version") != 1:
        raise ValueError("Неподдерживаемый формат шаблона")
    if story.get("map") != "terrain-740.jpg":
        raise ValueError("Карта недоступна")
    scenes = story.get("scenes", [])
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 16:
        raise ValueError("Нужно от 1 до 16 сцен")
    kinds = {"hero", "ward", "text", "arrow", "draw", "zone", "fog"}
    for scene in scenes:
        if not 0.5 <= float(scene.get("duration", 0)) <= 30:
            raise ValueError("Длительность сцены должна быть от 0.5 до 30 секунд")
        for key in ("headline", "narration", "caption"):
            if not isinstance(scene.get(key, ""), str) or len(scene.get(key, "")) > 500:
                raise ValueError("Слишком длинный текст сцены")
        cam = scene["camera"]
        values = [float(cam[k]) for k in ("x", "y", "zoom")]
        if not all(math.isfinite(v) for v in values) or not 1 <= values[2] <= 6:
            raise ValueError("Неверная камера")
        if not 0 <= values[0] <= 1 or not 0 <= values[1] <= 1:
            raise ValueError("Камера за пределами карты")
        objects = scene.get("objects", [])
        if not isinstance(objects, list) or len(objects) > 80:
            raise ValueError("Слишком много объектов")
        for obj in objects:
            if obj.get("type") not in kinds:
                raise ValueError("Неизвестный объект карты")
            if obj["type"] == "hero" and obj.get("asset") not in HEROES:
                raise ValueError("Портрет героя недоступен")
            numbers = [obj[k] for k in ("x", "y", "radius") if k in obj]
            for field in ("points", "path"):
                points = obj.get(field, [])
                if not isinstance(points, list) or len(points) > 500:
                    raise ValueError("Слишком длинная линия")
                for point in points:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError("Неверная точка")
                    numbers.extend(point)
            if any(
                not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1
                for v in numbers
            ):
                raise ValueError("Координаты должны быть от 0 до 1")
            if len(str(obj.get("text", ""))) > 100:
                raise ValueError("Подпись слишком длинная")
    return story


def interpolate(points, t):
    if not points:
        return [0, 0]
    if len(points) == 1:
        return points[0]
    t = min(1.0, max(0.0, t))
    distances = [math.dist(a, b) for a, b in pairwise(points)]
    remaining = t * sum(distances)
    for a, b, distance in zip(points, points[1:], distances):
        if distance and remaining <= distance:
            return [a[i] + (b[i] - a[i]) * remaining / distance for i in (0, 1)]
        remaining -= distance
    return points[-1]


@lru_cache(maxsize=32)
def font(size, bold=True):
    names = [
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


class MapPainter:
    """Renders the same editable object model as the canvas editor, without a browser."""

    def __init__(self, root: Path, width=1080):
        self.root, self.width = root, width
        self.scale = width / 1080
        with Image.open(root / "assets/tactical/terrain-740.jpg") as source:
            self.terrain = source.convert("RGB")
            self.terrain.thumbnail((4200, 4200), Image.Resampling.LANCZOS)
        self.portraits = {}
        for slug in HEROES:
            with Image.open(root / f"assets/tactical/{slug}.png") as im:
                self.portraits[slug] = ImageOps.fit(im.convert("RGB"), (90, 90))
        with Image.open(root / "assets/tactical/observer.png") as im:
            self.ward = ImageOps.fit(im.convert("RGBA"), (62, 46))
        with Image.open(root / "assets/ready-helper-banner.png") as im:
            self.brand = im.convert("RGBA")
            self.brand.thumbnail((420, 100), Image.Resampling.LANCZOS)

    def frame(self, story, index, t, *, brand=True):
        scene = story["scenes"][index]
        image = Image.new("RGB", (1080, 1920), "#080f17")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((45, 56, 59, 85), 5, fill="#65f1c2")
        draw.text((77, 55), "DOTA / РАЗБОР МОМЕНТА", font=font(26), fill="#a8bfce")
        self._text(draw, scene["headline"], (45, 118), 78, 980, "#f1f5f6", 2)
        mx, my, ex, ey = MAP_BOX
        mw, mh = ex - mx, ey - my
        cam = scene["camera"]
        zoom = cam["zoom"] * (1 + 0.025 * t)
        cw = 1 / zoom
        ch = cw * mh / mw * self.terrain.width / self.terrain.height
        bounds = (cam["x"] - cw / 2, cam["y"] - ch / 2, cam["x"] + cw / 2, cam["y"] + ch / 2)
        crop = self.terrain.transform(
            (mw, mh),
            Image.Transform.EXTENT,
            tuple(
                bounds[i] * (self.terrain.width if i % 2 == 0 else self.terrain.height)
                for i in range(4)
            ),
            Image.Resampling.BICUBIC,
        )
        crop = ImageEnhance.Brightness(crop).enhance(0.94).convert("RGBA")

        def pos(x, y):
            return ((x - bounds[0]) / cw * mw, (y - bounds[1]) / ch * mh)

        layer = Image.new("RGBA", crop.size)
        ld = ImageDraw.Draw(layer)
        ordered = sorted(
            scene["objects"], key=lambda o: {"arrow": 0, "draw": 0, "text": 2}.get(o["type"], 1)
        )
        for obj in ordered:
            if obj["type"] in {"fog", "zone"}:
                x, y = pos(obj["x"], obj["y"])
                r = obj.get("radius", 0.06) / cw * mw
                rgb = tuple(bytes.fromhex(COLORS.get(obj.get("color"), COLORS["gold"])[1:]))
                if obj["type"] == "fog":
                    ld.ellipse((x - r, y - r, x + r, y + r), fill=(3, 9, 21, 205))
                else:
                    ld.ellipse(
                        (x - r, y - r, x + r, y + r), fill=(*rgb, 38), outline=(*rgb, 150), width=3
                    )
                    pulse = r * (0.83 + 0.17 * ((t * 2) % 1))
                    ld.ellipse(
                        (x - pulse, y - pulse, x + pulse, y + pulse), outline=(*rgb, 90), width=2
                    )
        crop = Image.alpha_composite(crop, layer.filter(ImageFilter.GaussianBlur(3)))
        ld = ImageDraw.Draw(crop)
        for obj in ordered:
            kind = obj["type"]
            color = COLORS.get(obj.get("color", obj.get("team", "ally")), COLORS["ally"])
            if kind in {"draw", "arrow"}:
                points = obj.get("points", [])
                if len(points) < 2:
                    continue
                progress = min(1.0, t * 1.9 + 0.04) if obj.get("reveal") else 1
                full = [pos(*p) for p in points]
                distance = sum(math.dist(a, b) for a, b in pairwise(full)) * progress
                visible = [full[0]]
                for a, b in pairwise(full):
                    length = math.dist(a, b)
                    if distance >= length:
                        visible.append(b)
                        distance -= length
                    else:
                        visible.append(interpolate([a, b], distance / max(length, 0.001)))
                        break
                ld.line(visible, fill="#071018", width=15, joint="curve")
                ld.line(visible, fill=color, width=7, joint="curve")
                if kind == "arrow":
                    a, b = visible[-2:]
                    angle = math.atan2(b[1] - a[1], b[0] - a[0])
                    ld.polygon(
                        [
                            b,
                            (b[0] - 28 * math.cos(angle - 0.5), b[1] - 28 * math.sin(angle - 0.5)),
                            (b[0] - 28 * math.cos(angle + 0.5), b[1] - 28 * math.sin(angle + 0.5)),
                        ],
                        fill=color,
                    )
            elif kind == "hero":
                point = interpolate(obj.get("path", [[obj["x"], obj["y"]]]), t * t * (3 - 2 * t))
                x, y = pos(*point)
                x, y = int(x), int(y)
                ld.ellipse((x - 53, y - 53, x + 53, y + 53), fill="#08131a", outline=color, width=5)
                if obj.get("hidden"):
                    ld.text((x - 16, y - 29), "?", font=font(53), fill=color)
                else:
                    mask = Image.new("L", (90, 90))
                    ImageDraw.Draw(mask).ellipse((0, 0, 89, 89), fill=255)
                    crop.paste(self.portraits[obj["asset"]], (x - 45, y - 45), mask)
                ld.rounded_rectangle((x - 38, y + 56, x + 38, y + 62), 3, fill=color)
            elif kind == "ward":
                x, y = map(int, pos(obj["x"], obj["y"]))
                ld.ellipse(
                    (x - 38, y - 38, x + 38, y + 38),
                    fill="#111b1e",
                    outline=COLORS["gold"],
                    width=3,
                )
                crop.alpha_composite(self.ward, (x - 31, y - 23))
            elif kind == "text":
                x, y = pos(obj["x"], obj["y"])
                label = obj.get("text", "")[:60]
                f = font(29)
                bbox = ld.textbbox((0, 0), label, font=f)
                tw = bbox[2]
                x = min(mw - tw / 2 - 14, max(tw / 2 + 14, x))
                y = min(mh - 48, max(8, y))
                ld.rounded_rectangle(
                    (x - tw / 2 - 12, y - 7, x + tw / 2 + 12, y + 36),
                    10,
                    fill="#0a1723",
                    outline=color,
                    width=2,
                )
                ld.text((x - tw / 2, y), label, font=f, fill=color)
        mask = Image.new("L", (mw, mh))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, mw - 1, mh - 1), 28, fill=255)
        image.paste(crop.convert("RGB"), (mx, my), mask)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(MAP_BOX, 28, outline="#344554", width=2)
        draw.text(
            (mx + 20, my + 20),
            "УЧЕБНАЯ СИТУАЦИЯ",
            font=font(21),
            fill="#f4e8cf",
            stroke_width=2,
            stroke_fill="#0a1723",
        )
        draw.text((48, 1302), "●  ТВОЯ КОМАНДА", font=font(22), fill=COLORS["ally"])
        draw.text((378, 1302), "●  ПРОТИВНИК", font=font(22), fill=COLORS["enemy"])
        draw.text((765, 1302), "КАРТА 7.40", font=font(22), fill="#758d9f")
        self._text(draw, scene["caption"], (48, 1380), 48, 980, COLORS["ally"], 2)
        self._text(draw, scene["narration"], (48, 1510), 35, 960, "#b7c7d3", 3)
        if brand:
            image.paste(self.brand, ((1080 - self.brand.width) // 2, 1700), self.brand)
        if self.width != 1080:
            image = image.resize((self.width, round(1920 * self.scale)), Image.Resampling.LANCZOS)
        return image

    @staticmethod
    def _text(draw, text, xy, size, maxw, color, maxlines):
        f = font(size)
        words = text.split()
        lines = []
        line = ""
        for word in words:
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=f) > maxw and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if len(lines) > maxlines and size > 20:
            return MapPainter._text(draw, text, xy, size - 3, maxw, color, maxlines)
        for i, line in enumerate(lines[:maxlines]):
            draw.text((xy[0], xy[1] + i * int(size * 1.16)), line, font=f, fill=color)


def render_story(config: AppConfig, story: dict, output: Path, progress=lambda _: None) -> Path:
    """Render edited keyframes on a PC or VPS. No browser or graphics card needed."""
    story = copy.deepcopy(validate_story(story))
    output.mkdir(parents=True, exist_ok=True)
    working = output / "assets"
    working.mkdir(exist_ok=True)
    audio = []
    for i, scene in enumerate(story["scenes"]):
        progress(f"Озвучка {i + 1}/{len(story['scenes'])}")
        part = working / f"voice-{i:02d}"
        part.mkdir(exist_ok=True)
        voice, _ = synthesize(config, scene["narration"] or scene["headline"], part)
        # Audio length drives every visual beat; no equal-duration slicing.
        scene["duration"] = media_duration(voice)
        audio.append(voice)
    fps = 24
    painter = MapPainter(config.root)
    segments = []
    for i, (scene, voice) in enumerate(zip(story["scenes"], audio)):
        progress(f"Анимация {i + 1}/{len(story['scenes'])}")
        dest = working / f"scene-{i:02d}.mp4"
        segments.append(dest)
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "1080x1920",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-i",
            str(voice),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(dest),
        ]
        frames = max(1, math.ceil(scene["duration"] * fps))
        with subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            try:
                for n in range(frames):
                    frame = painter.frame(story, i, n / max(1, frames - 1), brand=False)
                    process.stdin.write(frame.tobytes())
                process.stdin.close()
                error = process.stderr.read().decode("utf-8", errors="replace")
                if process.wait():
                    raise RuntimeError(error[-1500:])
            except Exception:
                process.kill()
                process.wait()
                raise
        painter.frame(story, i, 0.6).save(output / f"preview-{i + 1}.jpg", quality=93)
    listing = working / "concat.txt"
    # Generated relative names avoid quoting user-controlled filesystem paths in ffconcat.
    listing.write_text("".join(f"file '{p.name}'\n" for p in segments), encoding="utf-8")
    original = output / "short-original.mp4"
    unbranded = output / "short-unbranded.mp4"
    final = output / "short.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(original),
        ],
        check=True,
    )
    progress("Фирменная вставка и баннер")
    insert_midroll(original, config.root / config.section("render")["midroll_path"], unbranded)
    _apply_brand_overlay(config, unbranded, final)
    original.unlink(missing_ok=True)
    unbranded.unlink(missing_ok=True)
    (output / "storyboard.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    progress("Готово")
    return final
