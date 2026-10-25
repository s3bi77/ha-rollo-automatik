"""Gemeinsame Basis der Entitäten."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .const import CONF_INITIAL_VALUES
from .controller import RoomController


class RolloEntity(Entity):
    """Entität am Raum-Gerät mit fester Entity-ID wie im Node-RED-Subflow."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: RoomController, domain: str, key: str) -> None:
        self.controller = controller
        self.key = key
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = controller.device_info
        self.entity_id = f"{domain}.{controller.object_id(key)}"

    def initial_value(self) -> str | None:
        """Wert, der beim Anlegen von Node-RED übernommen wurde."""
        return self.controller.entry.data.get(CONF_INITIAL_VALUES, {}).get(self.entity_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.add_listener(self.async_write_ha_state))
