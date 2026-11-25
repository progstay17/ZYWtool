import json

import pytest

import preset_io


def test_export_import_round_trip_strips_machine_specific_paths(tmp_path):
    config = {
        "shift_mode": "none",
        "shifts": [],
        "excel_root": r"C:\Users\private\Reports",
        "organized_root": r"D:\private\organized",
        "naming": {
            "source_json": r"C:\Users\private\session.json",
            "template": "{DATE}_{ROOM}",
            "field_map": {"DATE": "start_time_unix"},
            "variables": [{"name": "ROOM", "source": "json:task", "operations": [
                {"op": "split", "delimiter": " - ", "index": 1}]}],
        },
    }
    path = tmp_path / "Default.zywpreset.json"
    preset_io.export_preset_file(path, "Default Naming", config)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "excel_root" not in payload["config"]
    assert "organized_root" not in payload["config"]
    assert payload["config"]["naming"]["source_json"] == ""

    name, imported = preset_io.import_preset_file(path)
    assert name == "Default Naming"
    assert imported["naming"]["variables"][0]["name"] == "ROOM"
    assert "excel_root" not in imported


def test_import_rejects_non_zywtool_files(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"format": "other", "version": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="bukan preset"):
        preset_io.import_preset_file(path)


def test_import_rejects_unknown_variable_operations(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({
        "format": preset_io.FORMAT_ID,
        "version": preset_io.FORMAT_VERSION,
        "name": "Bad",
        "config": {"naming": {"template": "{A}", "variables": [
            {"name": "A", "source": "json:x", "operations": [{"op": "run_code"}]}
        ]}},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="tidak valid"):
        preset_io.import_preset_file(path)
