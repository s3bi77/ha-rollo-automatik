"""Steuerung eines Raums: sammelt Zustände, wertet aus und fährt die Rollos."""

from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_AZIMUTH_ENTITY,
    CONF_DUSK_ENTITY,
    CONF_ELEVATION_ENTITY,
    CONF_LUX_ENTITY,
    CONF_PREFIX,
    CONF_PRESENCE_LABEL,
    CONF_ROLLOS,
    CONF_ROOM_NAME,
    CONF_SLEEP_MODE,
    CONF_TEMP_ENTITY,
    DEFAULT_AZIMUTH_ENTITY,
    DEFAULT_DUSK_ENTITY,
    DEFAULT_ELEVATION_ENTITY,
    DEFAULT_LUX_ENTITY,
    DEFAULT_PRESENCE_LABEL,
    DEFAULT_TEMP_ENTITY,
    DOMAIN,
    NUMBER_TO_SETTING,
    NUMBERS,
    ROLLO_COVER,
    ROLLO_DIRECTION,
    ROLLO_OVERRIDE_SUN_POS,
    ROLLO_SUFFIX,
    ROLLO_SUN_RULE,
    ROLLO_WINDOW,
    SWITCH_AUTOMATIK_AKTIV,
    SWITCH_BESCHATTUNG,
    SWITCHES,
)
from .logic import (
    Inputs,
    Result,
    RolloConfig,
    RoomState,
    Settings,
    cascade_positions,
    evaluate,
)

_LOGGER = logging.getLogger(__name__)


def _rule_entities(rule: Any) -> list[str]:
    if not isinstance(rule, dict):
        return []
    if "entity" in rule:
        return [rule["entity"]]
    return [e for sub in rule.get("allOf", []) + rule.get("anyOf", []) for e in _rule_entities(sub)]


