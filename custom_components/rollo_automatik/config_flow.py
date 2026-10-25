"""Einrichtung über die Oberfläche: Bereich → Rollos → je Rollo → Außensensoren."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    condition,
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .const import (
    CONF_AREA,
    CONF_CLIMATE_ENTITY,
    CONF_COVER_ENTITY,
    CONF_COVERS,
    CONF_DUSK_ENTITY,
    CONF_ILLUMINANCE_ENTITY,
    CONF_ORIENTATION,
    CONF_PRESENCE_ENTITY,
    CONF_PRESENCE_LABEL,
    CONF_SHADING_CONDITIONS,
    CONF_SHADING_POSITION,
    CONF_SLEEP_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_ENTITY,
    DEFAULT_ORIENTATION,
    DOMAIN,
    ORIENTATIONS,
    OUTDOOR_KEYS,
)

SECTION_COVERS = "covers_section"
SECTION_SENSORS = "sensors_section"
SECTION_WINDOW = "window_section"
SECTION_SUN = "sun_section"
SECTION_OUTDOOR = "outdoor_section"
SECTION_HOUSE = "house_section"

WINDOW_CLASSES = {"window", "door", "opening", "garage_door"}
PRESENCE_CLASSES = {"presence", "occupancy", "motion"}


def area_entities(
    hass: HomeAssistant,
    area_id: str,
    domains: set[str],
    device_classes: set[str] | None = None,
) -> list[str]:
    """Entitäten eines Bereichs, auch über das Gerät zugeordnete."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    found: list[str] = []
    for entry in entities.entities.values():
        if entry.domain not in domains or entry.disabled:
            continue
        area = entry.area_id
        if area is None and entry.device_id and (device := devices.async_get(entry.device_id)):
            area = device.area_id
        if area != area_id:
            continue
        if device_classes and (entry.device_class or entry.original_device_class) not in device_classes:
            continue
        found.append(entry.entity_id)
    return sorted(found)


def _entity_selector(
    domains: list[str], candidates: list[str], *, multiple: bool = False
) -> selector.EntitySelector:
    config: dict[str, Any] = {"filter": [{"domain": d} for d in domains], "multiple": multiple}
    if candidates:
        config["include_entities"] = candidates
    return selector.EntitySelector(selector.EntitySelectorConfig(**config))


def _first(candidates: list[str]) -> str | None:
    return candidates[0] if len(candidates) == 1 else None


