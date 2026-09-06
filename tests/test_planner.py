from shorts_factory.planner import demo_plan


def test_demo_plan_is_renderable():
    plan = demo_plan("Почему Pudge промахивается хуком")
    assert len(plan.scenes) == 6
    assert len(plan.title) <= 100
    assert all(scene.narration and scene.screen_text for scene in plan.scenes)
    assert len(plan.narration) > 100
