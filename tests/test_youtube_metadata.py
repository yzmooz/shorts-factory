from shorts_factory.config import AppConfig
from shorts_factory.models import Scene, VideoPlan
from shorts_factory.youtube import _hashtags, build_description


def test_hashtags_are_thematic_and_limited():
    tags = ["молния", "наука", "скорость света", "гром", "физика", "лишнее"]

    result = _hashtags(tags)

    assert result == ["#shorts", "#наука", "#молния", "#скоростьсвета", "#гром"]


def test_description_has_no_pexels_credit_when_disabled(tmp_path):
    config = AppConfig(root=tmp_path, raw={"visuals": {"credit_in_description": False}})
    plan = VideoPlan(
        topic="Луна",
        title="Луна #shorts",
        description="Что произойдёт с приливами без Луны? #луна #shorts",
        tags=["луна", "космос", "наука"],
        scenes=[Scene("Текст", "Экран")],
    )

    description = build_description(config, plan, tmp_path)

    assert description.endswith("#shorts #наука #луна #космос")
    assert description.count("#shorts") == 1
    assert "Pexels" not in description
