"""Steuerung eines Raums: sammelt Zustände, wertet aus und fährt die Rollos."""

from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, condition, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_AREA,
    CONF_CLIMATE_ENTITY,
    CONF_COVER_ENTITY,
    CONF_COVERS,
    CONF_DUSK_ENTITY,
    CONF_HOUSE_PRESENCE_ENTITY,
    CONF_ILLUMINANCE_ENTITY,
    CONF_ORIENTATION,
    CONF_PRESENCE_ENTITY,
    CONF_REVEAL_DEPTH,
    CONF_SHADING_CONDITIONS,
    CONF_SHADING_POSITION,
    CONF_SLEEP_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_ENTITY,
    CONF_WINDOW_HEIGHT,
    CONF_WINDOW_WIDTH,
    DEFAULT_ORIENTATION,
    DEFAULT_REVEAL_DEPTH,
    DOMAIN,
    NUMBERS,
    ORIENTATIONS,
    SUN_ENTITY,
    SWITCH_AUTOMATION,
    SWITCH_SHADING,
    SWITCHES,
)
from .logic import CoverConfig, Inputs, Result, RoomState, Settings, cascade_positions, evaluate

_LOGGER = logging.getLogger(__name__)


def orientation_degrees(value: Any) -> float:
    """Wandelt eine Himmelsrichtung oder Gradzahl in Grad um."""
    if value in ORIENTATIONS:
        return ORIENTATIONS[value]
    try:
        return float(value) % 360
    except (TypeError, ValueError):
        return ORIENTATIONS[DEFAULT_ORIENTATION]


