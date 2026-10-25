"""Rollo-Automatik: Rollladensteuerung pro Raum."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, HomeAssistant, callback

from .controller import RoomController

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

type RolloConfigEntry = ConfigEntry[RoomController]


async def async_setup_entry(hass: HomeAssistant, entry: RolloConfigEntry) -> bool:
    controller = RoomController(hass, entry)
    await controller.async_load_conditions()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Erst nach dem Start auswerten, damit alle Zustände geladen sind
    if hass.state is CoreState.running:
        controller.async_start()
    else:

        @callback
        def _start(_: Event) -> None:
            controller.async_start()

        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start))

    entry.async_on_unload(controller.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: RolloConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: RolloConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
