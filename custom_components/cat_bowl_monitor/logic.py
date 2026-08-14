"""Pure parsing and confirmation logic for Cat Bowl Monitor."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

VALID_LEVELS = frozenset({"empty", "low", "okay", "unknown"})
VALID_WET_APPEARANCES = frozenset({"moist", "dry", "mixed", "unknown"})
VALID_SECONDARY_KINDS = frozenset(
    {"wet_food", "treats", "other_food", "empty", "unknown"}
)


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


def merge_night_schedule(
    daytime_times: tuple[time, ...],
    anchor: time,
    night_interval_hours: int,
    night_start: time = time(hour=22),
) -> tuple[time, ...]:
    """Replace daytime schedule slots with denser overnight checks."""
    if not night_interval_hours:
        return tuple(sorted(set(daytime_times)))
    anchor_minutes = anchor.hour * 60 + anchor.minute
    night_start_minutes = night_start.hour * 60 + night_start.minute

    def is_night(check_time: time) -> bool:
        minutes = check_time.hour * 60 + check_time.minute
        return minutes >= night_start_minutes or minutes < anchor_minutes

    night_times = interval_schedule(anchor, night_interval_hours)
    return tuple(
        sorted(
            {
                *{check_time for check_time in daytime_times if not is_night(check_time)},
                *{check_time for check_time in night_times if is_night(check_time)},
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
    secondary_kind: str
    wet_appearance: str
    wet_appearance_confidence: float
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


def is_quiet_time(
    current: time,
    *,
    quiet_start: time,
    quiet_end: time,
) -> bool:
    """Return whether a wall-clock time falls in a possibly overnight range."""
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= current < quiet_end
    return current >= quiet_start or current < quiet_end


def family_observation_signature(assessment: Assessment) -> str:
    """Describe meaningful bowl state while ignoring noisy percentage changes."""
    return (
        f"{assessment.dry.level}|{assessment.wet.level}|"
        f"{assessment.secondary_kind}|{assessment.wet_appearance}"
    )


def should_notify_cycle(
    *,
    notifications_enabled: bool,
    notify_no_action: bool,
    right_needed: bool,
    left_needed: bool,
    observation_changed: bool,
) -> bool:
    """Notify for feeder decisions or meaningful no-feed state changes."""
    return notifications_enabled and (
        right_needed
        or left_needed
        or (notify_no_action and observation_changed)
    )


def should_send_cat_photo(
    *,
    cat_present: bool,
    cat_confidence: float,
    confidence_threshold: float,
    captured_at: datetime,
    last_sent_at: datetime | None,
    dedupe_minutes: int,
) -> bool:
    """Return whether a confident cat sighting should send a photo."""
    if not cat_present or cat_confidence < confidence_threshold:
        return False
    return last_sent_at is None or captured_at - last_sent_at >= timedelta(
        minutes=dedupe_minutes
    )


def derive_wet_freshness(
    *,
    current_kind: str,
    current_appearance: str,
    current_fill: int | None,
    previous_kind: str,
    previous_appearance: str,
    previous_fill: int | None,
    batch_started_fresh: bool,
) -> tuple[str, bool]:
    """Track freshness only for a wet-food batch first observed moist."""
    if current_kind != "wet_food":
        return "unknown", False
    clearly_added = (
        current_appearance == "moist"
        and (
            previous_kind != "wet_food"
            or previous_appearance == "dry"
            or (
                current_fill is not None
                and previous_fill is not None
                and current_fill >= previous_fill + 10
            )
        )
    )
    tracked = batch_started_fresh or clearly_added
    if not tracked:
        return "unknown", False
    return {
        "moist": "fresh",
        "dry": "dried",
        "mixed": "mixed",
    }.get(current_appearance, "unknown"), True


def is_usable_primary_assessment(
    assessment: BowlReading, confidence_threshold: float
) -> bool:
    """Return whether a primary reading is safe for decisions and reporting."""
    return (
        assessment.visible
        and assessment.level != "unknown"
        and assessment.fill_percent is not None
        and assessment.confidence >= confidence_threshold
    )


def should_use_safety_feed(
    *,
    now: datetime,
    inconclusive_since: datetime | None,
    last_feeder_completion_at: datetime | None,
    last_fallback_feed_at: datetime | None,
    after_hours: int = 8,
    cooldown_hours: int = 12,
) -> bool:
    """Allow one bounded fallback only after prolonged camera confusion."""
    if inconclusive_since is None:
        return False
    if now - inconclusive_since < timedelta(hours=after_hours):
        return False
    if (
        last_feeder_completion_at is not None
        and last_feeder_completion_at > inconclusive_since
    ):
        return False
    return last_fallback_feed_at is None or now - last_fallback_feed_at >= timedelta(
        hours=cooldown_hours
    )


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


def _message_content(message: Any) -> Any:
    """Return final content, falling back to a provider reasoning channel."""
    if not isinstance(message, dict):
        raise TypeError("Provider message is not an object")
    content = message.get("content")
    if content is None or content == "" or content == []:
        content = message.get("reasoning_content")
    return content


def _choice_content(choice: Any) -> Any:
    """Return usable content, rejecting answers truncated by the token limit."""
    if not isinstance(choice, dict):
        raise TypeError("Provider choice is not an object")
    message = choice.get("message")
    if (
        isinstance(message, dict)
        and choice.get("finish_reason") == "length"
        and not message.get("content")
    ):
        raise AssessmentError(
            "The AI provider ran out of response tokens before answering"
        )
    return _message_content(message)


def parse_provider_response(body: bytes | str) -> Assessment:
    """Parse one strict OpenAI-compatible chat-completions response."""
    try:
        payload = json.loads(body)
        content = _choice_content(payload["choices"][0])
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
        secondary_kind = str(result["secondary_kind"]).strip().lower()
        wet_appearance = str(result["wet_appearance"]).strip().lower()
        wet_appearance_confidence = max(
            0.0, min(1.0, float(result["wet_appearance_confidence"]))
        )
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

    if (
        not summary
        or not isinstance(cat_present, bool)
        or secondary_kind not in VALID_SECONDARY_KINDS
        or wet_appearance not in VALID_WET_APPEARANCES
        or (secondary_kind != "wet_food" and wet_appearance != "unknown")
    ):
        raise AssessmentError("The AI provider returned an invalid bowl assessment")
    return Assessment(
        dry=dry,
        wet=wet,
        cat_present=cat_present,
        cat_confidence=cat_confidence,
        secondary_kind=secondary_kind,
        wet_appearance=wet_appearance,
        wet_appearance_confidence=wet_appearance_confidence,
        summary=summary[:500],
    )


def parse_consumption_response(body: bytes | str) -> Consumption:
    """Parse a strict earlier-versus-current comparison."""
    try:
        payload = json.loads(body)
        content = _choice_content(payload["choices"][0])
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
