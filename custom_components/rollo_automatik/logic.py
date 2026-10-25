"""Entscheidungslogik der Rollo-Automatik.

Reiner Python-Code ohne Home-Assistant-Abhängigkeiten, damit er sich direkt
testen lässt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Nach einer Fahrt bei Abwesenheit wird die Präsenz kurz ignoriert, damit der
# fahrende Rollo den Präsenzmelder nicht selbst auslöst.
PRESENCE_SUPPRESS_SECONDS = 240

# Temperatur-Hysterese für "kalt": aus erst bei Schwelle + 1 °C.
COLD_HYSTERESIS = 1.0

# Die Sonne scheint direkt auf ein Fenster, wenn ihr Azimut höchstens so weit
# von der Ausrichtung des Fensters abweicht und sie zwischen 10° und 80° hoch steht.
SUN_HALF_ANGLE = 65
SUN_MIN_ELEVATION = 10
SUN_MAX_ELEVATION = 80

REASON_DUSK = "Dämmerung"
REASON_PRESENCE = "Anwesenheit"
REASON_SOLAR_GAIN = "Sonnenwärme"
REASON_COLD = "Kälte"
REASON_HEAT = "Hitzeschutz"
REASON_SHADING = "Beschattung"
REASON_WINDOW = "Fenster offen"
REASON_SLEEP = "Schlafmodus"
REASON_SLEEP_WINDOW = "Schlafmodus + Fenster offen"


@dataclass
class CoverConfig:
    """Konfiguration eines einzelnen Rollos."""

    cover_entity: str
    window_entity: str | None = None
    # Azimut, in den das Fenster zeigt (180 = Süden)
    orientation: float = 180
    # Beschattungsposition für dieses Rollo statt der Raum-Einstellung
    shading_position: float | None = None


@dataclass
class Settings:
    """Einstellungen des Raums (die Zahlen und Schalter am Gerät)."""

    window_position: float = 100
    shading_position: float = 50
    shading: bool = False
    illuminance_threshold: float = 1500
    illuminance_hysteresis: float = 100
    cold_threshold: float = 5
    deadband: float = 5
    sleep_position: float | None = None
    sleep_window_position: float | None = None


@dataclass
class Inputs:
    """Aktuelle Messwerte und Zustände."""

    illuminance: float | None
    temperature: float | None
    hvac: str
    dusk: bool
    room_presence: bool
    house_presence: bool
    sleep: bool
    sun_azimuth: float | None
    sun_elevation: float | None
    window_open: dict[str, bool] = field(default_factory=dict)
    cover_position: dict[str, float | None] = field(default_factory=dict)
    # Ergebnis der Beschattungsbedingungen je Rollo (fehlt = erlaubt)
    shading_allowed: dict[str, bool] = field(default_factory=dict)


@dataclass
class RoomState:
    """Gedächtnis zwischen zwei Auswertungen."""

    presence: bool = False
    bright: bool = False
    cold: bool = False
    suppress_presence_until: float = 0.0
    last_constraints: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


@dataclass
class CoverResult:
    """Ergebnis für ein Rollo."""

    cover_entity: str
    target: float | None
    constraints: list[tuple[str, float]]
    sun_direct: bool
    move: bool
    skip_reason: str | None = None

    @property
    def reason(self) -> str | None:
        return self.constraints[-1][0] if self.constraints else None


@dataclass
class Result:
    """Ergebnis einer Auswertung für den ganzen Raum."""

    covers: list[CoverResult]
    presence: bool
    bright: bool
    cold: bool

    @property
    def moves(self) -> list[CoverResult]:
        return [c for c in self.covers if c.move]


def is_sun_direct(azimuth: float | None, elevation: float | None, orientation: float) -> bool:
    """Scheint die Sonne direkt auf ein Fenster mit dieser Ausrichtung?"""
    if azimuth is None or elevation is None:
        return False
    deviation = abs((azimuth - orientation + 180) % 360 - 180)
    return deviation < SUN_HALF_ANGLE and SUN_MIN_ELEVATION < elevation < SUN_MAX_ELEVATION


def evaluate(
    covers: list[CoverConfig],
    settings: Settings,
    inputs: Inputs,
    state: RoomState,
    now: float,
) -> Result:
    """Berechnet die Zielpositionen und aktualisiert das Gedächtnis.

    Die Regeln werden der Reihe nach angewendet. "Höchstens" begrenzt die
    Position nach oben, "mindestens" nach unten; die letzte greifende Regel
    gewinnt.
    """

    # Anwesenheit bleibt nach einmaliger Erkennung gesetzt, bis das Haus leer
    # ist. Kurz nach einer Fahrt bei Abwesenheit wird sie ignoriert.
    if not inputs.house_presence or now < state.suppress_presence_until:
        state.presence = False
    elif inputs.room_presence:
        state.presence = True
    presence = state.presence

    illuminance = inputs.illuminance or 0
    if not state.bright and illuminance > settings.illuminance_threshold:
        state.bright = True
    if state.bright and illuminance < settings.illuminance_threshold - settings.illuminance_hysteresis:
        state.bright = False

    if inputs.temperature is not None:
        if not state.cold and inputs.temperature < settings.cold_threshold:
            state.cold = True
        if state.cold and inputs.temperature > settings.cold_threshold + COLD_HYSTERESIS:
            state.cold = False

    hvac = (inputs.hvac or "").lower()
    changed_during_absence = False
    results: list[CoverResult] = []

    for cover in covers:
        key = cover.cover_entity
        window_open = inputs.window_open.get(key, False)
        position = inputs.cover_position.get(key)
        sun_direct = is_sun_direct(inputs.sun_azimuth, inputs.sun_elevation, cover.orientation)

        target: float | None = None
        constraints: list[tuple[str, float]] = []

        def at_most(value: float, reason: str) -> bool:
            nonlocal target
            if target is None or target > value:
                target = value
                constraints.append((reason, value))
                return True
            return False

        def at_least(value: float, reason: str) -> bool:
            nonlocal target
            if target is None or target < value:
                target = value
                constraints.append((reason, value))
                return True
            return False

        if inputs.dusk:
            at_most(0, REASON_DUSK)
        else:
            if presence or position == 100:
                at_least(100, REASON_PRESENCE)
            if not presence:
                if hvac == "heat" and state.bright and sun_direct:
                    changed_during_absence = at_least(100, REASON_SOLAR_GAIN) or changed_during_absence
                elif state.cold:
                    changed_during_absence = at_most(0, REASON_COLD) or changed_during_absence
                elif hvac == "cool" and state.bright:
                    changed_during_absence = at_most(0, REASON_HEAT) or changed_during_absence

        if settings.shading and state.bright and sun_direct and inputs.shading_allowed.get(key, True):
            at_most(
                cover.shading_position
                if cover.shading_position is not None
                else settings.shading_position,
                REASON_SHADING,
            )

        if window_open:
            at_least(settings.window_position, REASON_WINDOW)

        if inputs.sleep and settings.sleep_position is not None:
            at_least(settings.sleep_position, REASON_SLEEP)
            at_most(settings.sleep_position, REASON_SLEEP)
            if window_open and settings.sleep_window_position is not None:
                at_least(settings.sleep_window_position, REASON_SLEEP_WINDOW)

        # Nur fahren, wenn sich die greifenden Regeln geändert haben. So bleibt
        # ein von Hand verstelltes Rollo in Ruhe.
        move = False
        skip: str | None = None
        if state.last_constraints.get(key) == constraints:
            skip = "keine Änderung"
        else:
            state.last_constraints[key] = list(constraints)
            if target is None:
                skip = "kein Ziel"
            elif abs((position or 0) - target) < settings.deadband:
                skip = "innerhalb der Totzone"
            else:
                move = True

        results.append(
            CoverResult(
                cover_entity=key,
                target=target,
                constraints=constraints,
                sun_direct=sun_direct,
                move=move,
                skip_reason=skip,
            )
        )

    if changed_during_absence and any(r.move for r in results):
        state.suppress_presence_until = now + PRESENCE_SUPPRESS_SECONDS

    return Result(covers=results, presence=presence, bright=state.bright, cold=state.cold)


def cascade_positions(
    changed: str,
    sleep_position: float,
    sleep_window_position: float,
    window_position: float,
) -> dict[str, float]:
    """Hält Schlafposition <= Schlafposition mit Fenster <= Fensterposition ein.

    `changed` ist der Schlüssel des geänderten Werts. Gibt die anzupassenden
    anderen Werte zurück.
    """
    updates: dict[str, float] = {}
    if changed == "sleep_position" and sleep_position > sleep_window_position:
        updates["sleep_window_position"] = sleep_position
        updates["window_position"] = max(window_position, sleep_position)
    elif changed == "sleep_window_position" and sleep_window_position < sleep_position:
        updates["sleep_position"] = sleep_window_position
    elif changed == "sleep_window_position" and sleep_window_position > window_position:
        updates["window_position"] = sleep_window_position
    elif changed == "window_position" and window_position < sleep_window_position:
        updates["sleep_window_position"] = window_position
        updates["sleep_position"] = min(sleep_position, window_position)
    return updates
