"""Entscheidungslogik der Rollo-Automatik.

Reiner Python-Code ohne Home-Assistant-Abhängigkeiten, damit er sich direkt
testen lässt. Portiert aus dem Node-RED-Subflow "Rollo Automatik"
(Function-Node "Decide Rollo Target").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Nach einer Fahrt bei Abwesenheit wird die Präsenz kurz ignoriert, damit der
# fahrende Rollo den Präsenzmelder nicht selbst auslöst.
PRESENCE_SUPPRESS_SECONDS = 240

# Temperatur-Hysterese für "kalt": aus erst bei Schwelle + 1 °C.
COLD_HYSTERESIS = 1.0


@dataclass
class RolloConfig:
    """Konfiguration eines einzelnen Rollos im Raum."""

    suffix: str
    cover_entity: str
    window_entity: str
    # 0 = Ost/Süd, 1 = Süd/West, 2 = West, 3 = Nord (verschiebt das Sonnenfenster um 90°)
    direction: int = 0
    # Regel, wann beschattet werden darf. None = immer.
    sun_rule: Any = None
    # Beschattungsposition für dieses Rollo statt der Raum-Einstellung.
    override_sun_pos: float | None = None


@dataclass
class Settings:
    """Einstellungen des Raums (die Zahlen und Schalter am Gerät)."""

    window_pos: float = 100
    sun_pos: float = 100
    sun_active: bool = False
    lux_threshold: float = 1500
    lux_hyst: float = 100
    cold_threshold: float = 5
    deadband: float = 5
    sleep_pos: float | None = None
    sleep_window_pos: float | None = None


@dataclass
class Inputs:
    """Aktuelle Messwerte und Zustände."""

    lux: float | None
    temp: float | None
    hvac: str
    dusk: bool
    raw_presence: bool
    house_presence: bool
    sleep: bool
    azimuth: float | None
    elevation: float | None
    window_open: dict[str, bool]
    cover_pos: dict[str, float | None]
    get_state: Callable[[str], str | None]


@dataclass
class RoomState:
    """Gedächtnis zwischen zwei Auswertungen."""

    presence: bool = False
    lux_above: bool = False
    temp_below: bool = False
    suppress_presence_until: float = 0.0
    last_constraints: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


@dataclass
class RolloResult:
    """Ergebnis für ein Rollo."""

    suffix: str
    cover_entity: str
    target: float | None
    reason: list[str]
    constraints: list[tuple[str, float]]
    move: bool
    skip_reason: str | None = None


@dataclass
class Result:
    """Ergebnis einer Auswertung für den ganzen Raum."""

    rollos: list[RolloResult]
    presence: bool
    lux_above: bool
    temp_below: bool
    sun_direct: dict[str, bool]

    @property
    def moves(self) -> list[RolloResult]:
        return [r for r in self.rollos if r.move]

    @property
    def summary(self) -> str:
        return "; ".join(
            f"{r.suffix}: {'–' if r.target is None else int(r.target)}"
            + (f" ({r.constraints[-1][0]})" if r.constraints else "")
            for r in self.rollos
        )


def is_sun_direct(azimuth: float | None, elevation: float | None, direction: int) -> bool:
    """Steht die Sonne im Fenster dieser Ausrichtung?"""
    if azimuth is None or elevation is None:
        return False
    offset = direction * 90
    return 80 + offset < azimuth < 210 + offset and 10 < elevation < 80


def evaluate_rule(rule: Any, get_state: Callable[[str], str | None]) -> bool:
    """Wertet eine Sonnenregel aus.

    Formate:
      {"entity": "select.x", "eq": "Kühlen"}
      {"entity": "cover.x", "ne": "closed"}
      {"allOf": [regel, ...]}
      {"anyOf": [regel, ...]}
    """
    if rule is None:
        return True
    if not isinstance(rule, dict):
        _LOGGER.error("Ungültige Sonnenregel: %s", rule)
        return False
    if "entity" in rule:
        ops = [k for k in rule if k != "entity"]
        if len(ops) != 1 or ops[0] not in ("eq", "ne"):
            _LOGGER.error("Regel braucht genau eines von 'eq' oder 'ne': %s", rule)
            return False
        state = get_state(rule["entity"])
        if ops[0] == "eq":
            return state == rule["eq"]
        return state != rule["ne"]
    if "allOf" in rule and "anyOf" in rule:
        _LOGGER.error("Nur eines von allOf oder anyOf erlaubt: %s", rule)
        return False
    for key, combine in (("allOf", all), ("anyOf", any)):
        if key in rule:
            subrules = rule[key]
            if not isinstance(subrules, list) or not subrules:
                _LOGGER.error("%s braucht eine nicht leere Liste: %s", key, rule)
                return False
            return combine(evaluate_rule(sub, get_state) for sub in subrules)
    _LOGGER.error("Unbekannte Sonnenregel: %s", rule)
    return False


def validate_rule(rule: Any) -> None:
    """Wirft ValueError, wenn die Regel nicht dem Format entspricht."""
    if rule is None:
        return
    if not isinstance(rule, dict):
        raise ValueError("Regel muss ein Objekt sein")
    if "entity" in rule:
        ops = [k for k in rule if k != "entity"]
        if len(ops) != 1 or ops[0] not in ("eq", "ne"):
            raise ValueError("Regel mit 'entity' braucht genau eines von 'eq' oder 'ne'")
        return
    keys = [k for k in ("allOf", "anyOf") if k in rule]
    if len(keys) != 1 or len(rule) != 1:
        raise ValueError("Regel braucht 'entity', 'allOf' oder 'anyOf'")
    subrules = rule[keys[0]]
    if not isinstance(subrules, list) or not subrules:
        raise ValueError(f"'{keys[0]}' braucht eine nicht leere Liste")
    for sub in subrules:
        validate_rule(sub)


def evaluate(
    rollos: list[RolloConfig],
    settings: Settings,
    inputs: Inputs,
    state: RoomState,
    now: float,
) -> Result:
    """Berechnet die Zielpositionen und aktualisiert das Gedächtnis."""

    # Präsenz: bleibt nach einmaliger Erkennung gesetzt, bis das Haus leer ist.
    # Kurz nach einer Fahrt bei Abwesenheit wird sie ignoriert.
    if not inputs.house_presence or now < state.suppress_presence_until:
        state.presence = False
    elif inputs.raw_presence:
        state.presence = True
    presence = state.presence

    # Helligkeit mit Hysterese
    lux = inputs.lux or 0
    if not state.lux_above and lux > settings.lux_threshold:
        state.lux_above = True
    if state.lux_above and lux < settings.lux_threshold - settings.lux_hyst:
        state.lux_above = False

    # Kälte mit Hysterese (ohne Messwert bleibt der letzte Zustand)
    if inputs.temp is not None:
        if not state.temp_below and inputs.temp < settings.cold_threshold:
            state.temp_below = True
        if state.temp_below and inputs.temp > settings.cold_threshold + COLD_HYSTERESIS:
            state.temp_below = False

    hvac = (inputs.hvac or "").lower()
    changed_during_absence = False
    results: list[RolloResult] = []
    sun_direct_map: dict[str, bool] = {}

    for rollo in rollos:
        window_open = inputs.window_open.get(rollo.suffix, False)
        cover_pos = inputs.cover_pos.get(rollo.suffix)
        sun_direct = is_sun_direct(inputs.azimuth, inputs.elevation, rollo.direction)
        sun_direct_map[rollo.suffix] = sun_direct

        target: float | None = None
        reason: list[str] = []
        constraints: list[tuple[str, float]] = []

        def set_max(value: float, label: str) -> bool:
            nonlocal target
            applied = target is None or target > value
            if applied:
                target = value
                constraints.append((label, value))
            reason.append(f"{label}: {target:g}")
            return applied

        def set_min(value: float, label: str) -> bool:
            nonlocal target
            applied = target is None or target < value
            if applied:
                target = value
                constraints.append((label, value))
            reason.append(f"{label}: {target:g}")
            return applied

        if inputs.dusk:
            set_max(0, "dusk")
        else:
            if presence or cover_pos == 100:
                set_min(100, "nodusk")
            if not presence:
                if hvac == "heat" and state.lux_above and sun_direct:
                    changed_during_absence = set_min(100, "heat_lux") or changed_during_absence
                elif state.temp_below:
                    changed_during_absence = set_max(0, "cold") or changed_during_absence
                elif hvac == "cool" and state.lux_above:
                    changed_during_absence = set_max(0, "cool_lux") or changed_during_absence

        if (
            settings.sun_active
            and state.lux_above
            and sun_direct
            and evaluate_rule(rollo.sun_rule, inputs.get_state)
        ):
            sun_pos = (
                rollo.override_sun_pos
                if rollo.override_sun_pos is not None
                else settings.sun_pos
            )
            set_max(sun_pos, "sunshade")

        if window_open:
            set_min(settings.window_pos, "window")

        if inputs.sleep and settings.sleep_pos is not None:
            set_min(settings.sleep_pos, "sleep")
            set_max(settings.sleep_pos, "sleep")
            if window_open and settings.sleep_window_pos is not None:
                set_min(settings.sleep_window_pos, "sleep+window")

        # Nur fahren, wenn sich die greifenden Bedingungen geändert haben.
        # So bleibt ein von Hand verstelltes Rollo in Ruhe.
        move = False
        skip: str | None = None
        if state.last_constraints.get(rollo.suffix) == constraints:
            skip = "keine Änderung der Bedingungen"
        else:
            state.last_constraints[rollo.suffix] = list(constraints)
            if target is None:
                skip = "kein Ziel"
            elif abs((cover_pos or 0) - target) < settings.deadband:
                skip = "innerhalb der Totzone"
            else:
                move = True

        results.append(
            RolloResult(
                suffix=rollo.suffix,
                cover_entity=rollo.cover_entity,
                target=target,
                reason=reason,
                constraints=constraints,
                move=move,
                skip_reason=skip,
            )
        )

    if changed_during_absence and any(r.move for r in results):
        state.suppress_presence_until = now + PRESENCE_SUPPRESS_SECONDS

    return Result(
        rollos=results,
        presence=presence,
        lux_above=state.lux_above,
        temp_below=state.temp_below,
        sun_direct=sun_direct_map,
    )


def cascade_positions(
    changed: str,
    sleep_pos: float,
    sleep_window_pos: float,
    window_pos: float,
) -> dict[str, float]:
    """Hält sleep_pos <= sleep_window_pos <= window_pos ein.

    `changed` ist der geänderte Wert ("sleep_pos", "sleep_window_pos" oder
    "window_pos"). Gibt die anzupassenden anderen Werte zurück.
    """
    updates: dict[str, float] = {}
    if changed == "sleep_pos" and sleep_pos > sleep_window_pos:
        updates["sleep_window_pos"] = sleep_pos
        updates["window_pos"] = max(window_pos, sleep_pos)
    elif changed == "sleep_window_pos" and sleep_window_pos < sleep_pos:
        updates["sleep_pos"] = sleep_window_pos
    elif changed == "sleep_window_pos" and sleep_window_pos > window_pos:
        updates["window_pos"] = sleep_window_pos
    elif changed == "window_pos" and window_pos < sleep_window_pos:
        updates["sleep_window_pos"] = window_pos
        updates["sleep_pos"] = min(sleep_pos, window_pos)
    return updates
