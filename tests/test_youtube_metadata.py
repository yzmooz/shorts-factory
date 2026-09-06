from shorts_factory.config import AppConfig
from shorts_factory.models import Scene, VideoPlan
from shorts_factory.youtube import _hashtags, build_description


def test_hashtags_are_thematic_and_limited():
    tags = ["pudge", "meat hook", "гайды дота 2", "support", "лишнее"]

    result = _hashtags(tags)

    assert result == ["#shorts", "#dota2", "#дота2", "#pudge", "#meathook"]


def test_description_has_no_pexels_credit_when_disabled(tmp_path):
    config = AppConfig(root=tmp_path, raw={"visuals": {"credit_in_description": False}})
    plan = VideoPlan(
        topic="Pudge",
        title="Pudge #dota2 #shorts",
        description="Как чаще попадать Meat Hook на Pudge? #dota2 #shorts",
        tags=["pudge", "meat hook", "гайды дота 2"],
        scenes=[Scene("Текст", "Экран")],
    )

    description = build_description(config, plan, tmp_path)

    assert description.endswith("#shorts #dota2 #дота2 #pudge #meathook")
    assert description.count("#shorts") == 1
    assert "Pexels" not in description
