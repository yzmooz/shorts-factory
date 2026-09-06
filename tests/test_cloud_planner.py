import json
from types import SimpleNamespace

import pytest

from shorts_factory.config import AppConfig
from shorts_factory.planner import _generate_deepseek, _generate_openai, demo_plan


def config(tmp_path, provider="deepseek"):
    return AppConfig(
        root=tmp_path,
        raw={
            "content": {
                "provider": provider,
                "deepseek_model": "deepseek-v4-flash",
                "openai_model": "gpt-5.6-luna",
                "reasoning_effort": "low",
                "api_timeout_seconds": 10,
            }
        },
    )


def plan_json():
    return json.dumps(demo_plan("Марс").to_dict(), ensure_ascii=False)


class FakeOpenAI:
    last_kwargs = None

    def __init__(self, **_kwargs):
        self.responses = SimpleNamespace(create=self.create_response)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create_chat_completion))

    def create_response(self, **kwargs):
        FakeOpenAI.last_kwargs = kwargs
        return SimpleNamespace(output_text=plan_json())

    def create_chat_completion(self, **kwargs):
        FakeOpenAI.last_kwargs = kwargs
        message = SimpleNamespace(content=plan_json())
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_openai_uses_responses_and_json_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("shorts_factory.planner.OpenAI", FakeOpenAI)
    result = _generate_openai(config(tmp_path, "openai"), "prompt")
    assert result["topic"] == "Марс"
    assert FakeOpenAI.last_kwargs["text"]["format"]["type"] == "json_schema"


def test_deepseek_uses_json_mode_without_thinking(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr("shorts_factory.planner.OpenAI", FakeOpenAI)
    result = _generate_deepseek(config(tmp_path), "prompt")
    assert result["topic"] == "Марс"
    assert FakeOpenAI.last_kwargs["response_format"] == {"type": "json_object"}
    assert FakeOpenAI.last_kwargs["extra_body"]["thinking"]["type"] == "disabled"


def test_missing_deepseek_key_is_clear(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        _generate_deepseek(config(tmp_path), "prompt")
