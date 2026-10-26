"""Konstanten der Rollo-Automatik."""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "rollo_automatik"

# Raum
CONF_AREA = "area"
CONF_COVERS = "covers"
CONF_PRESENCE_ENTITY = "presence_entity"
CONF_SLEEP_ENTITY = "sleep_entity"
CONF_CLIMATE_ENTITY = "climate_entity"

# Pro Rollo
CONF_COVER_ENTITY = "entity_id"
CONF_WINDOW_ENTITY = "window_entity"
CONF_ORIENTATION = "orientation"
CONF_SHADING_POSITION = "shading_position"
CONF_SHADING_CONDITIONS = "shading_conditions"

# Außen
CONF_ILLUMINANCE_ENTITY = "illuminance_entity"
CONF_TEMPERATURE_ENTITY = "temperature_entity"
CONF_DUSK_ENTITY = "dusk_entity"
CONF_HOUSE_PRESENCE_ENTITY = "house_presence_entity"

OUTDOOR_KEYS = (
    CONF_ILLUMINANCE_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_DUSK_ENTITY,
    CONF_HOUSE_PRESENCE_ENTITY,
)

SUN_ENTITY = "sun.sun"

# Himmelsrichtung der Fensterfläche (Azimut in Grad)
ORIENTATIONS = {
    "n": 0,
    "ne": 45,
    "e": 90,
    "se": 135,
    "s": 180,
    "sw": 225,
    "w": 270,
    "nw": 315,
}
DEFAULT_ORIENTATION = "s"


@dataclass(frozen=True)
class NumberSpec:
    """Eine Einstellungs-Zahl am Raum-Gerät."""

    key: str
    min_value: float
    max_value: float
    step: float
    default: float
    unit: str | None
    sleep_only: bool = False


NUMBERS: tuple[NumberSpec, ...] = (
    NumberSpec("sleep_position", 0, 100, 1, 0, "%", sleep_only=True),
    NumberSpec("sleep_window_position", 0, 100, 1, 20, "%", sleep_only=True),
    NumberSpec("window_position", 0, 100, 1, 100, "%"),
    NumberSpec("shading_position", 0, 100, 1, 50, "%"),
    NumberSpec("illuminance_threshold", 0, 100000, 50, 1500, "lx"),
    NumberSpec("illuminance_hysteresis", 0, 10000, 10, 100, "lx"),
    NumberSpec("cold_threshold", -20, 30, 0.5, 5, "°C"),
    NumberSpec("deadband", 0, 20, 1, 5, "%"),
)

SWITCH_AUTOMATION = "automation"
SWITCH_SHADING = "shading"
SWITCHES: dict[str, bool] = {
    SWITCH_AUTOMATION: True,
    SWITCH_SHADING: False,
}

SENSOR_STATUS = "status"
