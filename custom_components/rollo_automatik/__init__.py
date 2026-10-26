"""Rollo-Automatik: Rollladensteuerung pro Raum."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .controller import RoomController

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

type RolloConfigEntry = ConfigEntry[RoomController]


@callback
def _fix_doubled_area_ids(hass: HomeAssistant, entry: ConfigEntry, area_name: str) -> None:
    """Korrigiert IDs wie switch.wohnzimmer_wohnzimmer_rollos_automatik.

    Bis 0.2.1 enthielt der Gerätename den Bereich, den Home Assistant der
    Entity-ID zusätzlich voranstellt.
    """
    registry = er.async_get(hass)
    slug = slugify(area_name)
    doubled = f"{slug}_{slug}_rollos_"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        domain, object_id = reg_entry.entity_id.split(".", 1)
        if not object_id.startswith(doubled):
            continue
        new_id = f"{domain}.{slug}_rollos_{object_id[len(doubled):]}"
        if registry.async_get(new_id) is None and hass.states.get(new_id) is None:
            registry.async_update_entity(reg_entry.entity_id, new_entity_id=new_id)


async def async_setup_entry(hass: HomeAssistant, entry: RolloConfigEntry) -> bool:
    controller = RoomController(hass, entry)
    _fix_doubled_area_ids(hass, entry, controller.area_name)
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
