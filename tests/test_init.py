"""Tests der Integration in Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, label_registry as lr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.rollo_automatik.const import DOMAIN

ROOM = {
    "room_name": "Kind 1",
    "prefix": "kind_1",
    "sleep_mode": True,
    "rollos": [{"suffix": "fenster", "direction": 0}],
    "import_nodered": True,
}


async def _setup(hass: HomeAssistant, data: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=data or ROOM, unique_id="kind_1", title="Kind 1")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_keep_nodered_ids(hass: HomeAssistant) -> None:
    await _setup(hass)
    for entity_id in (
        "number.kind_1_rollo_zielposition_schlafmodus",
        "number.kind_1_rollo_zielposition_schlafmodus_fenster_offen",
        "number.kind_1_rollo_zielposition_fenster_offen",
        "number.kind_1_rollo_zielposition_beschattung",
        "number.kind_1_rollo_lux_threshold",
        "number.kind_1_rollo_lux_hysteresis",
        "number.kind_1_rollo_kalte_threshold",
        "number.kind_1_rollo_automatik_totzone",
        "switch.kind_1_rollo_automatik_aktiv",
        "switch.kind_1_rollo_automatische_beschattung",
        "sensor.kind_1_rollo_automatik_status",
    ):
        assert hass.states.get(entity_id) is not None, entity_id


async def test_room_without_sleep_mode(hass: HomeAssistant) -> None:
    await _setup(hass, {**ROOM, "sleep_mode": False})
    assert hass.states.get("number.kind_1_rollo_zielposition_schlafmodus") is None
    assert hass.states.get("number.kind_1_rollo_zielposition_fenster_offen") is not None


async def test_takes_over_nodered_entity(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "number", "nodered", "nodered-abc", suggested_object_id="kind_1_rollo_lux_threshold"
    )
    hass.states.async_set("number.kind_1_rollo_lux_threshold", "1600")
    data = {**ROOM, "initial_values": {"number.kind_1_rollo_lux_threshold": "1600"}}
    await _setup(hass, data)

    reg_entry = registry.async_get("number.kind_1_rollo_lux_threshold")
    assert reg_entry is not None
    assert reg_entry.platform == DOMAIN
    assert hass.states.get("number.kind_1_rollo_lux_threshold").state == "1600.0"


async def test_dusk_closes_cover(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.kind_1_rollo_fenster", "open", {"current_position": 100})
    hass.states.async_set("binary_sensor.dammerung", "off")
    await _setup(hass)

    hass.states.async_set("binary_sensor.dammerung", "on")
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data == {"entity_id": "cover.kind_1_rollo_fenster", "position": 0}
    status = hass.states.get("sensor.kind_1_rollo_automatik_status")
    assert status.state == "fenster: 0 (dusk)"


async def test_automation_switch_off_blocks(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.kind_1_rollo_fenster", "open", {"current_position": 100})
    hass.states.async_set("binary_sensor.dammerung", "off")
    await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.kind_1_rollo_automatik_aktiv"}, blocking=True
    )

    hass.states.async_set("binary_sensor.dammerung", "on")
    await hass.async_block_till_done()
    assert calls == []
    assert hass.states.get("sensor.kind_1_rollo_automatik_status").state == "Automatik aus"


async def test_house_presence_from_label(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "cover", "set_cover_position")
    label = lr.async_get(hass).async_create("Präsenz")
    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "binary_sensor", "test", "p1", suggested_object_id="kind_1_prasenz"
    )
    registry.async_update_entity(sensor.entity_id, labels={label.label_id})
    hass.states.async_set("cover.kind_1_rollo_fenster", "closed", {"current_position": 0})
    hass.states.async_set("binary_sensor.kind_1_prasenz", "off")
    await _setup(hass)

    hass.states.async_set("binary_sensor.kind_1_prasenz", "on")
    await hass.async_block_till_done()
    assert calls[-1].data == {"entity_id": "cover.kind_1_rollo_fenster", "position": 100}


async def test_cascade_numbers(hass: HomeAssistant) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.kind_1_rollo_zielposition_schlafmodus", "value": 40},
        blocking=True,
    )
    assert hass.states.get("number.kind_1_rollo_zielposition_schlafmodus_fenster_offen").state == "40.0"


async def test_config_flow_captures_values(hass: HomeAssistant) -> None:
    hass.states.async_set("number.kind_1_rollo_lux_threshold", "1600")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "room_name": "Kind 1",
            "prefix": "",
            "sleep_mode": True,
            "rollos": [{"suffix": "fenster", "direction": 0, "sunRule": {"entity": "select.x", "eq": "Kühlen"}}],
            "import_nodered": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["prefix"] == "kind_1"
    assert result["data"]["initial_values"] == {"number.kind_1_rollo_lux_threshold": "1600"}


async def test_config_flow_rejects_bad_rule(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "room_name": "Kind 1",
            "sleep_mode": True,
            "rollos": [{"suffix": "fenster", "sunRule": {"entity": "select.x"}}],
            "import_nodered": False,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "rollo_sun_rule"}
