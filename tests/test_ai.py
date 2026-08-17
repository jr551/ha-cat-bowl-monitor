"""Tests for provider response failure classification."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).parents[1] / "custom_components" / "cat_bowl_monitor"
PACKAGE_NAME = "custom_components.cat_bowl_monitor"
AI_NAME = f"{PACKAGE_NAME}.ai"


def _load_ai_module(monkeypatch):
    """Load ai.py without requiring a Home Assistant installation."""
    if AI_NAME in sys.modules:
        return sys.modules[AI_NAME]

    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda _hass: None
    homeassistant.helpers = helpers
    helpers.aiohttp_client = aiohttp_client
    for name, module in {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, PACKAGE_NAME, package)
    for name in ("const", "image", "logic"):
        module_name = f"{PACKAGE_NAME}.{name}"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)

    spec = importlib.util.spec_from_file_location(AI_NAME, ROOT / "ai.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, AI_NAME, module)
    spec.loader.exec_module(module)
    return module


class _Hass:
    async def async_add_executor_job(self, function, *args):
        return function(*args)


def test_malformed_assessment_is_classified_after_bounded_attempts(monkeypatch) -> None:
    ai = _load_ai_module(monkeypatch)
    source = BytesIO()
    Image.new("RGB", (64, 48), (100, 100, 100)).save(source, format="JPEG")
    calls = 0

    async def provider_request(_hass, _settings, _request):
        nonlocal calls
        calls += 1
        return b'{"choices":[{"message":{"content":"not JSON"}}]}'

    monkeypatch.setattr(ai, "_async_provider_request", provider_request)
    settings = ai.ProviderSettings("key", "https://example.test/v1", "model", "test")

    async def run_check() -> None:
        with pytest.raises(ai.ProviderResponseError) as error:
            await ai.async_assess_bowl(
                _Hass(),
                source.getvalue(),
                "user",
                settings,
                "PRIMARY DRY and SECONDARY",
            )
        assert "invalid bowl assessment" in str(error.value)

    asyncio.run(run_check())
    assert calls == ai.PROVIDER_PARSE_ATTEMPTS


def test_xai_responses_payload_and_result_are_normalized(monkeypatch) -> None:
    ai = _load_ai_module(monkeypatch)

    payload = ai._xai_request(
        {
            "messages": [
                {"role": "system", "content": "Return JSON."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Assess the bowl."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64,abc",
                                "detail": "low",
                            },
                        },
                    ],
                },
            ],
            "max_tokens": 4000,
        },
        "grok-4.6",
    )

    assert payload["model"] == "grok-4.6"
    assert payload["max_output_tokens"] == 4000
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["store"] is False
    assert payload["input"][1]["content"] == [
        {"type": "input_text", "text": "Assess the bowl."},
        {
            "type": "input_image",
            "image_url": "data:image/jpeg;base64,abc",
            "detail": "low",
        },
    ]
    normalized = ai._xai_response_as_chat_completion(
        b'{"output":[{"type":"message","content":'
        b'[{"type":"output_text","text":"{\\"dry\\":{}}"}]}]}'
    )
    assert json.loads(normalized)["choices"][0]["message"]["content"] == '{"dry":{}}'


def test_partial_fallback_provider_is_rejected(monkeypatch) -> None:
    ai = _load_ai_module(monkeypatch)

    with pytest.raises(ai.ProviderError, match="Fallback provider requires"):
        ai.fallback_provider_settings_from_config({"fallback_ai_api_key": "key"})


def test_provider_request_fails_over_after_primary_error(monkeypatch) -> None:
    ai = _load_ai_module(monkeypatch)
    primary = ai.ProviderSettings("primary", "https://primary.test", "one", "Primary")
    fallback = ai.ProviderSettings("fallback", "https://api.x.ai/v1", "two", "Fallback")
    attempted: list[str] = []

    async def provider_request(_hass, settings, _request):
        attempted.append(settings.source)
        if settings is primary:
            raise ai.ProviderError("HTTP 402")
        return b'{"choices":[{"message":{"content":"{}"}}]}'

    monkeypatch.setattr(ai, "_async_provider_request", provider_request)

    async def run_request() -> None:
        body, active = await ai._async_provider_request_with_fallback(
            _Hass(), primary, fallback, {"messages": [], "max_tokens": 1}
        )
        assert body == b'{"choices":[{"message":{"content":"{}"}}]}'
        assert active is fallback

    asyncio.run(run_request())
    assert attempted == ["Primary", "Fallback"]
