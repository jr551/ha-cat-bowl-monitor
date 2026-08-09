"""Tests for low-light image preparation."""

import importlib.util
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageStat

IMAGE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "cat_bowl_monitor" / "image.py"
)
SPEC = importlib.util.spec_from_file_location("cat_bowl_image", IMAGE_PATH)
assert SPEC and SPEC.loader
IMAGE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMAGE_MODULE)
prepare_vision_jpeg = IMAGE_MODULE.prepare_vision_jpeg
camera_image_is_usable = IMAGE_MODULE.camera_image_is_usable
camera_luminance_range = IMAGE_MODULE.camera_luminance_range
camera_image_is_decodable = IMAGE_MODULE.camera_image_is_decodable


def _jpeg(level: int) -> bytes:
    image = Image.new("RGB", (64, 48), (level, level, level))
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def _mean(jpeg: bytes) -> float:
    with Image.open(BytesIO(jpeg)) as image:
        return ImageStat.Stat(image.convert("L")).mean[0]


def test_low_light_is_lifted_for_vision() -> None:
    image = Image.new("RGB", (64, 48), (8, 8, 8))
    for x in range(16, 48):
        for y in range(12, 36):
            image.putpixel((x, y), (45, 45, 45))
    output = BytesIO()
    image.save(output, format="JPEG")
    assert _mean(prepare_vision_jpeg(output.getvalue())) > 25


def test_daylight_is_not_brightened() -> None:
    prepared = prepare_vision_jpeg(_jpeg(120))
    assert 115 <= _mean(prepared) <= 125


def test_flat_black_frame_is_rejected() -> None:
    assert not camera_image_is_usable(_jpeg(8))
    low, high = camera_luminance_range(_jpeg(8))
    assert high - low < IMAGE_MODULE.MIN_USEFUL_LUMINANCE_SPAN


def test_truncated_jpeg_is_rejected_before_analysis() -> None:
    complete = _jpeg(80)
    assert camera_image_is_decodable(complete)
    assert not camera_image_is_decodable(complete[: len(complete) // 2])


def test_dark_frame_with_real_contrast_is_usable() -> None:
    image = Image.new("RGB", (64, 48), (8, 8, 8))
    for x in range(16, 48):
        for y in range(12, 36):
            image.putpixel((x, y), (45, 45, 45))
    output = BytesIO()
    image.save(output, format="JPEG")
    assert camera_image_is_usable(output.getvalue())
