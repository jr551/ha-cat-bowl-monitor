"""Tests for owner-supplied zone-map persistence."""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import types
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parents[1] / "custom_components" / "cat_bowl_monitor"
PACKAGE_NAME = "custom_components.cat_bowl_monitor"
ZONE_MAP_NAME = f"{PACKAGE_NAME}.zone_map"


def _load_zone_map_module(monkeypatch):
    """Load zone_map.py without requiring a Home Assistant installation."""
    if ZONE_MAP_NAME in sys.modules:
        return sys.modules[ZONE_MAP_NAME]

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    file_upload = types.ModuleType("homeassistant.components.file_upload")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object

    @contextlib.contextmanager
    def process_uploaded_file(_hass: object, _file_id: str):
        yield None

    file_upload.process_uploaded_file = process_uploaded_file
    components.file_upload = file_upload
    homeassistant.components = components
    for name, module in {
        "homeassistant": homeassistant,
        "homeassistant.components": components,
        "homeassistant.components.file_upload": file_upload,
        "homeassistant.core": core,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, PACKAGE_NAME, package)
    for name in ("const", "image"):
        module_name = f"{PACKAGE_NAME}.{name}"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)

    spec = importlib.util.spec_from_file_location(ZONE_MAP_NAME, ROOT / "zone_map.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, ZONE_MAP_NAME, module)
    spec.loader.exec_module(module)
    return module


class _Config:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


class _Hass:
    def __init__(self, root: Path) -> None:
        self.config = _Config(root)


def test_zone_map_upload_is_persisted_and_removed(tmp_path: Path, monkeypatch) -> None:
    zone_map = _load_zone_map_module(monkeypatch)
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 60), (20, 30, 40)).save(source, format="PNG")

    @contextlib.contextmanager
    def uploaded_file(_hass: object, _file_id: str):
        yield source

    zone_map.process_uploaded_file = uploaded_file
    hass = _Hass(tmp_path)

    zone_map.save_uploaded_zone_map_file(hass, "upload-id", "camera.example")
    saved = zone_map.load_zone_map(hass, "camera.example")
    assert saved and saved[:2] == bytes((0xFF, 0xD8))

    zone_map.remove_zone_map(hass, "camera.example")

    assert zone_map.load_zone_map(hass, "camera.example") is None
