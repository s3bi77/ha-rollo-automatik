"""Tests der Entscheidungslogik (ohne Home Assistant)."""

from __future__ import annotations

import pytest

from custom_components.rollo_automatik.logic import (
    PRESENCE_SUPPRESS_SECONDS,
    REASON_COLD,
    REASON_PRESENCE,
    REASON_SOLAR_GAIN,
    CoverConfig,
    Inputs,
    RoomState,
    Settings,
    cascade_positions,
    evaluate,
    is_sun_direct,
)

COVER = "cover.kind_1_fenster"
SOUTH_EAST = CoverConfig(COVER, "binary_sensor.kind_1_fenster", orientation=135)


def make_inputs(**overrides) -> Inputs:
    values = dict(
        illuminance=500.0,
        temperature=15.0,
        hvac="heat",
        dusk=False,
        room_presence=False,
        house_presence=True,
        sleep=False,
        sun_azimuth=150.0,
        sun_elevation=30.0,
        window_open={COVER: False},
        cover_position={COVER: 50.0},
    )
    values.update(overrides)
    return Inputs(**values)


def run(inputs, settings=None, state=None, covers=None, now=1000.0):
    state = state or RoomState()
    settings = settings or Settings(sleep_position=0, sleep_window_position=20)
    return evaluate(covers or [SOUTH_EAST], settings, inputs, state, now), state


def test_dusk_closes():
    result, _ = run(make_inputs(dusk=True, cover_position={COVER: 100.0}))
    assert result.covers[0].target == 0
    assert result.covers[0].move


def test_presence_opens():
    result, state = run(make_inputs(room_presence=True))
    assert result.covers[0].target == 100
    assert result.covers[0].reason == REASON_PRESENCE
    assert state.presence


def test_presence_stays_until_house_empty():
    state = RoomState()
    run(make_inputs(room_presence=True), state=state)
    result, _ = run(make_inputs(room_presence=False), state=state)
    assert result.presence
    result, _ = run(make_inputs(room_presence=False, house_presence=False), state=state)
    assert not result.presence


def test_no_move_without_rule_change():
    state = RoomState()
    first, _ = run(make_inputs(dusk=True, cover_position={COVER: 100.0}), state=state)
    assert first.covers[0].move
    # Von Hand auf 60 gefahren, gleiche Regeln: nichts tun
    second, _ = run(make_inputs(dusk=True, cover_position={COVER: 60.0}), state=state)
    assert not second.covers[0].move
    assert second.covers[0].skip_reason == "keine Änderung"


def test_deadband():
    result, _ = run(make_inputs(dusk=True, cover_position={COVER: 3.0}))
    assert not result.covers[0].move
    assert result.covers[0].skip_reason == "innerhalb der Totzone"


def test_absence_heating_with_sun_opens_and_suppresses_presence():
    settings = Settings(illuminance_threshold=1000)
    result, state = run(make_inputs(illuminance=2000.0, hvac="heat"), settings=settings, now=1000.0)
    assert result.covers[0].target == 100
    assert result.covers[0].reason == REASON_SOLAR_GAIN
    assert state.suppress_presence_until == 1000.0 + PRESENCE_SUPPRESS_SECONDS
    result, _ = run(make_inputs(illuminance=2000.0, room_presence=True), settings=settings, state=state, now=1100.0)
    assert not result.presence


def test_cold_closes_during_absence():
    result, state = run(make_inputs(temperature=2.0, hvac="off", cover_position={COVER: 100.0}))
    assert state.cold
    assert result.covers[0].target == 0
    assert [c[0] for c in result.covers[0].constraints] == [REASON_PRESENCE, REASON_COLD]


def test_cold_hysteresis():
    state = RoomState()
    run(make_inputs(temperature=4.0), state=state)
    assert state.cold
    run(make_inputs(temperature=5.5), state=state)
    assert state.cold
    run(make_inputs(temperature=6.5), state=state)
    assert not state.cold


def test_missing_temperature_keeps_state():
    state = RoomState(cold=True)
    run(make_inputs(temperature=None), state=state)
    assert state.cold


def test_illuminance_hysteresis():
    settings = Settings(illuminance_threshold=1500, illuminance_hysteresis=200)
    state = RoomState()
    run(make_inputs(illuminance=1600.0), settings=settings, state=state)
    assert state.bright
    run(make_inputs(illuminance=1400.0), settings=settings, state=state)
    assert state.bright
    run(make_inputs(illuminance=1250.0), settings=settings, state=state)
    assert not state.bright


def test_shading_respects_conditions():
    settings = Settings(shading=True, shading_position=30, illuminance_threshold=1000)
    result, _ = run(make_inputs(illuminance=2000.0, room_presence=True, shading_allowed={COVER: True}), settings=settings)
    assert result.covers[0].target == 30
    result, _ = run(make_inputs(illuminance=2000.0, room_presence=True, shading_allowed={COVER: False}), settings=settings)
    assert result.covers[0].target == 100


def test_cover_shading_position():
    cover = CoverConfig(COVER, orientation=135, shading_position=20)
    settings = Settings(shading=True, shading_position=75, illuminance_threshold=1000)
    result, _ = run(make_inputs(illuminance=2000.0, room_presence=True), settings=settings, covers=[cover])
    assert result.covers[0].target == 20


def test_window_open_raises_target():
    result, _ = run(make_inputs(dusk=True, window_open={COVER: True}, cover_position={COVER: 0.0}))
    assert result.covers[0].target == 100


def test_sleep_mode():
    result, _ = run(make_inputs(room_presence=True, sleep=True))
    assert result.covers[0].target == 0
    result, _ = run(make_inputs(room_presence=True, sleep=True, window_open={COVER: True}))
    assert result.covers[0].target == 20


def test_without_sleep_settings_sleep_is_ignored():
    result, _ = run(make_inputs(room_presence=True, sleep=True), settings=Settings())
    assert result.covers[0].target == 100


@pytest.mark.parametrize(
    ("azimuth", "elevation", "orientation", "expected"),
    [
        (150, 30, 135, True),
        (60, 30, 135, False),
        (220, 30, 225, True),
        (10, 30, 315, True),  # über 0° hinweg
        (150, 5, 135, False),
        (150, 85, 135, False),
        (None, 30, 135, False),
    ],
)
def test_sun_direct(azimuth, elevation, orientation, expected):
    assert is_sun_direct(azimuth, elevation, orientation) is expected


def test_cascade_positions():
    assert cascade_positions("sleep_position", 30, 20, 100) == {"sleep_window_position": 30, "window_position": 100}
    assert cascade_positions("sleep_window_position", 30, 20, 100) == {"sleep_position": 20}
    assert cascade_positions("sleep_window_position", 0, 80, 50) == {"window_position": 80}
    assert cascade_positions("window_position", 0, 20, 10) == {"sleep_window_position": 10, "sleep_position": 0}
    assert cascade_positions("window_position", 0, 20, 100) == {}
