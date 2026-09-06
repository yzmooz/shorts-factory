import shutil
import subprocess

import pytest

from shorts_factory.render import _quiet_midpoint, insert_midroll, media_info

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)


def _make_video(path, *, duration, color, frequency):
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
            f"color=c={color}:s=180x320:r=15:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
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


def test_insert_midroll_preserves_dimensions_and_adds_duration(tmp_path):
    source = tmp_path / "source.mp4"
    midroll = tmp_path / "midroll.mp4"
    output = tmp_path / "output.mp4"
    _make_video(source, duration=1.2, color="blue", frequency=440)
    _make_video(midroll, duration=0.4, color="red", frequency=880)

    insert_midroll(source, midroll, output)

    source_info = media_info(source)
    midroll_info = media_info(midroll)
    output_info = media_info(output)
    assert (output_info.width, output_info.height) == (source_info.width, source_info.height)
    assert output_info.has_audio
    assert output_info.duration == pytest.approx(
        source_info.duration + midroll_info.duration, abs=0.25
    )
    assert source.exists()
    assert midroll.exists()


def test_quiet_midpoint_falls_back_to_exact_middle_without_silence(tmp_path):
    source = tmp_path / "source.mp4"
    _make_video(source, duration=1.2, color="blue", frequency=440)

    assert _quiet_midpoint(source, 1.2) == pytest.approx(0.6)
