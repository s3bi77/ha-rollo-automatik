"""Konstanten der Rollo-Automatik."""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "rollo_automatik"

CONF_ROOM_NAME = "room_name"
CONF_PREFIX = "prefix"
CONF_SLEEP_MODE = "sleep_mode"
CONF_ROLLOS = "rollos"
CONF_IMPORT_NODERED = "import_nodered"
CONF_INITIAL_VALUES = "initial_values"

CONF_LUX_ENTITY = "lux_entity"
CONF_TEMP_ENTITY = "temp_entity"
CONF_DUSK_ENTITY = "dusk_entity"
CONF_AZIMUTH_ENTITY = "azimuth_entity"
CONF_ELEVATION_ENTITY = "elevation_entity"
CONF_PRESENCE_LABEL = "presence_label"

DEFAULT_LUX_ENTITY = "sensor.aussen_helligkeit"
DEFAULT_TEMP_ENTITY = "sensor.aussentemperatur"
DEFAULT_DUSK_ENTITY = "binary_sensor.dammerung"
DEFAULT_AZIMUTH_ENTITY = "sensor.sun_solar_azimuth"
DEFAULT_ELEVATION_ENTITY = "sensor.sun_solar_elevation"
DEFAULT_PRESENCE_LABEL = "Präsenz"

# Schlüssel in der Rollo-Liste (gleiche Namen wie im Node-RED-Subflow)
ROLLO_SUFFIX = "suffix"
ROLLO_DIRECTION = "direction"
ROLLO_SUN_RULE = "sunRule"
ROLLO_OVERRIDE_SUN_POS = "overrideSunPos"
ROLLO_COVER = "cover"
ROLLO_WINDOW = "window"

DEFAULT_ROLLOS = [{ROLLO_SUFFIX: "fenster", ROLLO_DIRECTION: 0}]


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


# Die Schlüssel ergeben die Entity-IDs: number.<praefix>_rollo_<key>
NUMBERS: tuple[NumberSpec, ...] = (
    NumberSpec("zielposition_schlafmodus", 0, 100, 1, 0, "%", sleep_only=True),
    NumberSpec("zielposition_schlafmodus_fenster_offen", 0, 100, 1, 20, "%", sleep_only=True),
    NumberSpec("zielposition_fenster_offen", 0, 100, 1, 100, "%"),
    NumberSpec("zielposition_beschattung", 0, 100, 1, 100, "%"),
    NumberSpec("lux_threshold", 0, 10000, 50, 1500, "lx"),
    NumberSpec("lux_hysteresis", 0, 1000, 10, 100, "lx"),
    NumberSpec("kalte_threshold", -20, 30, 0.5, 5, "°C"),
    NumberSpec("automatik_totzone", 0, 20, 1, 5, "%"),
)

SWITCH_AUTOMATIK_AKTIV = "automatik_aktiv"
SWITCH_BESCHATTUNG = "automatische_beschattung"
SWITCHES: dict[str, bool] = {
    SWITCH_AUTOMATIK_AKTIV: True,
    SWITCH_BESCHATTUNG: False,
}

SENSOR_STATUS = "automatik_status"

# Verknüpfung Zahl -> Feld in logic.Settings bzw. cascade_positions
NUMBER_TO_SETTING = {
    "zielposition_schlafmodus": "sleep_pos",
    "zielposition_schlafmodus_fenster_offen": "sleep_window_pos",
    "zielposition_fenster_offen": "window_pos",
    "zielposition_beschattung": "sun_pos",
    "lux_threshold": "lux_threshold",
    "lux_hysteresis": "lux_hyst",
    "kalte_threshold": "cold_threshold",
    "automatik_totzone": "deadband",
}
