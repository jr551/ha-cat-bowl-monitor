"""Config flow for Cat Bowl Monitor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .ai import (
    ProviderError,
    fallback_provider_settings_from_config,
    provider_settings_from_config,
)
from .const import (
    CHECK_INTERVAL_OPTIONS,
    CONF_AFTERNOON_TIME,
    CONF_AI_API_KEY,
    CONF_AI_BASE_URL,
    CONF_AI_MODEL,
    CONF_BOWL_DESCRIPTION,
    CONF_CAMERA_ENTITY,
    CONF_CHECK_INTERVAL_HOURS,
    CONF_CLEAR_ZONE_MAP,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_CONFIRMATION_SAMPLES,
    CONF_FALLBACK_AI_API_KEY,
    CONF_FALLBACK_AI_BASE_URL,
    CONF_FALLBACK_AI_MODEL,
    CONF_FEEDING_SENSOR,
    CONF_LEFT_FEED_ENTITY,
    CONF_LIGHT_ENTITY,
    CONF_MORNING_TIME,
    CONF_NIGHT_CHECK_INTERVAL_HOURS,
    CONF_NOTIFICATION_SERVICE,
    CONF_NOTIFICATIONS,
    CONF_NOTIFY_NO_ACTION,
    CONF_PET_NAME,
    CONF_RIGHT_FEED_ENTITY,
    CONF_ZONE_MAP_FILE,
    DEFAULT_AFTERNOON_TIME,
    DEFAULT_BOWL_DESCRIPTION,
    DEFAULT_CHECK_INTERVAL_HOURS,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_CONFIRMATION_SAMPLES,
    DEFAULT_MORNING_TIME,
    DEFAULT_NIGHT_CHECK_INTERVAL_HOURS,
    DEFAULT_NOTIFICATIONS,
    DEFAULT_NOTIFY_NO_ACTION,
    DEFAULT_PET_NAME,
    DOMAIN,
    MAX_CONFIRMATION_SAMPLES,
    MIN_CONFIRMATION_SAMPLES,
)
from .zone_map import ZoneMapError, remove_zone_map, save_uploaded_zone_map_file

_OPTIONAL_KEYS = (
    CONF_NOTIFICATION_SERVICE,
    CONF_AI_API_KEY,
    CONF_AI_BASE_URL,
    CONF_AI_MODEL,
    CONF_FALLBACK_AI_API_KEY,
    CONF_FALLBACK_AI_BASE_URL,
    CONF_FALLBACK_AI_MODEL,
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
    marker = (
        vol.Optional(key, description={"suggested_value": current})
        if current
        else vol.Optional(key)
    )
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
    marker = (
        vol.Optional(key, description={"suggested_value": current})
        if current
        else vol.Optional(key)
    )
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
                CONF_NOTIFY_NO_ACTION,
                default=defaults.get(
                    CONF_NOTIFY_NO_ACTION,
                    DEFAULT_NOTIFY_NO_ACTION,
                ),
            ): bool,
            vol.Required(
                CONF_CHECK_INTERVAL_HOURS,
                default=defaults.get(
                    CONF_CHECK_INTERVAL_HOURS, DEFAULT_CHECK_INTERVAL_HOURS
                ),
            ): vol.In(CHECK_INTERVAL_OPTIONS),
            vol.Required(
                CONF_NIGHT_CHECK_INTERVAL_HOURS,
                default=defaults.get(
                    CONF_NIGHT_CHECK_INTERVAL_HOURS,
                    DEFAULT_NIGHT_CHECK_INTERVAL_HOURS,
                ),
            ): vol.In(CHECK_INTERVAL_OPTIONS),
            vol.Required(
                CONF_MORNING_TIME,
                default=defaults.get(CONF_MORNING_TIME, DEFAULT_MORNING_TIME),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_AFTERNOON_TIME,
                default=defaults.get(CONF_AFTERNOON_TIME, DEFAULT_AFTERNOON_TIME),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_PET_NAME,
                default=defaults.get(CONF_PET_NAME, DEFAULT_PET_NAME),
            ): vol.All(str, vol.Length(min=1, max=60)),
            vol.Required(
                CONF_BOWL_DESCRIPTION,
                default=defaults.get(CONF_BOWL_DESCRIPTION, DEFAULT_BOWL_DESCRIPTION),
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Optional(CONF_ZONE_MAP_FILE): selector.FileSelector(
                config=selector.FileSelectorConfig(
                    accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                )
            ),
            vol.Optional(CONF_CLEAR_ZONE_MAP, default=False): bool,
        }
    )
    _optional_text(fields, CONF_FALLBACK_AI_API_KEY, defaults, "password")
    _optional_text(fields, CONF_FALLBACK_AI_BASE_URL, defaults, "url")
    _optional_text(fields, CONF_FALLBACK_AI_MODEL, defaults)
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
        fallback_provider_settings_from_config(user_input)
    except ProviderError:
        errors["base"] = "provider_not_configured"
    return errors


async def _async_apply_zone_map(
    hass: Any,
    camera_entity: str,
    uploaded_file_id: str | None,
    clear_zone_map: bool,
) -> None:
    """Persist an uploaded map or remove the existing map."""
    if uploaded_file_id and clear_zone_map:
        raise ZoneMapError("Choose an overlay map upload or removal, not both")
    if uploaded_file_id:
        await hass.async_add_executor_job(
            save_uploaded_zone_map_file,
            hass,
            uploaded_file_id,
            camera_entity,
        )
    elif clear_zone_map:
        await hass.async_add_executor_job(remove_zone_map, hass, camera_entity)


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
            uploaded_file_id = user_input.pop(CONF_ZONE_MAP_FILE, None)
            clear_zone_map = bool(user_input.pop(CONF_CLEAR_ZONE_MAP, False))
            errors = _validate_entities_and_provider(self.hass, user_input)
            if uploaded_file_id and clear_zone_map:
                errors[CONF_ZONE_MAP_FILE] = "zone_map_conflict"
            if not errors:
                camera_entity = str(user_input[CONF_CAMERA_ENTITY])
                await self.async_set_unique_id(camera_entity)
                self._abort_if_unique_id_configured()
                try:
                    await _async_apply_zone_map(
                        self.hass,
                        camera_entity,
                        uploaded_file_id,
                        clear_zone_map,
                    )
                except ZoneMapError:
                    errors[CONF_ZONE_MAP_FILE] = "invalid_zone_map"
                else:
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
            uploaded_file_id = user_input.pop(CONF_ZONE_MAP_FILE, None)
            clear_zone_map = bool(user_input.pop(CONF_CLEAR_ZONE_MAP, False))
            errors = _validate_entities_and_provider(self.hass, user_input)
            if uploaded_file_id and clear_zone_map:
                errors[CONF_ZONE_MAP_FILE] = "zone_map_conflict"
            if not errors:
                try:
                    await _async_apply_zone_map(
                        self.hass,
                        str(user_input[CONF_CAMERA_ENTITY]),
                        uploaded_file_id,
                        clear_zone_map,
                    )
                except ZoneMapError:
                    errors[CONF_ZONE_MAP_FILE] = "invalid_zone_map"
                else:
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


