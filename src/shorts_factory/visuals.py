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


def create_frames(
    config: AppConfig,
    plan: VideoPlan,
    output_dir: Path,
    *,
    backgrounds: list[Path | None] | None = None,
) -> list[Path]:
    render = config.section("render")
    width, height = int(render["width"]), int(render["height"])
    seed = int(hashlib.sha256(plan.topic.encode("utf-8")).hexdigest()[:8], 16)
    randomizer = random.Random(seed)
    frame_dir = output_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    background_dir = frame_dir / "backgrounds"
    overlay_dir = frame_dir / "overlays"
    background_dir.mkdir(exist_ok=True)
    overlay_dir.mkdir(exist_ok=True)
    result: list[Path] = []
    render_sources: list[str] = []
    overlay_paths: list[str] = []
    for index, scene in enumerate(plan.scenes):
        palette = PALETTES[index % len(PALETTES)]
        background = backgrounds[index] if backgrounds and index < len(backgrounds) else None
        if background is None:
            image = _gradient(width, height, palette[0], palette[1])
        else:
            image = _photo_background(background, width, height)
        background_path = background_dir / f"scene-{index + 1:02d}.jpg"
        image.save(background_path, quality=94)
        render_source = background if background and background.suffix.lower() == ".mp4" else background_path

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        if background is None:
            _decorations(draw, width, height, palette[2], randomizer)
        title_size = max(18, width // (12 if index == 0 else 13))
        title_font = _font(config, title_size, bold=True)

        _draw_title_card(overlay, config, scene.screen_text, title_font, index == 0)

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
    if path.suffix.lower() == ".mp4":
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


def _video_poster(path: Path) -> Image.Image:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "0.4",
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
    is_hook: bool,
) -> None:
    width, height = image.size
    measure = ImageDraw.Draw(image)
    card_margin = max(12, width // 15)
    horizontal_padding = max(20, width // 9)
    text_width = width - card_margin * 2 - horizontal_padding
    lines = _wrap_text(measure, text.upper(), font, text_width)
    line_height = int(font.size * 1.12)
    block_height = len(lines) * line_height
    card_bottom = int(height * (0.70 if is_hook else 0.68))
    vertical_padding = max(28, height // 17)
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
        fill=(3, 10, 22, 138),
        outline=(103, 232, 249, 62),
        width=2,
    )
    y = card_top + vertical_padding // 2
    for line_index, line in enumerate(lines):
        fill = (
            (103, 232, 249, 255)
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
