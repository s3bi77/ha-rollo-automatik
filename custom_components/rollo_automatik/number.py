"""Einstellungs-Zahlen pro Raum."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RolloConfigEntry
from .const import NUMBERS, NumberSpec
from .controller import RoomController
from .entity import RolloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RolloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    async_add_entities(
        RolloNumber(controller, spec)
        for spec in NUMBERS
        if spec.key in controller.numbers
    )


class RolloNumber(RolloEntity, RestoreNumber):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, controller: RoomController, spec: NumberSpec) -> None:
        super().__init__(controller, "number", spec.key)
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        if spec.unit == "%":
            self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float:
        return self.controller.numbers[self.key]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        value: float | None = None
        if (last := await self.async_get_last_number_data()) is not None:
            value = last.native_value
        if value is None and (initial := self.initial_value()) is not None:
            try:
                value = float(initial)
            except ValueError:
                value = None
        if value is not None:
            self.controller.set_number(self.key, value, evaluate_after=False)

    async def async_set_native_value(self, value: float) -> None:
        self.controller.set_number(self.key, value)
