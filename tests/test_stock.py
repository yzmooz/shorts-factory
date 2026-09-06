import json

from shorts_factory.stock import (
    _best_image_url,
    _best_video_file,
    _clean_query,
    description_credits,
)


def test_best_image_prefers_large2x():
    photo = {"src": {"portrait": "portrait.jpg", "large2x": "large2x.jpg"}}
    assert _best_image_url(photo) == "large2x.jpg"


def test_clean_query_removes_extra_spacing():
    assert _clean_query("  lightning: storm   sky ", "fallback") == "lightning storm sky"


def test_best_video_prefers_vertical_1080p_file():
    video = {
        "video_files": [
            {"link": "landscape", "file_type": "video/mp4", "width": 1920, "height": 1080},
            {"link": "small", "file_type": "video/mp4", "width": 360, "height": 640},
            {"link": "vertical", "file_type": "video/mp4", "width": 1080, "height": 1920},
        ]
    }

    assert _best_video_file(video)["link"] == "vertical"


def test_description_credits_deduplicates_names(tmp_path):
    payload = {
        "provider": "Pexels",
        "items": [
            {"photographer": "Alice"},
            {"photographer": "Bob"},
            {"photographer": "Alice"},
        ],
    }
    (tmp_path / "credits.json").write_text(json.dumps(payload), encoding="utf-8")

    credits = description_credits(tmp_path)

    assert credits == "Visuals provided by Pexels. Photos: Alice, Bob. https://www.pexels.com"