class RoomController:
    """Hält Einstellungen und Gedächtnis eines Raums."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        conf = {**entry.data, **entry.options}
        self.area_id: str = conf[CONF_AREA]
        area = ar.async_get(hass).async_get_area(self.area_id)
        self.area_name = area.name if area else entry.title

        self.presence_entity: str | None = conf.get(CONF_PRESENCE_ENTITY)
        self.sleep_entity: str | None = conf.get(CONF_SLEEP_ENTITY)
        self.climate_entity: str | None = conf.get(CONF_CLIMATE_ENTITY)
        self.illuminance_entity: str | None = conf.get(CONF_ILLUMINANCE_ENTITY)
        self.temperature_entity: str | None = conf.get(CONF_TEMPERATURE_ENTITY)
        self.dusk_entity: str | None = conf.get(CONF_DUSK_ENTITY)
        self.house_presence_entity: str | None = conf.get(CONF_HOUSE_PRESENCE_ENTITY)

        self.cover_conf: list[dict[str, Any]] = conf.get(CONF_COVERS, [])
        self.covers = [
            CoverConfig(
                cover_entity=c[CONF_COVER_ENTITY],
                window_entity=c.get(CONF_WINDOW_ENTITY),
                orientation=orientation_degrees(c.get(CONF_ORIENTATION, DEFAULT_ORIENTATION)),
                shading_position=c.get(CONF_SHADING_POSITION),
                width=c.get(CONF_WINDOW_WIDTH),
                height=c.get(CONF_WINDOW_HEIGHT),
                reveal=(c.get(CONF_REVEAL_DEPTH) or DEFAULT_REVEAL_DEPTH) / 100,
            )
            for c in self.cover_conf
        ]
        self._shading_checks: dict[str, Callable[..., bool]] = {}
        self._condition_entities: set[str] = set()

        self.has_sleep = self.sleep_entity is not None
        self.numbers: dict[str, float] = {
            spec.key: spec.default for spec in NUMBERS if self.has_sleep or not spec.sleep_only
        }
        self.switches: dict[str, bool] = dict(SWITCHES)
        self.state = RoomState()
        self.last_result: Result | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsub: list[Callable[[], None]] = []
        self._ready = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            # Der Bereich steht schon am Gerät; HA stellt ihn der Entity-ID voran
            name="Rollos",
            manufacturer="Rollo Automatik",
            model="Raumsteuerung",
            suggested_area=self.area_name,
        )

    # --- Lebenszyklus ----------------------------------------------------

    async def async_load_conditions(self) -> None:
        """Bereitet die Beschattungsbedingungen der Rollos vor."""
        for cover in self.cover_conf:
            configs = cover.get(CONF_SHADING_CONDITIONS) or []
            if not configs:
                continue
            try:
                validated = await condition.async_validate_conditions_config(self.hass, configs)
                self._shading_checks[cover[CONF_COVER_ENTITY]] = await condition.async_conditions_from_config(
                    self.hass, validated, _LOGGER, f"Beschattung {cover[CONF_COVER_ENTITY]}"
                )
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.error("Ungültige Beschattungsbedingung für %s: %s", cover[CONF_COVER_ENTITY], err)
                self._shading_checks[cover[CONF_COVER_ENTITY]] = lambda *_: False
                continue
            for conf in validated:
                self._condition_entities |= condition.async_extract_entities(conf)

    @callback
    def async_start(self) -> None:
        self._ready = True
        self._unsub.append(
            async_track_state_change_event(self.hass, self._watched_entities(), self._on_state_change)
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        self._ready = False

    def _watched_entities(self) -> list[str]:
        entities = {SUN_ENTITY, *self._condition_entities}
        for entity_id in (
            self.illuminance_entity,
            self.temperature_entity,
            self.dusk_entity,
            self.presence_entity,
            self.house_presence_entity,
            self.sleep_entity,
            self.climate_entity,
        ):
            if entity_id:
                entities.add(entity_id)
        for cover in self.covers:
            entities.add(cover.cover_entity)
            if cover.window_entity:
                entities.add(cover.window_entity)
        return sorted(entities)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        old = event.data["old_state"]
        new = event.data["new_state"]
        if event.data["entity_id"] == SUN_ENTITY:
            # Sonnenstand steckt in Attributen; nur auf ganze Grad reagieren
            if old and new and _sun_tuple(old.attributes) == _sun_tuple(new.attributes):
                return
        elif old is not None and new is not None and old.state == new.state:
            return
        self.async_evaluate()

    # --- Einstellungen von den Entitäten ---------------------------------

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def set_number(self, key: str, value: float, *, evaluate_after: bool = True) -> None:
        self.numbers[key] = value
        if self.has_sleep and evaluate_after:
            self.numbers.update(
                cascade_positions(
                    key,
                    sleep_position=self.numbers["sleep_position"],
                    sleep_window_position=self.numbers["sleep_window_position"],
                    window_position=self.numbers["window_position"],
                )
            )
        self._notify()
        if evaluate_after:
            self.async_evaluate()

    @callback
    def set_switch(self, key: str, value: bool, *, evaluate_after: bool = True) -> None:
        self.switches[key] = value
        self._notify()
        if evaluate_after:
            self.async_evaluate()

    # --- Auswertung -------------------------------------------------------

    def _state(self, entity_id: str | None) -> str | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.state

    def _float(self, entity_id: str | None) -> float | None:
        value = self._state(entity_id)
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    def _attr(self, entity_id: str, attribute: str) -> float | None:
        state = self.hass.states.get(entity_id)
        value = state.attributes.get(attribute) if state else None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _dusk(self) -> bool:
        if self.dusk_entity:
            return self._state(self.dusk_entity) == STATE_ON
        return self._state(SUN_ENTITY) == "below_horizon"

    def _inputs(self) -> Inputs:
        # Ohne Sensor oder bei unbekanntem Zustand gilt das Haus als bewohnt
        house = self._state(self.house_presence_entity) != STATE_OFF if self.house_presence_entity else True
        return Inputs(
            illuminance=self._float(self.illuminance_entity),
            temperature=self._float(self.temperature_entity),
            hvac=self._state(self.climate_entity) or "",
            dusk=self._dusk(),
            room_presence=self._state(self.presence_entity) == STATE_ON,
            house_presence=house,
            sleep=self.has_sleep and self._state(self.sleep_entity) == STATE_ON,
            sun_azimuth=self._attr(SUN_ENTITY, "azimuth"),
            sun_elevation=self._attr(SUN_ENTITY, "elevation"),
            window_open={
                c.cover_entity: self._state(c.window_entity) == STATE_ON for c in self.covers
            },
            cover_position={
                c.cover_entity: self._attr(c.cover_entity, "current_position") for c in self.covers
            },
            shading_allowed={
                entity_id: bool(check()) for entity_id, check in self._shading_checks.items()
            },
        )

    def _settings(self) -> Settings:
        return Settings(shading=self.switches[SWITCH_SHADING], **self.numbers)

    @callback
    def async_evaluate(self) -> None:
        """Wertet aus und fährt Rollos, deren Regeln sich geändert haben."""
        if not self._ready or not self.switches[SWITCH_AUTOMATION]:
            return
        result = evaluate(self.covers, self._settings(), self._inputs(), self.state, time.time())
        self.last_result = result
        for cover in result.moves:
            _LOGGER.debug("%s: %s auf %s (%s)", self.area_name, cover.cover_entity, cover.target, cover.reason)
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    {"entity_id": cover.cover_entity, "position": int(cover.target)},
                    blocking=False,
                )
            )
        self._notify()


def _sun_tuple(attributes: Any) -> tuple[int | None, int | None]:
    def rounded(value: Any) -> int | None:
        try:
            return round(float(value))
        except (TypeError, ValueError):
            return None

    return rounded(attributes.get("azimuth")), rounded(attributes.get("elevation"))
