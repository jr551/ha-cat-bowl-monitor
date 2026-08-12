"""Tests for Cat Bowl Monitor confirmation and parsing."""

import importlib.util
import json
import sys
from datetime import datetime, time, timedelta, timezone
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
family_observation_signature = LOGIC.family_observation_signature
apply_confirmation = LOGIC.apply_confirmation
derive_wet_freshness = LOGIC.derive_wet_freshness
is_feeding_completion = LOGIC.is_feeding_completion
is_quiet_time = LOGIC.is_quiet_time
is_usable_primary_assessment = LOGIC.is_usable_primary_assessment
interval_schedule = LOGIC.interval_schedule
merge_night_schedule = LOGIC.merge_night_schedule
should_notify_cycle = LOGIC.should_notify_cycle
should_send_cat_photo = LOGIC.should_send_cat_photo
should_use_safety_feed = LOGIC.should_use_safety_feed
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
        "secondary_kind": "wet_food",
        "wet_appearance": "dry",
        "wet_appearance_confidence": 0.88,
        "cat_present": False,
        "cat_confidence": 0.92,
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
    assert result.wet_appearance == "dry"
    assert not result.cat_present


def test_parse_compact_nested_assessment() -> None:
    result = parse_provider_response(
        provider_body(
            {
                "dry": {"level": "low", "fill": 12, "confidence": 0.9, "visible": True},
                "wet": {
                    "level": "empty",
                    "fill": 0,
                    "confidence": 0.8,
                    "visible": True,
                },
                "cat_present": True,
                "cat_confidence": 0.88,
                "secondary_kind": "wet_food",
                "wet_appearance": "moist",
                "wet_appearance_confidence": 0.91,
                "summary": "Dry low; wet empty.",
            }
        )
    )
    assert result.dry.fill_percent == 12
    assert result.wet.level == "empty"
    assert result.cat_present
    assert result.cat_confidence == 0.88
    assert result.wet_appearance == "moist"


def test_parse_reasoning_channel_when_content_is_empty() -> None:
    result = parse_provider_response(
        json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": json.dumps(two_bowl_result()),
                        }
                    }
                ]
            }
        ).encode()
    )
    assert result.dry.level == "low"
    assert result.wet.level == "empty"


def test_invalid_wet_appearance_is_rejected() -> None:
    payload = two_bowl_result()
    payload["wet_appearance"] = "old"
    with pytest.raises(AssessmentError):
        parse_provider_response(provider_body(payload))


def test_treats_cannot_be_labelled_moist_wet_food() -> None:
    payload = two_bowl_result()
    payload["secondary_kind"] = "treats"
    payload["wet_appearance"] = "moist"
    with pytest.raises(AssessmentError):
        parse_provider_response(provider_body(payload))


def test_wet_batch_must_start_moist_before_it_can_dry() -> None:
    assert derive_wet_freshness(
        current_kind="wet_food",
        current_appearance="dry",
        current_fill=20,
        previous_kind="unknown",
        previous_appearance="unknown",
        previous_fill=None,
        batch_started_fresh=False,
    ) == ("unknown", False)
    assert derive_wet_freshness(
        current_kind="wet_food",
        current_appearance="moist",
        current_fill=30,
        previous_kind="other_food",
        previous_appearance="unknown",
        previous_fill=10,
        batch_started_fresh=False,
    ) == ("fresh", True)
    assert derive_wet_freshness(
        current_kind="wet_food",
        current_appearance="dry",
        current_fill=15,
        previous_kind="wet_food",
        previous_appearance="moist",
        previous_fill=30,
        batch_started_fresh=True,
    ) == ("dried", True)


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


def test_truncated_provider_json_is_rejected_safely() -> None:
    body = json.dumps(
        {"choices": [{"message": {"content": '{"dry_level":"empty"'}}]}
    ).encode()
    with pytest.raises(AssessmentError):
        parse_provider_response(body)


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


def test_only_real_feeding_completion_resets_baseline() -> None:
    assert is_feeding_completion("on", "off")
    assert not is_feeding_completion("off", "on")
    assert not is_feeding_completion("unavailable", "off")
    assert not is_feeding_completion(None, "off")


def test_routine_no_action_cycle_is_silent_by_default() -> None:
    assert not should_notify_cycle(
        notifications_enabled=True,
        notify_no_action=False,
        right_needed=False,
        left_needed=False,
        observation_changed=False,
    )


