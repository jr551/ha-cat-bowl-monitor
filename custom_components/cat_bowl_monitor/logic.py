"""Pure parsing and confirmation logic for Cat Bowl Monitor."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from typing import Any

VALID_LEVELS = frozenset({"empty", "low", "okay", "unknown"})


def interval_schedule(anchor: time, interval_hours: int) -> tuple[time, ...]:
    """Return evenly spaced local wall-clock checks anchored to one time."""
    anchor_minutes = anchor.hour * 60 + anchor.minute
    return tuple(
        time(hour=minutes // 60, minute=minutes % 60)
        for minutes in sorted(
            {
                (anchor_minutes + offset * 60) % (24 * 60)
                for offset in range(0, 24, interval_hours)
            }
        )
    )


class AssessmentError(ValueError):
    """A safe-to-display provider assessment error."""


@dataclass(frozen=True, slots=True)
class BowlReading:
    """One bowl in one structured assessment."""

    level: str
    fill_percent: int | None
    confidence: float
    visible: bool


@dataclass(frozen=True, slots=True)
class Assessment:
    """One structured two-bowl assessment."""

    dry: BowlReading
    wet: BowlReading
    cat_present: bool
    cat_confidence: float
    summary: str


@dataclass(frozen=True, slots=True)
class Consumption:
    """AI comparison between an earlier and current image."""

    dry_eaten_percent: int | None
    wet_eaten_percent: int | None
    confidence: float
    summary: str


@dataclass(frozen=True, slots=True)
class Confirmation:
    """The result of applying one assessment to the state machine."""

    stable_level: str
    candidate_level: str | None
    candidate_count: int
    changed: bool


def is_feeding_completion(old_state: str | None, new_state: str | None) -> bool:
    """Return whether a feeder-active sensor completed a real dispense."""
    return old_state == "on" and new_state == "off"


def should_notify_cycle(
    *,
    notifications_enabled: bool,
    notify_no_action: bool,
    right_needed: bool,
    left_needed: bool,
) -> bool:
    """Keep routine no-action cycles silent unless explicitly requested."""
    return notifications_enabled and (notify_no_action or right_needed or left_needed)


def _reading(result: dict[str, Any], prefix: str) -> BowlReading:
    nested = result.get(prefix)
    if isinstance(nested, dict):
        level = str(nested["level"]).strip().lower()
        visible = nested["visible"]
        confidence = float(nested["confidence"])
        raw_fill = nested.get("fill")
    else:
        level = str(result[f"{prefix}_level"]).strip().lower()
        visible = result[f"{prefix}_visible"]
        confidence = float(result[f"{prefix}_confidence"])
        raw_fill = result.get(f"{prefix}_fill_percent")
    fill_percent = None if raw_fill is None else round(float(raw_fill))
    if level not in VALID_LEVELS:
        raise AssessmentError("The AI provider returned an unknown bowl level")
    if not isinstance(visible, bool):
        raise AssessmentError("The AI provider returned an invalid bowl assessment")
    confidence = max(0.0, min(1.0, confidence))
    if not visible:
        return BowlReading("unknown", None, confidence, False)
    if fill_percent is not None:
        fill_percent = max(0, min(100, fill_percent))
    return BowlReading(level, fill_percent, confidence, True)


def parse_provider_response(body: bytes | str) -> Assessment:
    """Parse one strict OpenAI-compatible chat-completions response."""
    try:
        payload = json.loads(body)
        content: Any = payload["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        result = _content_json_object(content)
        summary = " ".join(str(result["summary"]).split())
        dry = _reading(result, "dry")
        wet = _reading(result, "wet")
        cat_present = result["cat_present"]
        cat_confidence = max(0.0, min(1.0, float(result["cat_confidence"])))
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as err:
        raise AssessmentError(
            "The AI provider returned an invalid bowl assessment "
            f"({type(err).__name__}: {err})"
        ) from err

    if not summary or not isinstance(cat_present, bool):
        raise AssessmentError("The AI provider returned an invalid bowl assessment")
    return Assessment(
        dry=dry,
        wet=wet,
        cat_present=cat_present,
        cat_confidence=cat_confidence,
        summary=summary[:500],
    )


def parse_consumption_response(body: bytes | str) -> Consumption:
    """Parse a strict earlier-versus-current comparison."""
    try:
        payload = json.loads(body)
        content: Any = payload["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        result = _content_json_object(content)
        summary = " ".join(str(result["summary"]).split())
        confidence = max(0.0, min(1.0, float(result["confidence"])))
        dry = result.get("dry_eaten_percent")
        wet = result.get("wet_eaten_percent")
        dry_percent = None if dry is None else max(0, min(100, round(float(dry))))
        wet_percent = None if wet is None else max(0, min(100, round(float(wet))))
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as err:
        raise AssessmentError(
            "The AI provider returned an invalid consumption estimate "
            f"({type(err).__name__}: {err})"
        ) from err
    if not summary:
        raise AssessmentError(
            "The AI provider returned an invalid consumption estimate"
        )
    return Consumption(dry_percent, wet_percent, confidence, summary[:500])


def _content_json_object(content: Any) -> dict[str, Any]:
    """Extract the first JSON object from plain or fenced model content."""
    if isinstance(content, dict):
        return content
    text = str(content).strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        result, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(result, dict):
        raise TypeError("Provider content is not a JSON object")
    return result


def apply_confirmation(
    *,
    stable_level: str,
    candidate_level: str | None,
    candidate_count: int,
    assessment: BowlReading,
    confidence_threshold: float,
    required_samples: int,
) -> Confirmation:
    """Require repeated confident readings before changing stable state."""
    if (
        not assessment.visible
        or assessment.level == "unknown"
        or assessment.confidence < confidence_threshold
    ):
        return Confirmation(
            stable_level=stable_level,
            candidate_level=None,
            candidate_count=0,
            changed=False,
        )

    level = assessment.level
    if level == stable_level:
        return Confirmation(
            stable_level=stable_level,
            candidate_level=None,
            candidate_count=0,
            changed=False,
        )

    count = candidate_count + 1 if candidate_level == level else 1
    if count < required_samples:
        return Confirmation(
            stable_level=stable_level,
            candidate_level=level,
            candidate_count=count,
            changed=False,
        )
    return Confirmation(
        stable_level=level,
        candidate_level=None,
        candidate_count=0,
        changed=True,
    )
