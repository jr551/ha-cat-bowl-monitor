"""Persistent owner-supplied zone map image handling."""

from __future__ import annotations

import hashlib
import os
from contextlib import suppress
from pathlib import Path

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.core import HomeAssistant
from PIL import Image

from .const import DOMAIN, MAX_ZONE_MAP_BYTES, ZONE_MAP_DIRECTORY
from .image import prepare_zone_map_jpeg


class ZoneMapError(ValueError):
    """A safe-to-display zone map upload failure."""


def zone_map_path(hass: HomeAssistant, camera_entity: str) -> Path:
    """Return the stable map path for a camera entity."""
    camera_key = hashlib.sha256(camera_entity.encode()).hexdigest()[:16]
    return Path(hass.config.path(DOMAIN, ZONE_MAP_DIRECTORY, f"{camera_key}.jpg"))


def save_uploaded_zone_map_file(
    hass: HomeAssistant, uploaded_file_id: str, camera_entity: str
) -> None:
    """Validate, normalize, and atomically save an uploaded zone map."""
    destination = zone_map_path(hass, camera_entity)
    try:
        with process_uploaded_file(hass, uploaded_file_id) as uploaded:
            if uploaded.stat().st_size > MAX_ZONE_MAP_BYTES:
                raise ZoneMapError("The overlay map image is too large")
            prepared = prepare_zone_map_jpeg(uploaded.read_bytes())
    except ZoneMapError:
        raise
    except (Image.DecompressionBombError, OSError, ValueError) as err:
        raise ZoneMapError("The overlay map image is not a valid image") from err

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(prepared)
    os.replace(temporary, destination)


def remove_zone_map(hass: HomeAssistant, camera_entity: str) -> None:
    """Remove the saved zone map for a camera, if present."""
    with suppress(FileNotFoundError):
        zone_map_path(hass, camera_entity).unlink()


def load_zone_map(hass: HomeAssistant, camera_entity: str) -> bytes | None:
    """Load the saved zone map for a camera, if present."""
    path = zone_map_path(hass, camera_entity)
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None
