"""Rollo-Automatik: Rollladensteuerung pro Raum."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_IMPORT_NODERED, CONF_PREFIX, CONF_SLEEP_MODE, NUMBERS, SENSOR_STATUS, SWITCHES
from .controller import RoomController

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

type RolloConfigEntry = ConfigEntry[RoomController]


def expected_entity_ids(prefix: str, sleep_mode: bool) -> list[str]:
    """Die Entity-IDs, die ein Raum anlegt."""
    ids = [
        f"number.{prefix}_rollo_{spec.key}"
        for spec in NUMBERS
        if sleep_mode or not spec.sleep_only
    ]
    ids += [f"switch.{prefix}_rollo_{key}" for key in SWITCHES]
    ids.append(f"sensor.{prefix}_rollo_{SENSOR_STATUS}")
    return ids


@callback
def _release_nodered_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Gibt die IDs der alten Node-RED-Entitäten frei, damit wir sie übernehmen."""
    registry = er.async_get(hass)
    for entity_id in expected_entity_ids(entry.data[CONF_PREFIX], entry.data.get(CONF_SLEEP_MODE, True)):
        reg_entry = registry.async_get(entity_id)
        if reg_entry is None or reg_entry.platform != "nodered":
            continue
        _LOGGER.info("Übernehme %s von Node-RED", entity_id)
        registry.async_remove(entity_id)
        hass.states.async_remove(entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: RolloConfigEntry) -> bool:
    if entry.data.get(CONF_IMPORT_NODERED):
        _release_nodered_entities(hass, entry)

    controller = RoomController(hass, entry)
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
