"""Status-Sensor: Zielposition und Begründung pro Rollo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RolloConfigEntry
from .const import SENSOR_STATUS
from .controller import RoomController
from .entity import RolloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RolloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RolloStatusSensor(entry.runtime_data)])


class RolloStatusSensor(RolloEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: RoomController) -> None:
        super().__init__(controller, "sensor", SENSOR_STATUS)

    @property
    def native_value(self) -> str | None:
        if not self.controller.switches["automatik_aktiv"]:
            return "Automatik aus"
        result = self.controller.last_result
        if result is None:
            return None
        return result.summary[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self.controller.last_result
        if result is None:
            return None
        return {
            "praesenz": result.presence,
            "hell": result.lux_above,
            "kalt": result.temp_below,
            "rollos": {
                r.suffix: {
                    "rollo": r.cover_entity,
                    "ziel": r.target,
                    "sonne_direkt": result.sun_direct.get(r.suffix),
                    "gefahren": r.move,
                    "nicht_gefahren_weil": r.skip_reason,
                    "begruendung": r.reason,
                }
                for r in result.rollos
            },
        }
