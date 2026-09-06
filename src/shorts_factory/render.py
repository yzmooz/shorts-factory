from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .config import AppConfig


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("Нужны ffmpeg и ffprobe в PATH")


def media_info(path: Path) -> MediaInfo:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    fps_raw = str(video.get("r_frame_rate", "30/1"))
    fps = float(Fraction(fps_raw)) if fps_raw != "0/0" else 30.0
    return MediaInfo(
        duration=float(payload["format"]["duration"]),
        width=int(video["width"]),
        height=int(video["height"]),
        fps=max(1.0, min(fps, 60.0)),
        has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
    )


def media_duration(path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def render_video(config: AppConfig, frames: list[Path], audio_path: Path, output_dir: Path) -> Path:
    require_ffmpeg()
    if not frames:
        raise ValueError("Нельзя собрать ролик без кадров")
    render = config.section("render")
    width, height, fps = int(render["width"]), int(render["height"]), int(render["fps"])
    duration = media_duration(audio_path)
    transition = min(0.32, duration / len(frames) / 5) if len(frames) > 1 else 0.0
    scene_duration = max(0.5, (duration + transition * (len(frames) - 1)) / len(frames))
    original_path = output_dir / "short-original.mp4"
    unbranded_path = output_dir / "short-unbranded.mp4"
    output_path = output_dir / "short.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
    ]
    visual_manifest = output_dir / "frames" / "visuals.json"
    sources = frames
    overlays: list[Path] = []
    if visual_manifest.exists():
        manifest = json.loads(visual_manifest.read_text(encoding="utf-8"))
        candidate_sources = [Path(value) for value in manifest.get("sources", [])]
        candidate_overlays = [Path(value) for value in manifest.get("overlays", [])]
        if (
            len(candidate_sources) == len(frames)
            and len(candidate_overlays) == len(frames)
            and all(path.is_file() for path in candidate_sources + candidate_overlays)
        ):
            sources = candidate_sources
            overlays = candidate_overlays

    if overlays:
        for source, overlay in zip(sources, overlays, strict=True):
            if source.suffix.lower() == ".mp4":
                command.extend(
                    ["-stream_loop", "-1", "-t", f"{scene_duration:.6f}", "-i", str(source)]
                )
            else:
                command.extend(
                    [
                        "-loop",
                        "1",
                        "-framerate",
                        str(fps),
                        "-t",
                        f"{scene_duration:.6f}",
                        "-i",
                        str(source),
                    ]
                )
            command.extend(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(fps),
                    "-t",
                    f"{scene_duration:.6f}",
                    "-i",
                    str(overlay),
                ]
            )
    else:
        for frame in frames:
            command.extend(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(fps),
                    "-t",
                    f"{scene_duration:.6f}",
                    "-i",
                    str(frame),
                ]
            )

    narration_index = len(frames) * (2 if overlays else 1)
    command.extend(["-i", str(audio_path)])
    filter_parts: list[str] = []
    if overlays:
        for index, source in enumerate(sources):
            source_index = index * 2
            overlay_index = source_index + 1
            motion = _motion_filter(index, source, width, height, fps, scene_duration)
            filter_parts.append(
                f"[{source_index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},{motion}"
                "eq=saturation=1.10:contrast=1.035:brightness=0.008,"
                f"trim=duration={scene_duration:.6f},setpts=PTS-STARTPTS,setsar=1,"
                f"format=yuv420p[bg{index}]"
            )
            filter_parts.append(
                f"[{overlay_index}:v]scale={width}:{height},fps={fps},"
                f"trim=duration={scene_duration:.6f},setpts=PTS-STARTPTS,format=rgba[ui{index}]"
            )
            filter_parts.append(
                f"[bg{index}][ui{index}]overlay=0:0:format=auto,format=yuv420p[v{index}]"
            )
    else:
        for index in range(len(frames)):
            motion = _motion_filter(index, frames[index], width, height, fps, scene_duration)
            filter_parts.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},{motion}"
                "eq=saturation=1.10:contrast=1.035:brightness=0.008,"
                f"trim=duration={scene_duration:.6f},setpts=PTS-STARTPTS,setsar=1,"
                f"format=yuv420p[v{index}]"
            )
    if len(frames) == 1:
        filter_parts.append("[v0]null[vout]")
    else:
        current = "[v0]"
        for index in range(1, len(frames)):
            output = "[vout]" if index == len(frames) - 1 else f"[xf{index}]"
            offset = index * (scene_duration - transition)
            transition_name = ("fade", "smoothleft", "smoothup")[index % 3]
            filter_parts.append(
                f"{current}[v{index}]xfade=transition={transition_name}:"
                f"duration={transition:.3f}:offset={offset:.6f}{output}"
            )
            current = output

    music = str(render.get("background_music", "")).strip()
    if music:
        music_path = (config.root / music).resolve()
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])
        volume = float(render.get("music_volume", 0.08))
        music_index = narration_index + 1
        filter_parts.append(
            f"[{narration_index}:a]volume=1.0[a1];"
            f"[{music_index}:a]volume={volume}[a2];"
            "[a1][a2]amix=inputs=2:duration=first[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = f"{narration_index}:a:0"
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-map",
            audio_map,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(original_path),
        ]
    )
    subprocess.run(command, check=True)
    midroll_value = str(render.get("midroll_path", "")).strip()
    if not midroll_value:
        raise ValueError("render.midroll_path не задан: публикация без обязательной вставки запрещена")
    midroll_path = (config.root / midroll_value).resolve()
    if not midroll_path.is_file():
        raise FileNotFoundError(f"Обязательная вставка не найдена: {midroll_path}")
    try:
        insert_midroll(original_path, midroll_path, unbranded_path)
        _apply_brand_overlay(config, unbranded_path, output_path)
    finally:
        original_path.unlink(missing_ok=True)
        unbranded_path.unlink(missing_ok=True)
    return output_path


