"""Tests der Entscheidungslogik (ohne Home Assistant)."""

from __future__ import annotations

import pytest

from custom_components.rollo_automatik.logic import (
    PRESENCE_SUPPRESS_SECONDS,
    Inputs,
    RolloConfig,
    RoomState,
    Settings,
    cascade_positions,
    evaluate,
    evaluate_rule,
    is_sun_direct,
    validate_rule,
)

ROLLO = RolloConfig("fenster", "cover.kind_1_rollo_fenster", "binary_sensor.kind_1_fenster_geoffnet")


def make_inputs(**overrides) -> Inputs:
    values = dict(
        lux=500.0,
        temp=15.0,
        hvac="heat",
        dusk=False,
        raw_presence=False,
        house_presence=True,
        sleep=False,
        azimuth=150.0,
        elevation=30.0,
        window_open={"fenster": False},
        cover_pos={"fenster": 50.0},
        get_state=lambda _: None,
    )
    values.update(overrides)
    return Inputs(**values)


def run(inputs: Inputs, settings: Settings | None = None, state: RoomState | None = None, rollos=None, now=1000.0):
    state = state or RoomState()
    result = evaluate(rollos or [ROLLO], settings or Settings(sleep_pos=0, sleep_window_pos=20), inputs, state, now)
    return result, state


def test_dusk_closes():
    result, _ = run(make_inputs(dusk=True, cover_pos={"fenster": 100.0}))
    assert result.rollos[0].target == 0
    assert result.rollos[0].move


def test_presence_opens():
    result, state = run(make_inputs(raw_presence=True))
    assert result.rollos[0].target == 100
    assert state.presence


def test_presence_latches_until_house_empty():
    state = RoomState()
    run(make_inputs(raw_presence=True), state=state)
    result, _ = run(make_inputs(raw_presence=False), state=state)
    assert result.presence
    result, _ = run(make_inputs(raw_presence=False, house_presence=False), state=state)
    assert not result.presence


def test_no_move_without_constraint_change():
    state = RoomState()
    first, _ = run(make_inputs(dusk=True, cover_pos={"fenster": 100.0}), state=state)
    assert first.rollos[0].move
    # Jemand fährt das Rollo von Hand auf 60 – gleiche Bedingungen, also nichts tun
    second, _ = run(make_inputs(dusk=True, cover_pos={"fenster": 60.0}), state=state)
    assert not second.rollos[0].move
    assert second.rollos[0].skip_reason == "keine Änderung der Bedingungen"


def test_deadband():
    result, _ = run(make_inputs(dusk=True, cover_pos={"fenster": 3.0}))
    assert not result.rollos[0].move
    assert result.rollos[0].skip_reason == "innerhalb der Totzone"


def test_absence_heat_with_sun_opens_and_suppresses_presence():
    settings = Settings(lux_threshold=1000, sleep_pos=0, sleep_window_pos=20)
    result, state = run(make_inputs(lux=2000.0, hvac="heat"), settings=settings, now=1000.0)
    assert result.rollos[0].target == 100
    assert result.rollos[0].constraints[-1][0] == "heat_lux"
    assert state.suppress_presence_until == 1000.0 + PRESENCE_SUPPRESS_SECONDS
    # Während der Sperre zählt die Präsenz nicht
    result, _ = run(make_inputs(lux=2000.0, raw_presence=True), settings=settings, state=state, now=1100.0)
    assert not result.presence


def test_cold_closes_during_absence():
    result, state = run(make_inputs(temp=2.0, hvac="off", cover_pos={"fenster": 100.0}))
    assert state.temp_below
    # cover_pos 100 hält das Rollo offen (nodusk), "cold" begrenzt es dann auf 0
    assert result.rollos[0].target == 0
    assert [c[0] for c in result.rollos[0].constraints] == ["nodusk", "cold"]


def test_cold_hysteresis():
    state = RoomState()
    run(make_inputs(temp=4.0), state=state)
    assert state.temp_below
    run(make_inputs(temp=5.5), state=state)
    assert state.temp_below
    run(make_inputs(temp=6.5), state=state)
    assert not state.temp_below


def test_missing_temperature_keeps_state():
    state = RoomState(temp_below=True)
    run(make_inputs(temp=None), state=state)
    assert state.temp_below


