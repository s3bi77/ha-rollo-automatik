"""Einrichtung eines Raums über die Oberfläche."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_AZIMUTH_ENTITY,
    CONF_DUSK_ENTITY,
    CONF_ELEVATION_ENTITY,
    CONF_IMPORT_NODERED,
    CONF_INITIAL_VALUES,
    CONF_LUX_ENTITY,
    CONF_PREFIX,
    CONF_PRESENCE_LABEL,
    CONF_ROLLOS,
    CONF_ROOM_NAME,
    CONF_SLEEP_MODE,
    CONF_TEMP_ENTITY,
    DEFAULT_AZIMUTH_ENTITY,
    DEFAULT_DUSK_ENTITY,
    DEFAULT_ELEVATION_ENTITY,
    DEFAULT_LUX_ENTITY,
    DEFAULT_PRESENCE_LABEL,
    DEFAULT_ROLLOS,
    DEFAULT_TEMP_ENTITY,
    DOMAIN,
    ROLLO_COVER,
    ROLLO_DIRECTION,
    ROLLO_OVERRIDE_SUN_POS,
    ROLLO_SUFFIX,
    ROLLO_SUN_RULE,
    ROLLO_WINDOW,
)
from .logic import validate_rule

PREFIX_RE = re.compile(r"^[a-z0-9_]+$")
ROLLO_KEYS = {
    ROLLO_SUFFIX,
    ROLLO_DIRECTION,
    ROLLO_SUN_RULE,
    ROLLO_OVERRIDE_SUN_POS,
    ROLLO_COVER,
    ROLLO_WINDOW,
}


def validate_rollos(rollos: Any) -> list[dict[str, Any]]:
    """Prüft die Rollo-Liste. Wirft ValueError mit Fehlerschlüssel."""
    if not isinstance(rollos, list) or not rollos:
        raise ValueError("rollos_empty")
    suffixes: set[str] = set()
    for rollo in rollos:
        if not isinstance(rollo, dict) or not PREFIX_RE.match(str(rollo.get(ROLLO_SUFFIX, ""))):
            raise ValueError("rollo_suffix")
        if set(rollo) - ROLLO_KEYS:
            raise ValueError("rollo_unknown_key")
        if rollo[ROLLO_SUFFIX] in suffixes:
            raise ValueError("rollo_duplicate")
        suffixes.add(rollo[ROLLO_SUFFIX])
        if int(rollo.get(ROLLO_DIRECTION, 0)) not in (0, 1, 2, 3):
            raise ValueError("rollo_direction")
        try:
            validate_rule(rollo.get(ROLLO_SUN_RULE))
        except ValueError as err:
            raise ValueError("rollo_sun_rule") from err
    return rollos


def _sensor_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    entity = selector.EntitySelector()
    return {
        vol.Required(CONF_LUX_ENTITY, default=defaults.get(CONF_LUX_ENTITY, DEFAULT_LUX_ENTITY)): entity,
        vol.Required(CONF_TEMP_ENTITY, default=defaults.get(CONF_TEMP_ENTITY, DEFAULT_TEMP_ENTITY)): entity,
        vol.Required(CONF_DUSK_ENTITY, default=defaults.get(CONF_DUSK_ENTITY, DEFAULT_DUSK_ENTITY)): entity,
        vol.Required(
            CONF_AZIMUTH_ENTITY, default=defaults.get(CONF_AZIMUTH_ENTITY, DEFAULT_AZIMUTH_ENTITY)
        ): entity,
        vol.Required(
            CONF_ELEVATION_ENTITY, default=defaults.get(CONF_ELEVATION_ENTITY, DEFAULT_ELEVATION_ENTITY)
        ): entity,
        vol.Required(
            CONF_PRESENCE_LABEL, default=defaults.get(CONF_PRESENCE_LABEL, DEFAULT_PRESENCE_LABEL)
        ): selector.TextSelector(),
    }


def _capture_nodered_values(hass: HomeAssistant, prefix: str, sleep_mode: bool) -> dict[str, str]:
    """Liest die aktuellen Werte der Node-RED-Entitäten, bevor wir sie übernehmen."""
    from . import expected_entity_ids  # noqa: PLC0415

    values: dict[str, str] = {}
    for entity_id in expected_entity_ids(prefix, sleep_mode):
        state = hass.states.get(entity_id)
        if state is not None and state.state not in ("unknown", "unavailable"):
            values[entity_id] = state.state
    return values


class RolloAutomatikConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            prefix = user_input.get(CONF_PREFIX) or slugify(user_input[CONF_ROOM_NAME])
            try:
                if not PREFIX_RE.match(prefix):
                    raise ValueError("prefix")
                validate_rollos(user_input[CONF_ROLLOS])
            except ValueError as err:
                errors["base"] = str(err)
            else:
                await self.async_set_unique_id(prefix)
                self._abort_if_unique_id_configured()
                data = {**user_input, CONF_PREFIX: prefix}
                if user_input.get(CONF_IMPORT_NODERED):
                    data[CONF_INITIAL_VALUES] = _capture_nodered_values(
                        self.hass, prefix, user_input[CONF_SLEEP_MODE]
                    )
                return self.async_create_entry(title=user_input[CONF_ROOM_NAME], data=data)

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME, default=defaults.get(CONF_ROOM_NAME, "")): str,
                vol.Optional(CONF_PREFIX, default=defaults.get(CONF_PREFIX, "")): str,
                vol.Required(CONF_SLEEP_MODE, default=defaults.get(CONF_SLEEP_MODE, True)): bool,
                vol.Required(
                    CONF_ROLLOS, default=defaults.get(CONF_ROLLOS, DEFAULT_ROLLOS)
                ): selector.ObjectSelector(),
                vol.Required(
                    CONF_IMPORT_NODERED, default=defaults.get(CONF_IMPORT_NODERED, True)
                ): bool,
                **_sensor_schema(defaults),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RolloAutomatikOptionsFlow()


class RolloAutomatikOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            try:
                validate_rollos(user_input[CONF_ROLLOS])
            except ValueError as err:
                errors["base"] = str(err)
            else:
                return self.async_create_entry(data=user_input)

        defaults = user_input or current
        schema = vol.Schema(
            {
                vol.Required(CONF_ROLLOS, default=defaults.get(CONF_ROLLOS)): selector.ObjectSelector(),
                **_sensor_schema(defaults),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