def _motion_filter(
    index: int,
    source: Path,
    width: int,
    height: int,
    fps: int,
    scene_duration: float,
) -> str:
    """Create varied, subtle Ken Burns movement without distracting from captions."""
    if source.suffix.lower() == ".mp4":
        return f"fps={fps},"
    total_frames = max(1, round(scene_duration * fps))
    variants = (
        "zoompan=z='min(zoom+0.00075,1.085)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'",
        "zoompan=z='if(eq(on,1),1.085,max(zoom-0.00075,1.0))':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'",
        f"zoompan=z='1.065':x='(iw-iw/zoom)*on/{total_frames}':y='ih/2-ih/zoom/2'",
        f"zoompan=z='1.065':x='(iw-iw/zoom)*(1-on/{total_frames})':y='ih/2-ih/zoom/2'",
    )
    return f"{variants[index % len(variants)]}:d=1:s={width}x{height}:fps={fps},"


def _apply_brand_overlay(config: AppConfig, input_path: Path, output_path: Path) -> None:
    render = config.section("render")
    brand_value = str(render.get("brand_banner_path", "")).strip()
    if not brand_value:
        raise ValueError("render.brand_banner_path не задан: фирменный баннер обязателен")
    brand_path = (config.root / brand_value).resolve()
    if not brand_path.is_file():
        raise FileNotFoundError(f"Фирменный баннер не найден: {brand_path}")
    brand_width = int(render.get("brand_width", 460))
    bottom_margin = int(render.get("brand_bottom_margin", 190))
    opacity = max(0.1, min(float(render.get("brand_opacity", 0.92)), 1.0))
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-loop",
            "1",
            "-i",
            str(brand_path),
            "-filter_complex",
            (
                f"[1:v]scale={brand_width}:-1,format=rgba,"
                f"colorchannelmixer=aa={opacity:.3f}[brand];"
                f"[0:v][brand]overlay=x=(W-w)/2:y=H-h-{bottom_margin}:format=auto[v]"
            ),
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ],
        check=True,
    )


def insert_midroll(input_path: Path, midroll_path: Path, output_path: Path) -> None:
    """Insert the clip near the middle using memory-bounded sequential transcoding."""
    require_ffmpeg()
    input_path = input_path.resolve(strict=True)
    midroll_path = midroll_path.resolve(strict=True)
    output_path = output_path.resolve(strict=False)
    if len({input_path, midroll_path, output_path}) != 3:
        raise ValueError("Исходник, вставка и итоговый файл должны быть разными файлами")

    main = media_info(input_path)
    midroll = media_info(midroll_path)
    midpoint = _quiet_midpoint(input_path, main.duration)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_path.stem}.", suffix=".mp4", dir=output_path.parent, delete=False
    ) as handle:
        temporary_path = Path(handle.name)
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output_path.stem}-parts.", dir=output_path.parent
        ) as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            parts = [temp_dir / "01-before.mp4", temp_dir / "02-midroll.mp4", temp_dir / "03-after.mp4"]
            _transcode_segment(input_path, main, 0.0, midpoint, main, parts[0])
            _transcode_segment(midroll_path, midroll, 0.0, midroll.duration, main, parts[1])
            _transcode_segment(
                input_path,
                main,
                midpoint,
                main.duration - midpoint,
                main,
                parts[2],
            )
            concat_file = temp_dir / "concat.txt"
            concat_file.write_text(
                "".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8"
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    "-metadata",
                    "comment=midroll inserted automatically",
                    str(temporary_path),
                ],
                check=True,
            )
        rendered = media_info(temporary_path)
        expected_duration = main.duration + midroll.duration
        tolerance = max(0.25, 2.0 / main.fps)
        if abs(rendered.duration - expected_duration) > tolerance:
            raise RuntimeError(
                "Некорректная длительность после вставки: "
                f"ожидалось около {expected_duration:.3f}, получено {rendered.duration:.3f}"
            )
        if (rendered.width, rendered.height) != (main.width, main.height):
            raise RuntimeError("Размер итогового видео изменился после вставки")
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _transcode_segment(
    source: Path,
    source_info: MediaInfo,
    start: float,
    duration: float,
    target_info: MediaInfo,
    output: Path,
) -> None:
    end = start + duration
    video_filter = (
        f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
        f"scale={target_info.width}:{target_info.height}:force_original_aspect_ratio=decrease,"
        f"pad={target_info.width}:{target_info.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={target_info.fps:.6f},format=yuv420p[v]"
    )
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if source_info.has_audio:
        audio_filter = (
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
        )
        command.extend(["-filter_complex", f"{video_filter};{audio_filter}", "-map", "[v]", "-map", "[a]"])
    else:
        command.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{duration:.6f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-filter_complex",
                video_filter,
                "-map",
                "[v]",
                "-map",
                "1:a:0",
            ]
        )
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-shortest",
            str(output),
        ]
    )
    subprocess.run(command, check=True)


def _quiet_midpoint(path: Path, duration: float) -> float:
    """Choose the nearest brief silence around the middle so speech is not cut mid-word."""
    target = duration / 2.0
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            "silencedetect=noise=-35dB:d=0.12",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    starts = [float(value) for value in re.findall(r"silence_start: ([0-9.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: ([0-9.]+)", result.stderr)]
    candidates = [
        (start + end) / 2.0
        for start, end in zip(starts, ends, strict=False)
        if end > start and duration * 0.35 <= (start + end) / 2.0 <= duration * 0.65
    ]
    return min(candidates, key=lambda value: abs(value - target), default=target)


def probe_video(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name:format=duration,size",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)
