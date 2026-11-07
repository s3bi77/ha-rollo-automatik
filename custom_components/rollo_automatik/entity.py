"""Gemeinsame Basis der Entitäten."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .controller import RoomController


class RolloEntity(Entity):
    """Entität am Raum-Gerät."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: RoomController, key: str) -> None:
        self.controller = controller
        self.key = key
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = controller.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.add_listener(self.async_write_ha_state))
