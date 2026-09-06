from shorts_factory.config import AppConfig
from shorts_factory.dota import resolve_visual_asset
from shorts_factory.models import Scene, VideoPlan
from shorts_factory.planner import _apply_dota_branding, _prompt


def test_resolve_official_hero_and_item_assets(monkeypatch):
    monkeypatch.setattr(
        "shorts_factory.dota.hero_catalog",
        lambda: [{"id": 14, "name": "npc_dota_hero_pudge", "name_loc": "Pudge"}],
    )
    monkeypatch.setattr(
        "shorts_factory.dota.item_catalog",
        lambda: [{"id": 116, "name": "item_black_king_bar", "name_loc": "Black King Bar"}],
    )

    hero = resolve_visual_asset("hero:pudge", "Pudge", 1)
    item = resolve_visual_asset("item:black_king_bar", "BKB", 2)

    assert hero["url"].endswith("/heroes/renders/pudge.webm")
    assert item["url"].endswith("/items/black_king_bar.png")


def test_dota_prompt_builds_hook_and_ad_break(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "shorts_factory.planner.planning_context",
        lambda _topic: "Последний официальный патч: 7.xx",
    )
    config = AppConfig(
        root=tmp_path,
        raw={
            "channel": {
                "niche": "Dota 2",
                "scenes": 6,
                "video_seconds": 24,
            },
            "content": {
                "style": "быстро и полезно",
                "call_to_action": "игровой выбор",
            },
        },
    )

    prompt = _prompt(config, "Как Pudge попадает Meat Hook")

    assert "ТОЛЬКО про Dota 2" in prompt
    assert "сильный хук" in prompt
    assert "READY HELPER" in prompt
    assert "hero:internal_name" in prompt
    assert "map:roshan_ward" in prompt
    assert "7.xx" in prompt


def test_dota_metadata_is_forced_when_model_omits_it():
    plan = VideoPlan(
        topic="Pudge",
        title="Как попадать хуком",
        description="Разбор Meat Hook.",
        tags=["pudge"],
        scenes=[Scene("Текст", "Подписывайся!", "hero:pudge")],
    )

    _apply_dota_branding(plan)

    assert plan.title.endswith("#dota2 #shorts")
    assert {"dota2", "дота2", "shorts"}.issubset(plan.tags)
    assert plan.scenes[-1].screen_text == "ТВОЙ ВЫБОР?"