class RoomController:
    """Hält Einstellungen und Gedächtnis eines Raums."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        conf = {**entry.data, **entry.options}
        self.room_name: str = conf[CONF_ROOM_NAME]
        self.prefix: str = conf[CONF_PREFIX]
        self.sleep_mode: bool = conf.get(CONF_SLEEP_MODE, True)
        self.lux_entity: str = conf.get(CONF_LUX_ENTITY, DEFAULT_LUX_ENTITY)
        self.temp_entity: str = conf.get(CONF_TEMP_ENTITY, DEFAULT_TEMP_ENTITY)
        self.dusk_entity: str = conf.get(CONF_DUSK_ENTITY, DEFAULT_DUSK_ENTITY)
        self.azimuth_entity: str = conf.get(CONF_AZIMUTH_ENTITY, DEFAULT_AZIMUTH_ENTITY)
        self.elevation_entity: str = conf.get(CONF_ELEVATION_ENTITY, DEFAULT_ELEVATION_ENTITY)
        self.presence_label: str = conf.get(CONF_PRESENCE_LABEL, DEFAULT_PRESENCE_LABEL)

        self.rollos: list[RolloConfig] = [
            RolloConfig(
                suffix=r[ROLLO_SUFFIX],
                cover_entity=r.get(ROLLO_COVER) or f"cover.{self.prefix}_rollo_{r[ROLLO_SUFFIX]}",
                window_entity=r.get(ROLLO_WINDOW)
                or f"binary_sensor.{self.prefix}_{r[ROLLO_SUFFIX]}_geoffnet",
                direction=int(r.get(ROLLO_DIRECTION, 0)),
                sun_rule=r.get(ROLLO_SUN_RULE),
                override_sun_pos=r.get(ROLLO_OVERRIDE_SUN_POS),
            )
            for r in conf.get(CONF_ROLLOS, [])
        ]

        self.presence_entity = f"binary_sensor.{self.prefix}_prasenz"
        self.sleep_entity = f"switch.{self.prefix}_schlafmodus"
        self.climate_entity = f"climate.{self.prefix}"

        self.numbers: dict[str, float] = {
            spec.key: spec.default
            for spec in NUMBERS
            if self.sleep_mode or not spec.sleep_only
        }
        self.switches: dict[str, bool] = dict(SWITCHES)
        self.state = RoomState()
        self.last_result: Result | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsub: list[Callable[[], None]] = []
        self._ready = False

    # --- Gerät und IDs -------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=f"{self.room_name} Rollo",
            manufacturer="Rollo Automatik",
            model="Raum",
        )

    def object_id(self, key: str) -> str:
        return f"{self.prefix}_rollo_{key}"

    # --- Lebenszyklus ----------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Beginnt, auf Zustandsänderungen zu hören."""
        self._ready = True
        self._unsub.append(
            async_track_state_change_event(self.hass, self._watched_entities(), self._on_state_change)
        )
        # Präsenz-Label: die Liste der Entitäten kann sich ändern
        self._unsub.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_updated
            )
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        self._ready = False

    @callback
    def _on_registry_updated(self, event: Event) -> None:
        if event.data.get("action") != "update" or "labels" not in event.data.get("changes", {}):
            return
        # Neu abonnieren, damit neue Präsenz-Entitäten mitzählen
        self.async_stop()
        self.async_start()

    def _house_presence_entities(self) -> list[str]:
        label = lr.async_get(self.hass).async_get_label_by_name(self.presence_label)
        if label is None:
            return []
        registry = er.async_get(self.hass)
        return [e.entity_id for e in er.async_entries_for_label(registry, label.label_id)]

    def _watched_entities(self) -> list[str]:
        entities = {
            self.lux_entity,
            self.temp_entity,
            self.dusk_entity,
            self.azimuth_entity,
            self.elevation_entity,
            self.presence_entity,
            self.sleep_entity,
            self.climate_entity,
            *self._house_presence_entities(),
        }
        for rollo in self.rollos:
            entities.update((rollo.cover_entity, rollo.window_entity))
            entities.update(_rule_entities(rollo.sun_rule))
        return sorted(entities)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        old = event.data["old_state"]
        new = event.data["new_state"]
        # Wie in Node-RED: nur echte Zustandswechsel, keine reinen Attribut-Updates
        if old is not None and new is not None and old.state == new.state:
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
        if self.sleep_mode and evaluate_after:
            self._cascade(key)
        self._notify()
        if evaluate_after:
            self.async_evaluate()

    @callback
    def _cascade(self, changed_key: str) -> None:
        names = {
            "zielposition_schlafmodus": "sleep_pos",
            "zielposition_schlafmodus_fenster_offen": "sleep_window_pos",
            "zielposition_fenster_offen": "window_pos",
        }
        if changed_key not in names:
            return
        updates = cascade_positions(
            names[changed_key],
            sleep_pos=self.numbers["zielposition_schlafmodus"],
            sleep_window_pos=self.numbers["zielposition_schlafmodus_fenster_offen"],
            window_pos=self.numbers["zielposition_fenster_offen"],
        )
        reverse = {v: k for k, v in names.items()}
        for name, value in updates.items():
            self.numbers[reverse[name]] = value

    @callback
    def set_switch(self, key: str, value: bool, *, evaluate_after: bool = True) -> None:
        self.switches[key] = value
        self._notify()
        if evaluate_after:
            self.async_evaluate()

    # --- Auswertung -------------------------------------------------------

    def _state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.state

    def _float(self, entity_id: str) -> float | None:
        value = self._state(entity_id)
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    def _cover_position(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        pos = state.attributes.get("current_position")
        return float(pos) if pos is not None else None

    def _settings(self) -> Settings:
        values = {NUMBER_TO_SETTING[k]: v for k, v in self.numbers.items()}
        return Settings(sun_active=self.switches[SWITCH_BESCHATTUNG], **values)

    def _inputs(self) -> Inputs:
        house = any(self._state(e) == STATE_ON for e in self._house_presence_entities())
        return Inputs(
            lux=self._float(self.lux_entity),
            temp=self._float(self.temp_entity),
            hvac=self._state(self.climate_entity) or "",
            dusk=self._state(self.dusk_entity) == STATE_ON,
            raw_presence=self._state(self.presence_entity) == STATE_ON,
            house_presence=house,
            sleep=self.sleep_mode and self._state(self.sleep_entity) == STATE_ON,
            azimuth=self._float(self.azimuth_entity),
            elevation=self._float(self.elevation_entity),
            window_open={r.suffix: self._state(r.window_entity) == STATE_ON for r in self.rollos},
            cover_pos={r.suffix: self._cover_position(r.cover_entity) for r in self.rollos},
            get_state=lambda entity_id: (s.state if (s := self.hass.states.get(entity_id)) else None),
        )

    @callback
    def async_evaluate(self) -> None:
        """Wertet aus und fährt Rollos, deren Bedingungen sich geändert haben."""
        if not self._ready or not self.switches[SWITCH_AUTOMATIK_AKTIV]:
            return
        result = evaluate(self.rollos, self._settings(), self._inputs(), self.state, time.time())
        self.last_result = result
        for rollo in result.moves:
            _LOGGER.debug(
                "%s: %s auf %s (%s)",
                self.room_name,
                rollo.cover_entity,
                rollo.target,
                "; ".join(rollo.reason),
            )
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    {"entity_id": rollo.cover_entity, "position": int(rollo.target)},
                    blocking=False,
                )
            )
        self._notify()