class _RoomSteps:
    """Gemeinsame Schritte für Einrichtung und Bearbeitung."""

    hass: HomeAssistant
    area_id: str
    data: dict[str, Any]
    previous_covers: dict[str, dict[str, Any]]
    cover_queue: list[str]
    cover_total: int

    def _area_name(self) -> str:
        area = ar.async_get(self.hass).async_get_area(self.area_id)
        return area.name if area else self.area_id

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            covers = user_input.get(SECTION_COVERS, {}).get(CONF_COVERS) or []
            sensors = user_input.get(SECTION_SENSORS, {})
            if not covers:
                errors["base"] = "no_covers"
            else:
                self.data.update(
                    {
                        key: sensors.get(key)
                        for key in (CONF_PRESENCE_ENTITY, CONF_SLEEP_ENTITY, CONF_CLIMATE_ENTITY)
                    }
                )
                self.cover_queue = list(covers)
                self.cover_total = len(covers)
                self.data[CONF_COVERS] = []
                return await self.async_step_cover()

        covers = area_entities(self.hass, self.area_id, {"cover"})
        presence = area_entities(self.hass, self.area_id, {"binary_sensor"}, PRESENCE_CLASSES)
        sleep = area_entities(self.hass, self.area_id, {"switch", "input_boolean"})
        climate = area_entities(self.hass, self.area_id, {"climate"})

        suggested = user_input or {
            SECTION_COVERS: {CONF_COVERS: list(self.previous_covers) or covers},
            SECTION_SENSORS: {
                CONF_PRESENCE_ENTITY: self.data.get(
                    CONF_PRESENCE_ENTITY, presence[0] if presence else None
                ),
                CONF_SLEEP_ENTITY: self.data.get(CONF_SLEEP_ENTITY),
                CONF_CLIMATE_ENTITY: self.data.get(CONF_CLIMATE_ENTITY, _first(climate)),
            },
        }
        schema = vol.Schema(
            {
                vol.Required(SECTION_COVERS): section(
                    vol.Schema(
                        {vol.Optional(CONF_COVERS): _entity_selector(["cover"], covers, multiple=True)}
                    )
                ),
                vol.Required(SECTION_SENSORS): section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_PRESENCE_ENTITY): _entity_selector(["binary_sensor"], presence),
                            vol.Optional(CONF_SLEEP_ENTITY): _entity_selector(
                                ["switch", "input_boolean"], sleep
                            ),
                            vol.Optional(CONF_CLIMATE_ENTITY): _entity_selector(["climate"], climate),
                        }
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"area": self._area_name()},
        )

    async def async_step_cover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        cover_id = self.cover_queue[0]
        errors: dict[str, str] = {}
        if user_input is not None:
            window = user_input.get(SECTION_WINDOW, {})
            sun = user_input.get(SECTION_SUN, {})
            conditions = sun.get(CONF_SHADING_CONDITIONS) or []
            try:
                await condition.async_validate_conditions_config(self.hass, conditions)
            except (HomeAssistantError, vol.Invalid):
                errors["base"] = "invalid_conditions"
            else:
                self.data[CONF_COVERS].append(
                    {
                        CONF_COVER_ENTITY: cover_id,
                        CONF_WINDOW_ENTITY: window.get(CONF_WINDOW_ENTITY),
                        CONF_ORIENTATION: sun.get(CONF_ORIENTATION) or DEFAULT_ORIENTATION,
                        CONF_SHADING_POSITION: sun.get(CONF_SHADING_POSITION),
                        CONF_SHADING_CONDITIONS: conditions,
                    }
                )
                self.cover_queue.pop(0)
                if self.cover_queue:
                    return await self.async_step_cover()
                return await self.async_step_outdoor()

        windows = area_entities(self.hass, self.area_id, {"binary_sensor"}, WINDOW_CLASSES)
        previous = self.previous_covers.get(cover_id, {})
        suggested = user_input or {
            SECTION_WINDOW: {
                CONF_WINDOW_ENTITY: previous.get(CONF_WINDOW_ENTITY, _first(windows)),
            },
            SECTION_SUN: {
                CONF_ORIENTATION: previous.get(CONF_ORIENTATION, DEFAULT_ORIENTATION),
                CONF_SHADING_POSITION: previous.get(CONF_SHADING_POSITION),
                CONF_SHADING_CONDITIONS: previous.get(CONF_SHADING_CONDITIONS),
            },
        }
        schema = vol.Schema(
            {
                vol.Required(SECTION_WINDOW): section(
                    vol.Schema(
                        {vol.Optional(CONF_WINDOW_ENTITY): _entity_selector(["binary_sensor"], windows)}
                    )
                ),
                vol.Required(SECTION_SUN): section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_ORIENTATION): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=list(ORIENTATIONS),
                                    translation_key=CONF_ORIENTATION,
                                    custom_value=True,
                                    mode=selector.SelectSelectorMode.DROPDOWN,
                                )
                            ),
                            vol.Optional(CONF_SHADING_POSITION): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=0,
                                    max=100,
                                    step=1,
                                    unit_of_measurement="%",
                                    mode=selector.NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Optional(CONF_SHADING_CONDITIONS): selector.ConditionSelector(),
                        }
                    )
                ),
            }
        )
        state = self.hass.states.get(cover_id)
        return self.async_show_form(
            step_id="cover",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={
                "cover": state.name if state else cover_id,
                "area": self._area_name(),
                "index": str(self.cover_total - len(self.cover_queue) + 1),
                "total": str(self.cover_total),
            },
        )

    async def async_step_outdoor(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            values = {**user_input.get(SECTION_OUTDOOR, {}), **user_input.get(SECTION_HOUSE, {})}
            self.data.update({key: values.get(key) for key in OUTDOOR_KEYS})
            return self._finish()

        values = {key: self.data.get(key) for key in OUTDOOR_KEYS}
        if not any(values.values()):
            # Vom zuletzt eingerichteten Raum übernehmen
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                conf = {**entry.data, **entry.options}
                values = {key: conf.get(key) for key in OUTDOOR_KEYS}
        suggested = {
            SECTION_OUTDOOR: {
                key: values.get(key)
                for key in (CONF_ILLUMINANCE_ENTITY, CONF_TEMPERATURE_ENTITY, CONF_DUSK_ENTITY)
            },
            SECTION_HOUSE: {CONF_PRESENCE_LABEL: values.get(CONF_PRESENCE_LABEL)},
        }
        schema = vol.Schema(
            {
                vol.Required(SECTION_OUTDOOR): section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_ILLUMINANCE_ENTITY): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="sensor")
                            ),
                            vol.Optional(CONF_TEMPERATURE_ENTITY): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="sensor")
                            ),
                            vol.Optional(CONF_DUSK_ENTITY): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="binary_sensor")
                            ),
                        }
                    )
                ),
                vol.Required(SECTION_HOUSE): section(
                    vol.Schema({vol.Optional(CONF_PRESENCE_LABEL): selector.LabelSelector()})
                ),
            }
        )
        return self.async_show_form(
            step_id="outdoor",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )

    def _finish(self) -> ConfigFlowResult:
        raise NotImplementedError


class RolloAutomatikConfigFlow(_RoomSteps, ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.previous_covers = {}
        self.cover_queue = []
        self.cover_total = 0

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.area_id = user_input[CONF_AREA]
            await self.async_set_unique_id(self.area_id)
            self._abort_if_unique_id_configured()
            self.data[CONF_AREA] = self.area_id
            return await self.async_step_room()

        schema = vol.Schema(
            {
                vol.Required(CONF_AREA): selector.AreaSelector(
                    selector.AreaSelectorConfig(entity=selector.EntityFilterSelectorConfig(domain="cover"))
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(title=self._area_name(), data=self.data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RolloAutomatikOptionsFlow()


class RolloAutomatikOptionsFlow(_RoomSteps, OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        self.area_id = current[CONF_AREA]
        self.data = {key: value for key, value in current.items() if key not in (CONF_AREA, CONF_COVERS)}
        self.previous_covers = {c[CONF_COVER_ENTITY]: c for c in current.get(CONF_COVERS, [])}
        self.cover_queue = []
        self.cover_total = 0
        return await self.async_step_room()

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self.data)
