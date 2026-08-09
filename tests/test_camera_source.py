"""Tests for safe direct ESPHome snapshot resolution."""

import importlib.util
from pathlib import Path

SOURCE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "cat_bowl_monitor"
    / "camera_source.py"
)
SPEC = importlib.util.spec_from_file_location("cat_bowl_camera_source", SOURCE_PATH)
assert SPEC and SPEC.loader
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)
private_esphome_snapshot_url = SOURCE.private_esphome_snapshot_url


def test_private_ipv4_snapshot_url() -> None:
    assert (
        private_esphome_snapshot_url("192.168.69.26")
        == "http://192.168.69.26:8081/"
    )


def test_public_or_invalid_host_is_rejected() -> None:
    assert private_esphome_snapshot_url("8.8.8.8") is None
    assert private_esphome_snapshot_url("camera.example") is None