def test_cat_photo_requires_confidence_and_deduplicates() -> None:
    captured_at = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    common = {
        "cat_present": True,
        "confidence_threshold": 0.8,
        "captured_at": captured_at,
        "dedupe_minutes": 30,
    }
    assert should_send_cat_photo(**common, cat_confidence=0.9, last_sent_at=None)
    assert not should_send_cat_photo(**common, cat_confidence=0.79, last_sent_at=None)
    assert not should_send_cat_photo(
        **common,
        cat_confidence=0.9,
        last_sent_at=captured_at - timedelta(minutes=29),
    )
    assert should_send_cat_photo(
        **common,
        cat_confidence=0.9,
        last_sent_at=captured_at - timedelta(minutes=30),
    )


def test_four_hour_schedule_wraps_from_0615() -> None:
    assert interval_schedule(time(6, 15), 4) == (
        time(2, 15),
        time(6, 15),
        time(10, 15),
        time(14, 15),
        time(18, 15),
        time(22, 15),
    )
    assert should_notify_cycle(
        notifications_enabled=True,
        notify_no_action=False,
        right_needed=True,
        left_needed=False,
        observation_changed=False,
    )
    assert should_notify_cycle(
        notifications_enabled=True,
        notify_no_action=True,
        right_needed=False,
        left_needed=False,
        observation_changed=True,
    )
    assert not should_notify_cycle(
        notifications_enabled=True,
        notify_no_action=True,
        right_needed=False,
        left_needed=False,
        observation_changed=False,
    )
    assert not should_notify_cycle(
        notifications_enabled=False,
        notify_no_action=True,
        right_needed=True,
        left_needed=True,
        observation_changed=True,
    )


def test_two_hour_overnight_schedule_replaces_normal_night_slots() -> None:
    daytime = interval_schedule(time(6, 15), 4)
    assert merge_night_schedule(daytime, time(6, 15), 2) == (
        time(0, 15),
        time(2, 15),
        time(4, 15),
        time(6, 15),
        time(10, 15),
        time(14, 15),
        time(18, 15),
        time(22, 15),
    )


def test_notification_quiet_hours_span_midnight_until_morning() -> None:
    quiet_start = time(22)
    quiet_end = time(6, 15)
    assert is_quiet_time(time(22), quiet_start=quiet_start, quiet_end=quiet_end)
    assert is_quiet_time(time(2), quiet_start=quiet_start, quiet_end=quiet_end)
    assert not is_quiet_time(
        time(6, 15), quiet_start=quiet_start, quiet_end=quiet_end
    )
    assert not is_quiet_time(
        time(18), quiet_start=quiet_start, quiet_end=quiet_end
    )


def test_family_signature_ignores_fill_noise_but_tracks_food_state() -> None:
    first = parse_provider_response(provider_body(two_bowl_result()))
    changed_fill = two_bowl_result()
    changed_fill["dry_fill_percent"] = 18
    second = parse_provider_response(provider_body(changed_fill))
    changed_state = two_bowl_result()
    changed_state["dry_level"] = "empty"
    changed_state["dry_fill_percent"] = 0
    third = parse_provider_response(provider_body(changed_state))
    assert family_observation_signature(first) == family_observation_signature(second)
    assert family_observation_signature(first) != family_observation_signature(third)


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


def test_primary_assessment_must_be_visible_confident_and_quantified() -> None:
    assert is_usable_primary_assessment(reading("low"), 0.7)
    assert not is_usable_primary_assessment(BowlReading("unknown", None, 0.9, False), 0.7)
    assert not is_usable_primary_assessment(BowlReading("low", None, 0.9, True), 0.7)
    assert not is_usable_primary_assessment(BowlReading("low", 10, 0.6, True), 0.7)


def test_safety_feed_requires_eight_unclear_hours_and_twelve_hour_cooldown() -> None:
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    assert not should_use_safety_feed(
        now=now,
        inconclusive_since=now - timedelta(hours=7, minutes=59),
        last_feeder_completion_at=None,
        last_fallback_feed_at=None,
    )
    assert should_use_safety_feed(
        now=now,
        inconclusive_since=now - timedelta(hours=8),
        last_feeder_completion_at=None,
        last_fallback_feed_at=None,
    )
    assert not should_use_safety_feed(
        now=now,
        inconclusive_since=now - timedelta(hours=8),
        last_feeder_completion_at=None,
        last_fallback_feed_at=now - timedelta(hours=11, minutes=59),
    )


def test_confirmed_feed_during_confusion_blocks_safety_feed() -> None:
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    unclear = now - timedelta(hours=9)
    assert not should_use_safety_feed(
        now=now,
        inconclusive_since=unclear,
        last_feeder_completion_at=unclear + timedelta(hours=4),
        last_fallback_feed_at=None,
    )
