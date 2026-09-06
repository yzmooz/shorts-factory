from shorts_factory import cli
from shorts_factory.config import AppConfig
from shorts_factory.queue import QueueStore


def _config(tmp_path):
    return AppConfig(
        root=tmp_path,
        raw={
            "automation": {"max_uploads_per_day": 4, "min_hours_between_uploads": 0},
            "youtube": {},
        },
    )


def test_cleanup_uploaded_output_removes_only_bulky_artifacts(tmp_path):
    config = _config(tmp_path)
    config.raw["automation"]["cleanup_after_upload"] = True
    output_dir = tmp_path / "output" / "one"
    (output_dir / "assets").mkdir(parents=True)
    (output_dir / "frames").mkdir()
    for path in (
        output_dir / "assets" / "scene.jpg",
        output_dir / "frames" / "frame.png",
        output_dir / "narration.mp3",
        output_dir / "narration.srt",
        output_dir / "short-original.mp4",
        output_dir / "short.mp4",
        output_dir / "plan.json",
        output_dir / "probe.json",
    ):
        path.write_bytes(b"data")

    cli._cleanup_uploaded_output(config, output_dir)

    assert not (output_dir / "assets").exists()
    assert not (output_dir / "frames").exists()
    assert not (output_dir / "narration.mp3").exists()
    assert not (output_dir / "narration.srt").exists()
    assert not (output_dir / "short-original.mp4").exists()
    assert not (output_dir / "short.mp4").exists()
    assert (output_dir / "plan.json").exists()
    assert (output_dir / "probe.json").exists()


def test_auto_run_retries_same_draft_after_upload_failure(tmp_path, monkeypatch):
    config = _config(tmp_path)
    queue = QueueStore(tmp_path / "data" / "queue.db")
    output_dir = tmp_path / "output" / "one"
    output_dir.mkdir(parents=True)
    (output_dir / "short.mp4").write_bytes(b"video")
    calls = {"build": 0, "upload": 0}

    monkeypatch.setattr(cli, "next_topic", lambda _config: "Тестовая тема")

    def fake_build(_config, topic):
        calls["build"] += 1
        return queue.add(topic, output_dir), output_dir

    def fake_upload(*_args, **_kwargs):
        calls["upload"] += 1
        if calls["upload"] == 1:
            raise RuntimeError("temporary failure")
        return "youtube-id"

    monkeypatch.setattr(cli, "build_short", fake_build)
    monkeypatch.setattr(cli, "load_plan", lambda _output_dir: object())
    monkeypatch.setattr(cli, "upload_video", fake_upload)

    try:
        cli._auto_run(config, queue)
    except RuntimeError as exc:
        assert str(exc) == "temporary failure"

    assert (tmp_path / "data" / "auto-pending.json").exists()
    assert cli._auto_run(config, queue) == 0
    assert calls == {"build": 1, "upload": 2}
    assert queue.get(1)["status"] == "uploaded"
    assert not (tmp_path / "data" / "auto-pending.json").exists()
