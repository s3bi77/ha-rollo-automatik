"""Tests der Integration in Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.rollo_automatik.const import DOMAIN

COVER = "cover.arbeitszimmer_fenster"


@pytest.fixture
def area(hass: HomeAssistant) -> str:
    """Bereich mit Rollo, Fenster, Präsenz und Schlafmodus."""
    area = ar.async_get(hass).async_create("Arbeitszimmer")
    registry = er.async_get(hass)
    for domain, object_id, device_class in (
        ("cover", "arbeitszimmer_fenster", None),
        ("binary_sensor", "arbeitszimmer_fenster_offen", "window"),
        ("binary_sensor", "arbeitszimmer_anwesenheit", "presence"),
        ("switch", "arbeitszimmer_schlafen", None),
        ("climate", "arbeitszimmer", None),
    ):
        entry = registry.async_get_or_create(
            domain, "test", object_id, suggested_object_id=object_id, original_device_class=device_class
        )
        registry.async_update_entity(entry.entity_id, area_id=area.id)
    return area.id


def room_data(area_id: str, **overrides) -> dict:
    data = {
        "area": area_id,
        "presence_entity": "binary_sensor.arbeitszimmer_anwesenheit",
        "sleep_entity": "switch.arbeitszimmer_schlafen",
        "climate_entity": "climate.arbeitszimmer",
        "covers": [
            {
                "entity_id": COVER,
                "window_entity": "binary_sensor.arbeitszimmer_fenster_offen",
                "orientation": "se",
                "shading_position": None,
                "shading_conditions": [],
            }
        ],
        "illuminance_entity": None,
        "temperature_entity": None,
        "dusk_entity": "binary_sensor.dammerung",
        "house_presence_entity": None,
    }
    data.update(overrides)
    return data


async def _setup(hass: HomeAssistant, data: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id=data["area"], title="Arbeitszimmer", version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entities(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    registry = er.async_get(hass)
    return {e.translation_key: e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}


async def test_creates_room_device(hass: HomeAssistant, area: str) -> None:
    entry = await _setup(hass, room_data(area))
    keys = _entities(hass, entry)
    assert set(keys) == {
        "sleep_position",
        "sleep_window_position",
        "window_position",
        "shading_position",
        "illuminance_threshold",
        "illuminance_hysteresis",
        "cold_threshold",
        "deadband",
        "automation",
        "shading",
        "status",
    }
    registry = er.async_get(hass)
    device_id = registry.async_get(keys["automation"]).device_id
    from homeassistant.helpers import device_registry as dr

    assert dr.async_get(hass).async_get(device_id).area_id == area


async def test_room_without_sleep(hass: HomeAssistant, area: str) -> None:
    entry = await _setup(hass, room_data(area, sleep_entity=None))
    assert "sleep_position" not in _entities(hass, entry)


async def test_dusk_closes_cover(hass: HomeAssistant, area: str) -> None:
    calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set(COVER, "open", {"current_position": 100, "friendly_name": "Fenster"})
    hass.states.async_set("binary_sensor.dammerung", "off")
    entry = await _setup(hass, room_data(area))

    hass.states.async_set("binary_sensor.dammerung", "on")
    await hass.async_block_till_done()

    assert calls[-1].data == {"entity_id": COVER, "position": 0}
    status = hass.states.get(_entities(hass, entry)["status"])
    assert status.state == "Fenster: 0 % (Dämmerung)"


async def test_automation_switch_off_blocks(hass: HomeAssistant, area: str) -> None:
    calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set(COVER, "open", {"current_position": 100})
    hass.states.async_set("binary_sensor.dammerung", "off")
    entry = await _setup(hass, room_data(area))
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": _entities(hass, entry)["automation"]}, blocking=True
    )

    hass.states.async_set("binary_sensor.dammerung", "on")
    await hass.async_block_till_done()
    assert calls == []


async def test_house_presence_sensor(hass: HomeAssistant, area: str) -> None:
    calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set(COVER, "closed", {"current_position": 0})
    hass.states.async_set("binary_sensor.haus_anwesend", "on")
    hass.states.async_set("binary_sensor.arbeitszimmer_anwesenheit", "off")
    await _setup(hass, room_data(area, house_presence_entity="binary_sensor.haus_anwesend"))

    hass.states.async_set("binary_sensor.arbeitszimmer_anwesenheit", "on")
    await hass.async_block_till_done()
    assert calls[-1].data == {"entity_id": COVER, "position": 100}


async def test_shading_conditions(hass: HomeAssistant, area: str) -> None:
    calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set(COVER, "open", {"current_position": 100})
    hass.states.async_set("sensor.hell", "5000")
    hass.states.async_set("input_boolean.kuehlen", "off")
    hass.states.async_set("sun.sun", "above_horizon", {"azimuth": 140, "elevation": 30})
    covers = room_data(area)["covers"]
    covers[0]["shading_conditions"] = [
        {"condition": "state", "entity_id": "input_boolean.kuehlen", "state": "on"}
    ]
    entry = await _setup(hass, room_data(area, covers=covers, illuminance_entity="sensor.hell"))
    keys = _entities(hass, entry)
    await hass.services.async_call("switch", "turn_on", {"entity_id": keys["shading"]}, blocking=True)
    await hass.async_block_till_done()
    assert not [c for c in calls if c.data["position"] != 100]

    hass.states.async_set("input_boolean.kuehlen", "on")
    await hass.async_block_till_done()
    assert calls[-1].data == {"entity_id": COVER, "position": 50}


async def test_cascade_numbers(hass: HomeAssistant, area: str) -> None:
    entry = await _setup(hass, room_data(area))
    keys = _entities(hass, entry)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": keys["sleep_position"], "value": 40}, blocking=True
    )
    assert hass.states.get(keys["sleep_window_position"]).state == "40.0"


async def test_config_flow(hass: HomeAssistant, area: str) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"area": area})
    assert result["step_id"] == "room"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "covers_section": {"covers": [COVER]},
            "sensors_section": {"presence_entity": "binary_sensor.arbeitszimmer_anwesenheit"},
        },
    )
    assert result["step_id"] == "cover"
    assert result["description_placeholders"]["index"] == "1"
    assert result["description_placeholders"]["total"] == "1"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "window_section": {"window_entity": "binary_sensor.arbeitszimmer_fenster_offen"},
            "sun_section": {
                "orientation": "sw",
                "shading_conditions": [{"condition": "state", "entity_id": "input_boolean.x", "state": "on"}],
            },
        },
    )
    assert result["step_id"] == "outdoor"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"outdoor_section": {"dusk_entity": "binary_sensor.dammerung"}, "house_section": {}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Arbeitszimmer"
    assert result["data"]["dusk_entity"] == "binary_sensor.dammerung"
    assert result["data"]["covers"][0]["orientation"] == "sw"
    assert result["data"]["sleep_entity"] is None


async def test_config_flow_rejects_bad_conditions(hass: HomeAssistant, area: str) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"area": area})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"covers_section": {"covers": [COVER]}, "sensors_section": {}}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "window_section": {},
            "sun_section": {"orientation": "s", "shading_conditions": [{"condition": "quatsch"}]},
        },
    )
    assert result["step_id"] == "cover"
    assert result["errors"] == {"base": "invalid_conditions"}


async def test_options_flow_keeps_cover_settings(hass: HomeAssistant, area: str) -> None:
    entry = await _setup(hass, room_data(area))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "room"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "covers_section": {"covers": [COVER]},
            "sensors_section": {"sleep_entity": "switch.arbeitszimmer_schlafen"},
        },
    )
    assert result["step_id"] == "cover"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "window_section": {"window_entity": "binary_sensor.arbeitszimmer_fenster_offen"},
            "sun_section": {"orientation": "w"},
        },
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"outdoor_section": {"dusk_entity": "binary_sensor.dammerung"}, "house_section": {}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["covers"][0]["orientation"] == "w"
    assert entry.options["dusk_entity"] == "binary_sensor.dammerung"


async def test_fixes_doubled_area_in_entity_ids(hass: HomeAssistant, area: str) -> None:
    data = room_data(area)
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id=area, title="Arbeitszimmer", version=2)
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        f"{entry.entry_id}_automation",
        config_entry=entry,
        suggested_object_id="arbeitszimmer_arbeitszimmer_rollos_automatik",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.arbeitszimmer_rollos_automatik") is not None
    assert hass.states.get("switch.arbeitszimmer_arbeitszimmer_rollos_automatik") is None
