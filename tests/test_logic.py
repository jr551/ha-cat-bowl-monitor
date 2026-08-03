"""Tests for Cat Bowl Monitor confirmation and parsing."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

LOGIC_PATH = (
    Path(__file__).parents[1] / "custom_components" / "cat_bowl_monitor" / "logic.py"
)
SPEC = importlib.util.spec_from_file_location("cat_bowl_logic", LOGIC_PATH)
assert SPEC and SPEC.loader
LOGIC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOGIC
SPEC.loader.exec_module(LOGIC)

AssessmentError = LOGIC.AssessmentError
BowlReading = LOGIC.BowlReading
apply_confirmation = LOGIC.apply_confirmation
parse_consumption_response = LOGIC.parse_consumption_response
parse_provider_response = LOGIC.parse_provider_response


def provider_body(result: dict) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(result)}}]}
    ).encode()


def two_bowl_result() -> dict:
    return {
        "dry_level": "low",
        "dry_fill_percent": 14,
        "dry_confidence": 0.91,
        "dry_visible": True,
        "wet_level": "empty",
        "wet_fill_percent": 0,
        "wet_confidence": 0.86,
        "wet_visible": True,
        "summary": "Sparse kibble remains and the wet bowl is empty.",
    }


def reading(level: str, confidence: float = 0.9) -> BowlReading:
    return BowlReading(level, 10, confidence, True)


def test_parse_two_bowl_assessment() -> None:
    result = parse_provider_response(provider_body(two_bowl_result()))
    assert result.dry.level == "low"
    assert result.dry.fill_percent == 14
    assert result.wet.level == "empty"
    assert result.wet.fill_percent == 0


def test_parse_fenced_assessment_with_trailing_text() -> None:
    content = f"```json\n{json.dumps(two_bowl_result())}\n```\nIgnored trailing text"
    result = parse_provider_response(
        json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    )
    assert result.dry.level == "low"
    assert result.wet.level == "empty"


def test_hidden_wet_bowl_is_forced_unknown() -> None:
    payload = two_bowl_result()
    payload["wet_level"] = "empty"
    payload["wet_visible"] = False
    result = parse_provider_response(provider_body(payload))
    assert result.wet.level == "unknown"
    assert result.wet.fill_percent is None


def test_invalid_level_is_rejected() -> None:
    payload = two_bowl_result()
    payload["dry_level"] = "half"
    with pytest.raises(AssessmentError):
        parse_provider_response(provider_body(payload))


def test_parse_consumption_comparison() -> None:
    result = parse_consumption_response(
        provider_body(
            {
                "dry_eaten_percent": 70,
                "wet_eaten_percent": None,
                "confidence": 0.82,
                "summary": "Most dry food was eaten.",
            }
        )
    )
    assert result.dry_eaten_percent == 70
    assert result.wet_eaten_percent is None
    assert result.confidence == 0.82


def test_two_confident_empty_samples_are_required() -> None:
    first = apply_confirmation(
        stable_level="okay",
        candidate_level=None,
        candidate_count=0,
        assessment=reading("empty"),
        confidence_threshold=0.7,
        required_samples=2,
    )
    assert first.stable_level == "okay"
    assert first.candidate_level == "empty"
    assert first.candidate_count == 1
    assert not first.changed

    second = apply_confirmation(
        stable_level=first.stable_level,
        candidate_level=first.candidate_level,
        candidate_count=first.candidate_count,
        assessment=reading("empty"),
        confidence_threshold=0.7,
        required_samples=2,
    )
    assert second.stable_level == "empty"
    assert second.changed


def test_low_confidence_resets_candidate_without_changing_state() -> None:
    result = apply_confirmation(
        stable_level="okay",
        candidate_level="empty",
        candidate_count=1,
        assessment=reading("empty", confidence=0.55),
        confidence_threshold=0.7,
        required_samples=2,
    )
    assert result.stable_level == "okay"
    assert result.candidate_level is None
    assert result.candidate_count == 0
