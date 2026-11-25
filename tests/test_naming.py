import json
from types import SimpleNamespace

import naming


def make_session(metadata, shift="", device_no="ZYW003", activity="Kitchen"):
    return SimpleNamespace(
        metadata=metadata,
        start=None,
        location=metadata.get("location", ""),
        capturer=metadata.get("capturer", ""),
        task=metadata.get("task", ""),
        device_no=device_no,
        activity=activity,
        shift=shift,
    )


def test_scan_json_detects_nested_objects_and_array_items(tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({
        "meta": {"location": "MM3107"},
        "recorders": [{"name": "Justin", "device": {"id": "ZYW003"}}],
    }), encoding="utf-8")

    fields = naming.scan_json_file(path)
    paths = {item["path"] for item in fields}
    assert "meta.location" in paths
    assert "recorders[0].name" in paths
    assert "recorders[0].device.id" in paths
    assert naming._read_path(json.loads(path.read_text()), "recorders[0].device.id") == "ZYW003"


def test_no_shift_omits_session_token_without_s0():
    metadata = {
        "start_time_unix": 1795651200,
        "location": "MM3107",
        "capturer": "JustinBenaiahJutanUPH",
        "task": "ZYW003 Kitchen",
    }
    session = make_session(metadata)
    cfg = {
        "shift_mode": "none",
        "shifts": [],
        "naming": {"template": naming.DEFAULT_TEMPLATE},
    }

    result = naming.build_folder_name(session, cfg)
    assert result.endswith("_ZYW003_Kitchen")
    assert "_S0_" not in result
    assert "__" not in result


def test_shift_based_name_uses_configured_shift_number():
    metadata = {
        "start_time_unix": 1795651200,
        "location": "MM3107",
        "capturer": "Justin",
        "task": "ZYW003 Kitchen",
    }
    session = make_session(metadata, shift="Afternoon")
    cfg = {
        "shift_mode": "enabled",
        "shifts": [["12:00", "16:00", "Afternoon", 2]],
        "naming": {"template": naming.DEFAULT_TEMPLATE},
    }

    assert "_ZYW003_S2_Kitchen" in naming.build_folder_name(session, cfg)


def test_custom_nested_field_mapping_and_template():
    metadata = {
        "meta": {"site": "MM3107", "operator": "Justin"},
        "record": {"activity": "Livingroom", "device": "ZYW015"},
    }
    session = make_session(metadata, device_no="", activity="")
    cfg = {
        "shift_mode": "none",
        "naming": {
            "template": "{PERSON_NAME}-{LOCATION_CODE}-{ACTIVITY}",
            "field_map": {
                "PERSON_NAME": "meta.operator",
                "LOCATION_CODE": "meta.site",
                "ACTIVITY": "record.activity",
            },
        },
    }

    assert naming.build_folder_name(session, cfg) == "Justin-MM3107-Livingroom"


def test_one_json_source_can_be_split_into_multiple_custom_variables():
    session = make_session({
        "task": "ZYW-003 - Kitchen - Cleaning - 02",
        "location": "MM3107",
    })
    cfg = {
        "shift_mode": "none",
        "naming": {
            "template": "{DEVICE_PART}_{ROOM}_{ACTIVITY_NAME}_{TASK_NO}",
            "variables": [
                {"name": "DEVICE_PART", "source": "json:task", "operations": [
                    {"op": "split", "delimiter": " - ", "index": 0},
                    {"op": "replace", "find": "-", "replace": ""},
                ]},
                {"name": "ROOM", "source": "json:task", "operations": [
                    {"op": "split", "delimiter": " - ", "index": 1},
                    {"op": "case", "mode": "title"},
                ]},
                {"name": "ACTIVITY_NAME", "source": "json:task", "operations": [
                    {"op": "split", "delimiter": " - ", "index": 2},
                    {"op": "case", "mode": "lower"},
                ]},
                {"name": "TASK_NO", "source": "json:task", "operations": [
                    {"op": "split", "delimiter": " - ", "index": 3},
                    {"op": "prefix", "text": "B"},
                ]},
            ],
        },
    }

    assert naming.build_folder_name(session, cfg) == "ZYW003_Kitchen_cleaning_B02"


def test_custom_variable_can_depend_on_another_custom_variable():
    session = make_session({"task": "Kitchen"})
    cfg = {"shift_mode": "none", "naming": {
        "template": "{ROOM}_{ROOM_LABEL}",
        "variables": [
            {"name": "ROOM", "source": "json:task", "operations": [{"op": "case", "mode": "lower"}]},
            {"name": "ROOM_LABEL", "source": "var:ROOM", "operations": [
                {"op": "prefix", "text": "Area "}, {"op": "case", "mode": "title"}]},
        ],
    }}
    assert naming.build_folder_name(session, cfg) == "kitchen_Area Kitchen"


def test_datetime_transform_converts_unix_or_iso_time_to_wita_and_wit():
    session = make_session({"captured_at": "2026-01-01T17:30:00Z"})
    cfg = {"shift_mode": "none", "naming": {
        "template": "{DATE_WITA}_{DATE_WIT}",
        "variables": [
            {"name": "DATE_WITA", "source": "json:captured_at", "operations": [
                {"op": "datetime", "source_timezone": "UTC", "timezone": "Asia/Makassar",
                 "format": "%Y%m%d_%H%M"}]},
            {"name": "DATE_WIT", "source": "json:captured_at", "operations": [
                {"op": "datetime", "source_timezone": "UTC", "timezone": "Asia/Jayapura",
                 "format": "%Y%m%d_%H%M"}]},
        ],
    }}
    assert naming.build_folder_name(session, cfg) == "20260102_0130_20260102_0230"


def test_custom_values_preserve_spaces_and_replace_can_remove_hyphens():
    session = make_session({"raw": "  EAST-WING  "})
    cfg = {"naming": {
        "template": "{ZONE}",
        "variables": [{"name": "ZONE", "source": "json:raw", "operations": [
            {"op": "replace", "find": "-", "replace": " "}, {"op": "collapse_spaces"}]}],
    }}
    assert naming.build_folder_name(session, cfg) == "EAST WING"


def test_disabled_operation_is_preserved_but_not_applied():
    session = make_session({"raw": "A-B"})
    cfg = {"naming": {
        "template": "{VALUE}",
        "variables": [{"name": "VALUE", "source": "json:raw", "operations": [
            {"op": "replace", "find": "-", "replace": " ", "enabled": False}]}],
    }}
    assert naming.build_folder_name(session, cfg) == "A-B"


def test_variable_dependency_cycle_is_rejected():
    session = make_session({"raw": "x"})
    cfg = {"naming": {
        "template": "{A}",
        "variables": [
            {"name": "A", "source": "var:B"},
            {"name": "B", "source": "var:A"},
        ],
    }}
    try:
        naming.build_folder_name(session, cfg)
    except ValueError as exc:
        assert "cycle" in str(exc).lower()
    else:
        raise AssertionError("Dependency cycle should fail")


def test_required_variable_fails_when_source_is_empty():
    session = make_session({})
    cfg = {"naming": {
        "template": "{REQUIRED}",
        "variables": [{"name": "REQUIRED", "source": "json:missing", "required": True}],
    }}
    try:
        naming.build_folder_name(session, cfg)
    except ValueError as exc:
        assert "wajib" in str(exc).lower()
    else:
        raise AssertionError("Missing required variable should fail")
