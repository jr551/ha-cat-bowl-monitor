"""Tests for provider response failure classification."""

from __future__ import annotations

import asyncio
import importlib.util
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
