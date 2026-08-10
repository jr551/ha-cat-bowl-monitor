"""Bounded image preparation for cat-bowl vision requests."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageEnhance, ImageOps, ImageStat

LOW_LIGHT_MEAN = 45.0
TARGET_LOW_LIGHT_MEAN = 85.0
MIN_USEFUL_LUMINANCE_SPAN = 20


def camera_luminance_range(jpeg: bytes) -> tuple[int, int]:
    """Return the grayscale extrema used by the quality gate."""
    with Image.open(BytesIO(jpeg)) as source:
        return source.convert("L").getextrema()


def camera_image_is_decodable(jpeg: bytes) -> bool:
    """Return whether Pillow can fully decode the received camera image."""
    try:
        with Image.open(BytesIO(jpeg)) as source:
            source.load()
    except (OSError, ValueError):
        return False
    return True


def camera_image_is_usable(jpeg: bytes) -> bool:
    """Reject effectively black frames before they reach the vision model."""
    try:
        low, high = camera_luminance_range(jpeg)
    except (OSError, ValueError):
        return False
    return high - low >= MIN_USEFUL_LUMINANCE_SPAN


def prepare_vision_jpeg(jpeg: bytes) -> bytes:
    """Normalize and gently lift dark camera images for vision analysis."""
    with Image.open(BytesIO(jpeg)) as source:
        image = source.convert("RGB")
        image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
        luminance = ImageStat.Stat(image.convert("L")).mean[0]
        if luminance < LOW_LIGHT_MEAN and camera_image_is_usable(jpeg):
            # The feeder camera's onboard light is too weak to illuminate the
            # room. Stretch the available range, then lift it without turning
            # normal daylight frames into washed-out images.
            image = ImageOps.autocontrast(image, cutoff=0.5)
            lifted_mean = max(ImageStat.Stat(image.convert("L")).mean[0], 1.0)
            factor = min(4.0, max(1.0, TARGET_LOW_LIGHT_MEAN / lifted_mean))
            image = ImageEnhance.Brightness(image).enhance(factor)
        output = BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
        return output.getvalue()


def prepare_zone_map_jpeg(image_bytes: bytes) -> bytes:
    """Validate and bound an owner-supplied zone map image."""
    with Image.open(BytesIO(image_bytes)) as source:
        source.load()
        image = source.convert("RGB")
        image.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()
