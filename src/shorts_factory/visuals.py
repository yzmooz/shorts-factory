from __future__ import annotations

import hashlib
import io
import json
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .config import AppConfig
from .models import VideoPlan

PALETTES = [
    ("#071A2B", "#0E7490", "#67E8F9", "#F8FAFC"),
    ("#1F1147", "#7E22CE", "#E879F9", "#FFFFFF"),
    ("#31110B", "#C2410C", "#FDBA74", "#FFF7ED"),
    ("#052E16", "#15803D", "#86EFAC", "#F0FDF4"),
]
ACCENT = "#FFD166"
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}


def create_frames(
    config: AppConfig,
    plan: VideoPlan,
    output_dir: Path,
    *,
    backgrounds: list[Path | None] | None = None,
) -> list[Path]:
    render = config.section("render")
    width, height = int(render["width"]), int(render["height"])
    visual_provider = str(config.raw.get("visuals", {}).get("provider", "gradient"))
    seed = int(hashlib.sha256(plan.topic.encode("utf-8")).hexdigest()[:8], 16)
    randomizer = random.Random(seed)
    frame_dir = output_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    background_dir = frame_dir / "backgrounds"
    overlay_dir = frame_dir / "overlays"
    source_dir = frame_dir / "sources"
    background_dir.mkdir(exist_ok=True)
    overlay_dir.mkdir(exist_ok=True)
    source_dir.mkdir(exist_ok=True)
    result: list[Path] = []
    render_sources: list[str] = []
    overlay_paths: list[str] = []
    for index, scene in enumerate(plan.scenes):
        palette = PALETTES[index % len(PALETTES)]
        background = backgrounds[index] if backgrounds and index < len(backgrounds) else None
        if visual_provider == "dota" and scene.visual_hint.casefold().startswith("map:"):
            image = _dota_map_background(
                width, height, scene.visual_hint.partition(":")[2], index
            )
            background = None
        elif background is None:
            image = _gradient(width, height, palette[0], palette[1])
        elif visual_provider == "dota" and background.suffix.lower() == ".png":
            image = _dota_item_background(
                background, width, height, scene.visual_hint
            )
        elif visual_provider == "dota" and background.suffix.lower() in VIDEO_SUFFIXES:
            image = _dota_backdrop(width, height, index)
        else:
            image = _photo_background(background, width, height)
        background_path = background_dir / f"scene-{index + 1:02d}.jpg"
        image.save(background_path, quality=94)
        render_source: Path = background_path
        if background and background.suffix.lower() in VIDEO_SUFFIXES:
            if visual_provider == "dota":
                animated_source = source_dir / f"scene-{index + 1:02d}.mp4"
                if _dota_hero_clip(
                    background, background_path, animated_source, width, height
                ):
                    render_source = animated_source
                else:
                    image = _dota_hero_poster(background, image)
                    image.save(background_path, quality=94)
            else:
                render_source = background

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        if background is None:
            _decorations(draw, width, height, palette[2], randomizer)
        title_size = max(18, width // (12 if index == 0 else 13))
        title_font = _font(config, title_size, bold=True)

        _draw_asset_badge(overlay, config, scene.visual_hint)
        _draw_title_card(overlay, config, scene.screen_text, title_font, index)

        overlay_path = overlay_dir / f"scene-{index + 1:02d}.png"
        overlay.save(overlay_path)
        path = frame_dir / f"scene-{index + 1:02d}.png"
        Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").save(path, quality=95)
        result.append(path)
        render_sources.append(str(render_source))
        overlay_paths.append(str(overlay_path))
    (frame_dir / "visuals.json").write_text(
        json.dumps({"sources": render_sources, "overlays": overlay_paths}, ensure_ascii=False),
        encoding="utf-8",
    )
    return result


def _photo_background(path: Path, width: int, height: int) -> Image.Image:
    if path.suffix.lower() in VIDEO_SUFFIXES:
        source = _video_poster(path)
    else:
        source = Image.open(path)
    with source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    cropped = ImageEnhance.Color(cropped).enhance(1.08)
    cropped = ImageEnhance.Contrast(cropped).enhance(1.06).convert("RGBA")
    tinted = Image.alpha_composite(cropped, Image.new("RGBA", cropped.size, (4, 12, 24, 24)))

    # A smooth cinematic gradient leaves the subject visible while protecting the UI areas.
    shade = Image.new("RGBA", (1, height), (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    for y in range(height):
        position = y / max(1, height - 1)
        if position < 0.22:
            alpha = round(88 - position / 0.22 * 48)
        elif position < 0.52:
            alpha = 40
        else:
            alpha = round(40 + (position - 0.52) / 0.48 * 118)
        shade_draw.point((0, y), fill=(0, 0, 0, alpha))
    shade = shade.resize((width, height))
    return Image.alpha_composite(tinted, shade).convert("RGB")


def _dota_backdrop(width: int, height: int, index: int) -> Image.Image:
    """Build a clean stage so a Dota asset reads instantly on a phone."""
    base = _gradient(width, height, "#070B0E", "#170805").convert("RGBA")
    base = Image.alpha_composite(base, _dota_atmosphere(width, height, index))
    grid = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grid, "RGBA")
    center = (width // 2, int(height * 0.30))
    for radius, alpha in ((390, 22), (300, 30), (210, 38)):
        draw.ellipse(
            (
                center[0] - radius,
                center[1] - radius,
                center[0] + radius,
                center[1] + radius,
            ),
            outline=(232, 151, 73, alpha),
            width=3,
        )
    draw.line((0, int(height * 0.47), width, int(height * 0.47)), fill=(255, 190, 90, 26), width=2)
    return Image.alpha_composite(base, grid).convert("RGB")


def _dota_item_background(
    path: Path, width: int, height: int, visual_hint: str
) -> Image.Image:
    """Turn a small official item icon into a deliberate Dota-style poster."""
    base = _dota_backdrop(width, height, 0).convert("RGBA")
    with Image.open(path) as source:
        icon = ImageOps.exif_transpose(source).convert("RGBA")
    scale = min(int(width * 0.36) / icon.width, int(height * 0.18) / icon.height)
    icon = icon.resize(
        (max(1, round(icon.width * scale)), max(1, round(icon.height * scale))),
        Image.Resampling.NEAREST,
    )
    x = (width - icon.width) // 2
    y = int(height * 0.19)
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    card_padding_x = 58
    card_padding_y = 52
    card = (
        x - card_padding_x,
        y - card_padding_y,
        x + icon.width + card_padding_x,
        y + icon.height + card_padding_y,
    )
    glow_draw.rounded_rectangle(
        card,
        radius=38,
        fill=(6, 12, 14, 225),
        outline=(242, 156, 67, 205),
        width=5,
    )
    padding = max(icon.width, icon.height) // 3
    glow_draw.ellipse(
        (x - padding, y - padding, x + icon.width + padding, y + icon.height + padding),
        fill=(240, 90, 35, 85),
    )
    soft_glow = glow.filter(ImageFilter.GaussianBlur(50))
    base = Image.alpha_composite(base, soft_glow)
    base = Image.alpha_composite(base, glow)
    shadow = Image.new("RGBA", icon.size, (0, 0, 0, 180)).filter(
        ImageFilter.GaussianBlur(10)
    )
    base.alpha_composite(shadow, (x + 8, y + 12))
    base.alpha_composite(icon, (x, y))
    draw = ImageDraw.Draw(base, "RGBA")
    label = _asset_label(visual_hint)
    font = _fallback_font(max(24, width // 25), bold=True)
    bounds = draw.textbbox((0, 0), label, font=font)
    label_x = (width - (bounds[2] - bounds[0])) // 2
    label_y = card[3] + 42
    draw.text(
        (label_x, label_y),
        label,
        font=font,
        fill=(255, 221, 164, 245),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 210),
    )
    return base.convert("RGB")


def _dota_map_background(
    width: int, height: int, mode: str, scene_index: int
) -> Image.Image:
    """Draw a phone-readable tactical map instead of an unrelated hero render."""
    base = _dota_backdrop(width, height, scene_index).convert("RGBA")
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")
    map_size = int(width * 0.78)
    left = (width - map_size) // 2
    top = int(height * 0.075)
    right = left + map_size
    bottom = top + map_size
    draw.rounded_rectangle(
        (left - 18, top - 18, right + 18, bottom + 18),
        radius=42,
        fill=(2, 7, 7, 235),
        outline=(232, 158, 76, 190),
        width=5,
    )
    draw.rounded_rectangle(
        (left, top, right, bottom), radius=28, fill=(17, 38, 29, 255)
    )

    # River and three lanes: schematic, deliberately clearer than a tiny minimap screenshot.
    river = [
        (left, top + int(map_size * 0.67)),
        (left + int(map_size * 0.18), top + int(map_size * 0.58)),
        (left + int(map_size * 0.42), top + int(map_size * 0.51)),
        (left + int(map_size * 0.68), top + int(map_size * 0.40)),
        (right, top + int(map_size * 0.30)),
    ]
    draw.line(river, fill=(54, 121, 143, 210), width=max(20, width // 28), joint="curve")
    lane_color = (186, 176, 134, 105)
    draw.line((left + 55, bottom - 60, right - 55, top + 60), fill=lane_color, width=12)
    draw.line(
        (left + 60, bottom - 70, left + 70, top + 80, right - 65, top + 60),
        fill=lane_color,
        width=9,
        joint="curve",
    )
    draw.line(
        (left + 60, bottom - 70, right - 75, bottom - 70, right - 65, top + 60),
        fill=lane_color,
        width=9,
        joint="curve",
    )
    draw.ellipse(
        (left + 35, bottom - 115, left + 135, bottom - 15),
        fill=(56, 190, 105, 230),
        outline=(158, 255, 190, 230),
        width=5,
    )
    draw.ellipse(
        (right - 135, top + 15, right - 35, top + 115),
        fill=(210, 65, 61, 230),
        outline=(255, 151, 139, 230),
        width=5,
    )

    roshan = (left + int(map_size * 0.42), top + int(map_size * 0.50))
    draw.ellipse(
        (roshan[0] - 66, roshan[1] - 66, roshan[0] + 66, roshan[1] + 66),
        fill=(68, 25, 15, 245),
        outline=(255, 163, 65, 255),
        width=8,
    )
    roshan_font = _fallback_font(max(20, width // 34), bold=True)
    roshan_text = "ROSHAN"
    bounds = draw.textbbox((0, 0), roshan_text, font=roshan_font)
    draw.text(
        (roshan[0] - (bounds[2] - bounds[0]) // 2, roshan[1] - roshan_font.size // 2),
        roshan_text,
        font=roshan_font,
        fill=(255, 222, 165, 255),
    )

    normalized = mode.casefold()
    ward = (roshan[0] + 120, roshan[1] - 115)
    if any(marker in normalized for marker in ("ward", "vision", "safe", "choice")):
        radius = 145
        draw.ellipse(
            (ward[0] - radius, ward[1] - radius, ward[0] + radius, ward[1] + radius),
            fill=(252, 202, 75, 36),
            outline=(255, 218, 112, 160),
            width=5,
        )
        draw.ellipse(
            (ward[0] - 25, ward[1] - 25, ward[0] + 25, ward[1] + 25),
            fill=(255, 215, 78, 255),
            outline=(255, 247, 201, 255),
            width=4,
        )
        draw.line((ward[0], ward[1] + 20, ward[0], ward[1] + 62), fill=(255, 225, 111, 255), width=8)

    enemy_points = (
        (roshan[0] + 200, roshan[1] - 8),
        (roshan[0] + 155, roshan[1] + 90),
        (roshan[0] + 245, roshan[1] + 110),
    )
    if any(marker in normalized for marker in ("danger", "loss", "choice")):
        for x, y in enemy_points:
            draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill=(242, 70, 65, 255))
        draw.line(
            (enemy_points[0][0], enemy_points[0][1], roshan[0] + 60, roshan[1]),
            fill=(255, 85, 75, 230),
            width=12,
        )
        arrow_tip = (roshan[0] + 50, roshan[1])
        draw.polygon(
            (
                arrow_tip,
                (arrow_tip[0] + 36, arrow_tip[1] - 26),
                (arrow_tip[0] + 36, arrow_tip[1] + 26),
            ),
            fill=(255, 85, 75, 240),
        )

    if "loss" in normalized:
        skull_font = _fallback_font(max(54, width // 12), bold=True)
        draw.text(
            (roshan[0] - 25, roshan[1] + 90),
            "×",
            font=skull_font,
            fill=(255, 76, 69, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 230),
        )

    return Image.alpha_composite(base, layer).convert("RGB")


def _dota_hero_clip(
    hero_path: Path,
    backdrop_path: Path,
    target: Path,
    width: int,
    height: int,
) -> bool:
    """Composite an official transparent hero render without cropping the hero."""
    hero_size = min(int(width * 0.88), int(height * 0.49))
    hero_y = max(25, int(height * 0.035))
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-loop",
        "1",
        "-framerate",
        "30",
        "-i",
        str(backdrop_path),
        "-stream_loop",
        "-1",
        "-c:v",
        "libvpx-vp9",
        "-i",
        str(hero_path),
        "-filter_complex",
        (
            f"[0:v]scale={width}:{height},format=rgba[stage];"
            f"[1:v]scale={hero_size}:{hero_size}:force_original_aspect_ratio=decrease,"
            "format=rgba[hero];"
            f"[stage][hero]overlay=x=(W-w)/2:y={hero_y}:format=auto,format=yuv420p[v]"
        ),
        "-map",
        "[v]",
        "-t",
        "4",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(target),
    ]
    try:
        subprocess.run(command, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        target.unlink(missing_ok=True)
        return False
    return target.is_file()


def _dota_hero_poster(path: Path, backdrop: Image.Image) -> Image.Image:
    """Static fallback for ffmpeg builds that cannot decode VP9 alpha."""
    with _video_poster(path) as source:
        hero = source.convert("RGBA")
    size = min(int(backdrop.width * 0.88), int(backdrop.height * 0.49))
    hero.thumbnail((size, size), Image.Resampling.LANCZOS)
    stage = backdrop.convert("RGBA")
    stage.alpha_composite(hero, ((stage.width - hero.width) // 2, int(stage.height * 0.035)))
    return stage.convert("RGB")


def _video_poster(path: Path) -> Image.Image:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "0.4",
            *(["-c:v", "libvpx-vp9"] if path.suffix.lower() == ".webm" else []),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return Image.open(io.BytesIO(result.stdout))


def _draw_title_card(
    image: Image.Image,
    config: AppConfig,
    text: str,
    font: ImageFont.FreeTypeFont,
    scene_index: int,
) -> None:
    width, height = image.size
    is_hook = scene_index == 0
    measure = ImageDraw.Draw(image)
    card_margin = max(12, width // 15)
    horizontal_padding = max(20, width // 9)
    text_width = width - card_margin * 2 - horizontal_padding
    lines = _wrap_text(measure, text.upper(), font, text_width)
    line_height = int(font.size * 1.12)
    block_height = len(lines) * line_height
    card_bottom = int(height * 0.70)
    vertical_padding = max(24, height // 24)
    card_top = card_bottom - block_height - vertical_padding
    card = (card_margin, card_top, width - card_margin, card_bottom)
    radius = max(10, width // 22)

    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (card[0] + 8, card[1] + 12, card[2] + 8, card[3] + 12),
        radius=radius,
        fill=(0, 0, 0, 128),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    image.paste(Image.alpha_composite(image.convert("RGBA"), shadow))

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        card,
        radius=radius,
        fill=(3, 8, 14, 205),
        outline=(240, 148, 70, 155),
        width=3,
    )
    phase_labels = ("ПРОБЛЕМА", "СТАВКА", "ЧТО ДЕЛАТЬ", "РЕШЕНИЕ", "ПОЧЕМУ", "ТВОЙ ВЫБОР")
    phase_colors = (
        (242, 82, 72, 255),
        (245, 158, 61, 255),
        (75, 196, 126, 255),
        (75, 196, 126, 255),
        (94, 171, 255, 255),
        (174, 112, 255, 255),
    )
    phase = phase_labels[min(scene_index, len(phase_labels) - 1)]
    phase_color = phase_colors[min(scene_index, len(phase_colors) - 1)]
    phase_font = _font(config, max(22, width // 31), bold=True)
    phase_bounds = draw.textbbox((0, 0), phase, font=phase_font)
    phase_width = phase_bounds[2] - phase_bounds[0]
    phase_height = phase_bounds[3] - phase_bounds[1]
    pill = (
        width // 2 - phase_width // 2 - 28,
        card_top - phase_height - 42,
        width // 2 + phase_width // 2 + 28,
        card_top - 18,
    )
    draw.rounded_rectangle(pill, radius=18, fill=(5, 9, 14, 235), outline=phase_color, width=3)
    draw.text(
        ((width - phase_width) // 2, pill[1] + 8),
        phase,
        font=phase_font,
        fill=phase_color,
    )
    y = card_top + vertical_padding // 2
    for line_index, line in enumerate(lines):
        fill = (
            (255, 184, 90, 255)
            if len(lines) > 1 and line_index == len(lines) - 1 and not is_hook
            else (
                255,
                255,
                255,
                245,
            )
        )
        bounds = draw.textbbox((0, 0), line, font=font)
        line_width = bounds[2] - bounds[0]
        x = (width - line_width) // 2
        draw.text((x + 5, y + 7), line, font=font, fill=(0, 0, 0, 160))
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=max(1, font.size // 34),
            stroke_fill=(5, 15, 30, 190),
        )
        y += line_height


def _draw_asset_badge(image: Image.Image, config: AppConfig, visual_hint: str) -> None:
    if visual_hint.casefold().startswith(("item:", "map:")):
        return
    label = _asset_label(visual_hint)
    if not label:
        return
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    font = _font(config, max(20, width // 34), bold=True)
    bounds = draw.textbbox((0, 0), label, font=font)
    text_width = bounds[2] - bounds[0]
    y = int(height * 0.48)
    card = (width // 2 - text_width // 2 - 24, y, width // 2 + text_width // 2 + 24, y + font.size + 24)
    draw.rounded_rectangle(card, radius=16, fill=(4, 9, 13, 215), outline=(255, 188, 92, 140), width=2)
    draw.text(((width - text_width) // 2, y + 9), label, font=font, fill=(255, 221, 164, 255))


def _asset_label(visual_hint: str) -> str:
    raw = visual_hint.partition(":")[2].strip().casefold()
    aliases = {
        "ward_observer": "OBSERVER WARD",
        "ward_sentry": "SENTRY WARD",
        "black_king_bar": "BLACK KING BAR",
        "blink": "BLINK DAGGER",
        "aegis": "AEGIS",
        "cheese": "CHEESE",
        "nevermore": "SHADOW FIEND",
        "skeleton_king": "WRAITH KING",
        "windrunner": "WINDRANGER",
    }
    return aliases.get(raw, raw.replace("_", " ").upper())


def _fallback_font(size: int, *, bold: bool) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\seguisb.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default(size=size)


def _gradient(width: int, height: int, top_hex: str, bottom_hex: str) -> Image.Image:
    top = tuple(bytes.fromhex(top_hex.lstrip("#")))
    bottom = tuple(bytes.fromhex(bottom_hex.lstrip("#")))
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    return image


def _dota_atmosphere(width: int, height: int, index: int) -> Image.Image:
    """Add a restrained Radiant/Dire atmosphere over official hero renders."""
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow, "RGBA")
    if index % 2:
        left, right = (65, 174, 104, 70), (213, 66, 48, 88)
    else:
        left, right = (213, 66, 48, 78), (65, 174, 104, 76)
    draw.ellipse((-width // 2, -height // 6, width // 2, height // 2), fill=left)
    draw.ellipse(
        (width // 2, height // 6, width + width // 2, int(height * 0.82)), fill=right
    )
    glow = glow.filter(ImageFilter.GaussianBlur(max(70, width // 7)))

    lines = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(lines, "RGBA")
    line_draw.line(
        (0, int(height * 0.12), int(width * 0.32), 0), fill=(236, 122, 62, 46), width=4
    )
    line_draw.line(
        (width, int(height * 0.18), int(width * 0.72), 0),
        fill=(87, 190, 125, 42),
        width=4,
    )
    line_draw.line(
        (0, int(height * 0.88), int(width * 0.28), height),
        fill=(87, 190, 125, 32),
        width=3,
    )
    return Image.alpha_composite(glow, lines)


def _decorations(
    draw: ImageDraw.ImageDraw, width: int, height: int, accent: str, rng: random.Random
) -> None:
    rgba = _hex_rgba(accent, 28)
    for _ in range(14):
        radius = rng.randint(50, 260)
        x, y = rng.randint(-100, width), rng.randint(-100, height)
        draw.ellipse((x, y, x + radius, y + radius), fill=rgba)
    for offset in range(-height, width, 180):
        draw.line((offset, 0, offset + height, height), fill=_hex_rgba(accent, 18), width=18)


def _font(config: AppConfig, size: int, *, bold: bool) -> ImageFont.FreeTypeFont:
    configured = str(config.section("render").get("font_path", "")).strip()
    candidates = [
        configured,
        r"C:\Windows\Fonts\seguisb.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default(size=size)


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if current and bbox[2] - bbox[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:5]


def _hex_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    rgb = tuple(bytes.fromhex(value.lstrip("#")))
    return rgb[0], rgb[1], rgb[2], alpha
