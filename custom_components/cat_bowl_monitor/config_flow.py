"""Config flow for Cat Bowl Monitor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .ai import ProviderError, provider_settings_from_config
from .const import (
    CONF_AFTERNOON_TIME,
    CONF_AI_API_KEY,
    CONF_AI_BASE_URL,
    CONF_AI_MODEL,
    CONF_BOWL_DESCRIPTION,
    CONF_CAMERA_ENTITY,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_CONFIRMATION_SAMPLES,
    CONF_FEEDING_SENSOR,
    CONF_LEFT_FEED_ENTITY,
    CONF_LIGHT_ENTITY,
    CONF_MORNING_TIME,
    CONF_NOTIFICATION_SERVICE,
    CONF_NOTIFICATIONS,
    CONF_PET_NAME,
    CONF_RIGHT_FEED_ENTITY,
    DEFAULT_AFTERNOON_TIME,
    DEFAULT_BOWL_DESCRIPTION,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_CONFIRMATION_SAMPLES,
    DEFAULT_MORNING_TIME,
    DEFAULT_NOTIFICATIONS,
    DEFAULT_PET_NAME,
    DOMAIN,
    MAX_CONFIRMATION_SAMPLES,
    MIN_CONFIRMATION_SAMPLES,
)

_OPTIONAL_KEYS = (
    CONF_LIGHT_ENTITY,
    CONF_RIGHT_FEED_ENTITY,
    CONF_LEFT_FEED_ENTITY,
    CONF_FEEDING_SENSOR,
    CONF_NOTIFICATION_SERVICE,
    CONF_AI_API_KEY,
    CONF_AI_BASE_URL,
    CONF_AI_MODEL,
)


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Retain explicit blanks so options can clear an earlier value."""
    return {**{key: "" for key in _OPTIONAL_KEYS}, **user_input}


def _optional_entity(
    fields: dict[Any, Any],
    key: str,
    defaults: dict[str, Any],
    domains: str | list[str],
) -> None:
    current = str(defaults.get(key, "")).strip()
    marker = vol.Optional(key, default=current) if current else vol.Optional(key)
    fields[marker] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domains)
    )


def _optional_text(
    fields: dict[Any, Any],
    key: str,
    defaults: dict[str, Any],
    text_type: str = "text",
) -> None:
    current = str(defaults.get(key, "")).strip()
    marker = vol.Optional(key, default=current) if current else vol.Optional(key)
    fields[marker] = selector.selector({"text": {"type": text_type}})


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    camera = str(defaults.get(CONF_CAMERA_ENTITY, "")).strip()
    camera_marker = (
        vol.Required(CONF_CAMERA_ENTITY, default=camera)
        if camera
        else vol.Required(CONF_CAMERA_ENTITY)
    )
    fields[camera_marker] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="camera")
    )
    _optional_entity(fields, CONF_LIGHT_ENTITY, defaults, "light")
    fields.update(
        {
            vol.Required(
                CONF_CONFIRMATION_SAMPLES,
                default=defaults.get(
                    CONF_CONFIRMATION_SAMPLES,
                    DEFAULT_CONFIRMATION_SAMPLES,
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_CONFIRMATION_SAMPLES,
                    max=MAX_CONFIRMATION_SAMPLES,
                ),
            ),
            vol.Required(
                CONF_CONFIDENCE_THRESHOLD,
                default=defaults.get(
                    CONF_CONFIDENCE_THRESHOLD,
                    DEFAULT_CONFIDENCE_THRESHOLD,
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=0.99)),
            vol.Required(
                CONF_NOTIFICATIONS,
                default=defaults.get(CONF_NOTIFICATIONS, DEFAULT_NOTIFICATIONS),
            ): bool,
            vol.Required(
                CONF_MORNING_TIME,
                default=defaults.get(CONF_MORNING_TIME, DEFAULT_MORNING_TIME),
            ): vol.Match(r"^(?:[01]\d|2[0-3]):[0-5]\d$"),
            vol.Required(
                CONF_AFTERNOON_TIME,
                default=defaults.get(CONF_AFTERNOON_TIME, DEFAULT_AFTERNOON_TIME),
            ): vol.Match(r"^(?:[01]\d|2[0-3]):[0-5]\d$"),
            vol.Required(
                CONF_PET_NAME,
                default=defaults.get(CONF_PET_NAME, DEFAULT_PET_NAME),
            ): vol.All(str, vol.Length(min=1, max=60)),
            vol.Required(
                CONF_BOWL_DESCRIPTION,
                default=defaults.get(CONF_BOWL_DESCRIPTION, DEFAULT_BOWL_DESCRIPTION),
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        }
    )
    for key in (CONF_RIGHT_FEED_ENTITY, CONF_LEFT_FEED_ENTITY):
        _optional_entity(
            fields,
            key,
            defaults,
            ["scene", "script", "button"],
        )
    _optional_entity(fields, CONF_FEEDING_SENSOR, defaults, "binary_sensor")
    _optional_text(fields, CONF_NOTIFICATION_SERVICE, defaults)
    _optional_text(fields, CONF_AI_API_KEY, defaults, "password")
    _optional_text(fields, CONF_AI_BASE_URL, defaults, "url")
    _optional_text(fields, CONF_AI_MODEL, defaults)
    return vol.Schema(fields)


def _service_exists(hass: Any, value: str) -> bool:
    """Return whether a domain.service string resolves."""
    parts = value.split(".", 1)
    return len(parts) == 2 and hass.services.has_service(parts[0], parts[1])


def _validate_entities_and_provider(
    hass: Any, user_input: dict[str, Any]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    camera_entity = str(user_input[CONF_CAMERA_ENTITY])
    if hass.states.get(camera_entity) is None:
        errors[CONF_CAMERA_ENTITY] = "camera_not_found"
    optional_entities = (
        (CONF_LIGHT_ENTITY, "light_not_found"),
        (CONF_FEEDING_SENSOR, "feeding_sensor_not_found"),
        (CONF_RIGHT_FEED_ENTITY, "action_not_found"),
        (CONF_LEFT_FEED_ENTITY, "action_not_found"),
    )
    for key, error in optional_entities:
        entity_id = str(user_input.get(key, "")).strip()
        if entity_id and hass.states.get(entity_id) is None:
            errors[key] = error
    notification_service = str(user_input.get(CONF_NOTIFICATION_SERVICE, "")).strip()
    if user_input.get(CONF_NOTIFICATIONS) and not _service_exists(
        hass, notification_service
    ):
        errors[CONF_NOTIFICATION_SERVICE] = "notification_service_not_found"
    try:
        provider_settings_from_config(hass, user_input)
    except ProviderError:
        errors["base"] = "provider_not_configured"
    return errors


class CatBowlMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Cat Bowl Monitor."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return CatBowlMonitorOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize(user_input)
            errors = _validate_entities_and_provider(self.hass, user_input)
            if not errors:
                camera_entity = str(user_input[CONF_CAMERA_ENTITY])
                await self.async_set_unique_id(camera_entity)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{str(user_input[CONF_PET_NAME]).strip()} bowls",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )


class CatBowlMonitorOptionsFlow(config_entries.OptionsFlow):
    """Configure sampling and confirmation options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize(user_input)
            errors = _validate_entities_and_provider(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        current = user_input or {
            **self.config_entry.data,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current),
            errors=errors,
        )
