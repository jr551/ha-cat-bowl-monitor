"""Tests for the scheduled provider-retry wiring in BowlRuntime."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "cat_bowl_monitor"
PACKAGE_NAME = "custom_components.cat_bowl_monitor"
RUNTIME_NAME = f"{PACKAGE_NAME}.runtime"

FIXED_NOW = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)


def _load_runtime(monkeypatch):
    """Load runtime.py with stubbed Home Assistant modules."""
    if RUNTIME_NAME in sys.modules:
        return sys.modules[RUNTIME_NAME]

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.Event = object
    core.callback = lambda func: func
    ha_const = types.ModuleType("homeassistant.const")
    ha_const.STATE_UNAVAILABLE = "unavailable"
    ha_const.STATE_UNKNOWN = "unknown"
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = Exception

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    persistent_notification = types.ModuleType(
        "homeassistant.components.persistent_notification"
    )
    persistent_notification.async_create = lambda *args, **kwargs: None
    camera = types.ModuleType("homeassistant.components.camera")
    camera.async_get_image = lambda *args, **kwargs: None
    components.persistent_notification = persistent_notification
    components.camera = camera

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = lambda hass: None
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_state_change_event = lambda *args, **kwargs: lambda: None
    event.async_track_time_change = lambda *args, **kwargs: lambda: None
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, *args, **kwargs) -> None:
            self.saved: list[dict] = []

        async def async_load(self) -> None:
            return None

        async def async_save(self, data: dict) -> None:
            self.saved.append(data)

    storage.Store = Store
    helpers.entity_registry = entity_registry
    helpers.event = event
    helpers.storage = storage

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    helpers.aiohttp_client = aiohttp_client

    util = types.ModuleType("homeassistant.util")
    util.__path__ = []
    dt = types.ModuleType("homeassistant.util.dt")
    dt.utcnow = lambda: FIXED_NOW
    dt.now = lambda: FIXED_NOW
    dt.as_local = lambda moment: moment
    dt.UTC = timezone.utc
    util.dt = dt

    for name, module in {
        "homeassistant": _package("homeassistant"),
        "homeassistant.core": core,
        "homeassistant.const": ha_const,
        "homeassistant.config_entries": config_entries,
        "homeassistant.exceptions": exceptions,
        "homeassistant.components": components,
        "homeassistant.components.persistent_notification": persistent_notification,
        "homeassistant.components.camera": camera,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.event": event,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    file_upload = types.ModuleType("homeassistant.components.file_upload")
    file_upload.process_uploaded_file = lambda *args, **kwargs: None
    components.file_upload = file_upload
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.file_upload", file_upload
    )

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, PACKAGE_NAME, package)
    for name in ("const", "image", "logic", "camera_source"):
        module_name = f"{PACKAGE_NAME}.{name}"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
    for name in ("zone_map", "ai"):
        module_name = f"{PACKAGE_NAME}.{name}"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)

    spec = importlib.util.spec_from_file_location(RUNTIME_NAME, ROOT / "runtime.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, RUNTIME_NAME, module)
    spec.loader.exec_module(module)
    return module


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    return module


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict | None]] = []

    def async_fire(self, event_type: str, payload: dict | None = None) -> None:
        self.events.append((event_type, payload))


class _Config:
    @staticmethod
    def path(*parts: str) -> str:
        return "/tmp/" + "/".join(parts)


class _Hass:
    def __init__(self, bus: _Bus, background: object) -> None:
        self.config = _Config()
        self.bus = bus
        self.async_create_background_task = background

    async def async_add_executor_job(self, function, *args):
        return function(*args)


class _Entry:
    def __init__(self) -> None:
        self.entry_id = "test-entry"
        self.data = {"camera_entity": "camera.test"}
        self.options = {}


def _build_runtime(module, hass) -> object:
    return module.BowlRuntime(hass, _Entry())


def test_cycle_schedules_one_retry_on_malformed_response(monkeypatch) -> None:
    module = _load_runtime(monkeypatch)
    bus = _Bus()
    recorded: list[object] = []

    class DoneTask:
        def done(self) -> bool:
            return True

    def record_background(coro, **kwargs):
        recorded.append(coro)
        coro.close()
        return DoneTask()

    runtime = _build_runtime(module, _Hass(bus, record_background))

    async def malformed(*args, **kwargs):
        raise module.ProviderResponseError("malformed response")

    runtime._async_capture_assess = malformed
    feed_calls: list[tuple] = []

    async def request_feed(*args, **kwargs):
        feed_calls.append(args)
        return "action_failed"

    runtime._async_request_feed = request_feed

    asyncio.run(runtime.async_scheduled_cycle())

    assert runtime.last_cycle_status == "retry_scheduled"
    assert runtime.pending_provider_retry_at is not None
    assert len(recorded) == 1
    assert runtime.last_feed_result == "right=not_requested; left=not_requested"
    assert runtime.last_error == "malformed response"
    assert feed_calls == []
    assert bus.events[0][0] == module.EVENT_SCHEDULED_CYCLE
    assert bus.events[0][1]["status"] == "inconclusive"
    assert runtime._store.saved[-1]["pending_provider_retry_at"] is not None


def test_provider_retry_runs_cycle_once_with_retry_flag(monkeypatch) -> None:
    module = _load_runtime(monkeypatch)

    def real_background(coro, **kwargs):
        return asyncio.ensure_future(coro)

    runtime = _build_runtime(module, _Hass(_Bus(), real_background))
    cycle_calls: list[bool] = []

    async def fake_cycle(now=None, provider_retry=False) -> None:
        cycle_calls.append(provider_retry)

    runtime.async_scheduled_cycle = fake_cycle

    async def camera_ready(action, *args):
        await action(*args)

    runtime._async_when_camera_ready = camera_ready

    async def no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    async def main() -> None:
        runtime._schedule_provider_retry()
        await asyncio.sleep(0)
        await runtime._provider_retry_task

    asyncio.run(main())

    assert cycle_calls == [True]
    assert runtime.pending_provider_retry_at is None
    assert runtime._store.saved[-1]["pending_provider_retry_at"] is None
