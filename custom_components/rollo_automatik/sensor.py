"""Status-Sensor: Zielposition und Grund pro Rollo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RolloConfigEntry
from .const import SENSOR_STATUS, SWITCH_AUTOMATION
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
        super().__init__(controller, SENSOR_STATUS)

    def _name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    @property
    def native_value(self) -> str | None:
        if not self.controller.switches[SWITCH_AUTOMATION]:
            return "Automatik aus"
        result = self.controller.last_result
        if result is None:
            return None
        parts = []
        for cover in result.covers:
            target = "–" if cover.target is None else f"{cover.target:g} %"
            reason = f" ({cover.reason})" if cover.reason else ""
            parts.append(f"{self._name(cover.cover_entity)}: {target}{reason}")
        return "; ".join(parts)[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self.controller.last_result
        if result is None:
            return None
        return {
            "anwesenheit": result.presence,
            "hell": result.bright,
            "kalt": result.cold,
            "rollos": {
                cover.cover_entity: {
                    "ziel": cover.target,
                    "grund": cover.reason,
                    "regeln": [f"{reason}: {value:g}" for reason, value in cover.constraints],
                    "sonne_direkt": cover.sun_direct,
                    "gefahren": cover.move,
                    "nicht_gefahren_weil": cover.skip_reason,
                }
                for cover in result.covers
            },
        }
