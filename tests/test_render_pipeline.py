import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw

from shorts_factory.config import AppConfig
from shorts_factory.models import Scene, VideoPlan
from shorts_factory.render import media_info, render_video
from shorts_factory.visuals import create_frames

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)


def _tone(path, duration, frequency=440):
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
            "-c:a",
            "libmp3lame",
            str(path),
        ],
        check=True,
    )


def _clip(path, duration):
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:s=180x320:r=15:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=880:sample_rate=48000:duration={duration}",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def test_render_uses_static_overlays_and_mandatory_midroll(tmp_path):
    assets = tmp_path / "assets"
    output = tmp_path / "output"
    assets.mkdir()
    output.mkdir()
    midroll = assets / "midroll.mp4"
    brand = assets / "brand.png"
    narration = output / "narration.mp3"
    _clip(midroll, 0.4)
    brand_image = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    ImageDraw.Draw(brand_image).rounded_rectangle((1, 1, 118, 38), 8, fill=(0, 180, 255, 230))
    brand_image.save(brand)
    _tone(narration, 1.6)
    config = AppConfig(
        root=tmp_path,
        raw={
            "render": {
                "width": 180,
                "height": 320,
                "fps": 15,
                "font_path": "",
                "background_music": "",
                "midroll_path": "assets/midroll.mp4",
                "brand_banner_path": "assets/brand.png",
                "brand_width": 90,
                "brand_bottom_margin": 20,
            }
        },
    )
    plan = VideoPlan(
        topic="Тест",
        title="Тест",
        description="Тест",
        tags=[],
        scenes=[
            Scene("Первая мысль.", "ПЕРВАЯ МЫСЛЬ"),
            Scene("Законченный вывод.", "ЯСНЫЙ ВЫВОД"),
        ],
    )

    frames = create_frames(config, plan, output, backgrounds=[None, None])
    video = render_video(config, frames, narration, output)

    info = media_info(video)
    assert (info.width, info.height) == (180, 320)
    assert info.duration == pytest.approx(2.0, abs=0.3)
    assert (output / "frames" / "visuals.json").exists()
    assert not (output / "short-original.mp4").exists()
    assert not (output / "short-unbranded.mp4").exists()