def test_lux_hysteresis():
    settings = Settings(lux_threshold=1500, lux_hyst=200, sleep_pos=0, sleep_window_pos=20)
    state = RoomState()
    run(make_inputs(lux=1600.0), settings=settings, state=state)
    assert state.lux_above
    run(make_inputs(lux=1400.0), settings=settings, state=state)
    assert state.lux_above
    run(make_inputs(lux=1250.0), settings=settings, state=state)
    assert not state.lux_above


def test_sunshade_with_rule():
    rollo = RolloConfig(
        "fenster", "cover.x", "binary_sensor.x",
        sun_rule={"entity": "select.heizung_betriebsmodus", "eq": "Kühlen"},
    )
    settings = Settings(sun_active=True, sun_pos=30, lux_threshold=1000, sleep_pos=0, sleep_window_pos=20)
    states = {"select.heizung_betriebsmodus": "Kühlen"}
    result, _ = run(
        make_inputs(lux=2000.0, raw_presence=True, get_state=states.get),
        settings=settings, rollos=[rollo],
    )
    assert result.rollos[0].target == 30
    states["select.heizung_betriebsmodus"] = "Winter"
    result, _ = run(
        make_inputs(lux=2000.0, raw_presence=True, get_state=states.get),
        settings=settings, rollos=[rollo],
    )
    assert result.rollos[0].target == 100


def test_override_sun_pos():
    rollo = RolloConfig("kuchenfenster", "cover.x", "binary_sensor.x", direction=0, override_sun_pos=30)
    settings = Settings(sun_active=True, sun_pos=75, lux_threshold=1000)
    result, _ = run(
        make_inputs(lux=2000.0, raw_presence=True, window_open={}, cover_pos={}),
        settings=settings, rollos=[rollo],
    )
    assert result.rollos[0].target == 30


def test_window_open_raises_target():
    result, _ = run(make_inputs(dusk=True, window_open={"fenster": True}, cover_pos={"fenster": 0.0}))
    assert result.rollos[0].target == 100


def test_sleep_mode_forces_position_and_window_lifts():
    settings = Settings(sleep_pos=0, sleep_window_pos=20)
    result, _ = run(make_inputs(raw_presence=True, sleep=True), settings=settings)
    assert result.rollos[0].target == 0
    result, _ = run(make_inputs(raw_presence=True, sleep=True, window_open={"fenster": True}), settings=settings)
    assert result.rollos[0].target == 20


def test_room_without_sleep_mode_ignores_sleep():
    result, _ = run(make_inputs(raw_presence=True, sleep=True), settings=Settings())
    assert result.rollos[0].target == 100


@pytest.mark.parametrize(
    ("azimuth", "elevation", "direction", "expected"),
    [
        (150, 30, 0, True),
        (70, 30, 0, False),
        (220, 30, 1, True),
        (150, 5, 0, False),
        (150, 85, 0, False),
        (None, 30, 0, False),
    ],
)
def test_sun_direct(azimuth, elevation, direction, expected):
    assert is_sun_direct(azimuth, elevation, direction) is expected


def test_rules():
    states = {"a": "on", "b": "closed"}.get
    assert evaluate_rule(None, states)
    assert evaluate_rule({"entity": "a", "eq": "on"}, states)
    assert evaluate_rule({"entity": "b", "ne": "open"}, states)
    assert evaluate_rule({"anyOf": [{"entity": "a", "eq": "off"}, {"entity": "b", "eq": "closed"}]}, states)
    assert not evaluate_rule({"allOf": [{"entity": "a", "eq": "off"}, {"entity": "b", "eq": "closed"}]}, states)
    assert not evaluate_rule("DEFAULT", states)


def test_validate_rule():
    validate_rule({"allOf": [{"anyOf": [{"entity": "a", "eq": "x"}]}, {"entity": "b", "ne": "y"}]})
    for bad in ("x", {"entity": "a"}, {"entity": "a", "eq": 1, "ne": 2}, {"allOf": []}, {"foo": 1}):
        with pytest.raises(ValueError):
            validate_rule(bad)


def test_cascade_positions():
    assert cascade_positions("sleep_pos", 30, 20, 100) == {"sleep_window_pos": 30, "window_pos": 100}
    assert cascade_positions("sleep_window_pos", 30, 20, 100) == {"sleep_pos": 20}
    assert cascade_positions("sleep_window_pos", 0, 80, 50) == {"window_pos": 80}
    assert cascade_positions("window_pos", 0, 20, 10) == {"sleep_window_pos": 10, "sleep_pos": 0}
    assert cascade_positions("window_pos", 0, 20, 100) == {}
