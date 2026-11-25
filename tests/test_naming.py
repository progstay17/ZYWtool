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
