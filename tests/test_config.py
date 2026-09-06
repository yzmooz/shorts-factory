import pytest

from shorts_factory.config import _validate


def valid_config():
    return {
        "channel": {"audience": "general"},
        "content": {"provider": "deepseek"},
        "visuals": {"provider": "gradient"},
        "render": {},
        "youtube": {"privacy": "private"},
        "automation": {"max_uploads_per_day": 1},
    }


def test_valid_config():
    _validate(valid_config())


def test_bad_audience_rejected():
    config = valid_config()
    config["channel"]["audience"] = "everyone"
    with pytest.raises(ValueError, match="audience"):
        _validate(config)


def test_public_is_allowed():
    config = valid_config()
    config["youtube"]["privacy"] = "public"
    _validate(config)


def test_four_daily_uploads_are_allowed():
    config = valid_config()
    config["automation"]["max_uploads_per_day"] = 4
    _validate(config)


def test_unknown_provider_rejected():
    config = valid_config()
    config["content"]["provider"] = "local"
    with pytest.raises(ValueError, match="provider"):
        _validate(config)


def test_unknown_visual_provider_rejected():
    config = valid_config()
    config["visuals"]["provider"] = "random-web"
    with pytest.raises(ValueError, match="visuals.provider"):
        _validate(config)
