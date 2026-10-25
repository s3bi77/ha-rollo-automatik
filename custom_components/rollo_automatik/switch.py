"""Schalter pro Raum: Automatik und Beschattung."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RolloConfigEntry
from .const import SWITCHES
from .controller import RoomController
from .entity import RolloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RolloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    async_add_entities(RolloSwitch(controller, key) for key in SWITCHES)


class RolloSwitch(RolloEntity, SwitchEntity, RestoreEntity):
    def __init__(self, controller: RoomController, key: str) -> None:
        super().__init__(controller, key)

    @property
    def is_on(self) -> bool:
        return self.controller.switches[self.key]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self.controller.set_switch(self.key, last.state == STATE_ON, evaluate_after=False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.set_switch(self.key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.set_switch(self.key, False)
