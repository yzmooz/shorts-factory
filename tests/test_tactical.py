import copy
import math

import pytest

from shorts_factory.tactical import default_story, interpolate, validate_story


def test_route_speed_uses_distance_not_number_of_points():
    assert interpolate([[0, 0], [0.1, 0], [1, 0]], 0.5) == pytest.approx([0.5, 0])
    assert interpolate([[0.2, 0.3], [0.2, 0.3]], 1) == [0.2, 0.3]


def test_editor_story_rejects_unavailable_assets_and_invalid_geometry():
    story = default_story()
    validate_story(story)
    bad = copy.deepcopy(story)
    bad["map"] = "../../.env"
    with pytest.raises(ValueError):
        validate_story(bad)
    bad = copy.deepcopy(story)
    bad["scenes"][0]["objects"][0]["path"][0][0] = math.nan
    with pytest.raises(ValueError):
        validate_story(bad)
    bad = copy.deepcopy(story)
    bad["scenes"][0]["objects"][0]["asset"] = "unavailable_hero"
    with pytest.raises(ValueError):
        validate_story(bad)
