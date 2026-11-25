import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zyw_core as core
import handcheck


class ConfigurationV106Tests(unittest.TestCase):
    def test_no_shift_mode_assigns_explicit_no_shift_label(self):
        session = core.Session("session_1", "/tmp/session")
        session.start = dt.datetime(2026, 11, 25, 9, 0, tzinfo=core.WIB)
        core.split_shifts(session, core.DEFAULT_CONFIG["shifts"], enabled=False)
        self.assertEqual(core.NO_SHIFT, session.shift)
        self.assertEqual({}, session.split)

    def test_no_shift_mode_omits_shift_segment_from_folder_name(self):
        session = core.Session("session_1", "/tmp/session")
        session.start = dt.datetime(2026, 11, 26, 9, 0, tzinfo=core.WIB)
        session.location = "Jakarta"
        session.capturer = "Fadhil"
        session.device_no = "ZYW001"
        session.activity = "Cleaning"
        core.split_shifts(session, [], enabled=False)

        names = core.name_map([session], {"shift_mode": "none", "shifts": []})
        self.assertEqual(
            "20261126_Jakarta_Fadhil_ZYW001_Cleaning",
            names[session.name],
        )
        self.assertNotIn("S0", names[session.name])
        self.assertNotIn("TANPASHIFT", names[session.name].upper())

    def test_shift_based_folder_name_keeps_assigned_shift_segment(self):
        session = core.Session("session_1", "/tmp/session")
        session.start = dt.datetime(2026, 11, 26, 9, 0, tzinfo=core.WIB)
        session.location = "Jakarta"
        session.capturer = "Fadhil"
        session.device_no = "ZYW001"
        session.activity = "Cleaning"
        shifts = [["07:00", "15:00", "Morning", 1]]
        core.split_shifts(session, shifts, enabled=True)

        names = core.name_map(
            [session], {"shift_mode": "enabled", "shifts": shifts}
        )
        self.assertEqual(
            "20261126_Jakarta_Fadhil_ZYW001_S1_Cleaning",
            names[session.name],
        )

    def test_unassigned_session_never_gets_an_s0_folder_segment(self):
        session = core.Session("session_1", "/tmp/session")
        session.start = dt.datetime(2026, 11, 26, 23, 30, tzinfo=core.WIB)
        session.location = "Jakarta"
        session.capturer = "Fadhil"
        session.device_no = "ZYW001"
        session.activity = "Cleaning"
        shifts = [["07:00", "20:00", "Day", 1]]
        core.split_shifts(session, shifts, enabled=True)

        names = core.name_map(
            [session], {"shift_mode": "enabled", "shifts": shifts}
        )
        self.assertEqual(
            "20261126_Jakarta_Fadhil_ZYW001_Cleaning",
            names[session.name],
        )
        self.assertNotIn("S0", names[session.name])

    def test_legacy_default_shift_labels_are_corrected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            Path(path).write_text(json.dumps({
                "shifts": [["07:00", "11:00", "7 AM - 11 PM", 1],
                           ["18:30", "20:30", "6:30 PM - 8:80 PM", 4]]
            }), encoding="utf-8")
            with patch.object(core, "CONFIG_PATH", path):
                cfg = core.load_config()
            self.assertEqual("7 AM - 11 AM", cfg["shifts"][0][2])
            self.assertEqual("6:30 PM - 8:30 PM", cfg["shifts"][1][2])
            self.assertEqual("Default (Legacy Workflow)", cfg["active_preset"])
            self.assertEqual("7 AM - 11 AM",
                             cfg["custom_presets"]["Default (Legacy Workflow)"]["shifts"][0][2])
            persisted = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual("Default (Legacy Workflow)", persisted["active_preset"])
            self.assertEqual(2, len(persisted["custom_presets"]["Default (Legacy Workflow)"]["shifts"]))

    def test_apply_preset_never_overwrites_user_paths(self):
        cfg = core.load_config()
        cfg["excel_root"] = "C:/user/chosen/excel"
        cfg["preview_root"] = "C:/user/chosen/preview"
        changed = core.apply_preset(cfg, "No Shift")
        self.assertEqual("none", changed["shift_mode"])
        self.assertEqual(cfg["excel_root"], changed["excel_root"])
        self.assertEqual(cfg["preview_root"], changed["preview_root"])

    def test_shift_validation_detects_overlap_across_midnight(self):
        shifts = [["22:00", "06:00", "Night", 1], ["02:00", "04:00", "Early", 2]]
        with self.assertRaisesRegex(ValueError, "bertumpuk"):
            core.validate_shifts(shifts)

    def test_overnight_shift_matches_after_midnight(self):
        session = core.Session("session_1", "/tmp/session")
        session.start = dt.datetime(2026, 11, 25, 2, 30, tzinfo=core.WIB)
        session.duration_s = 3600
        core.split_shifts(session, [["22:00", "06:00", "Night", 1]])
        self.assertEqual("Night", session.shift)

    def test_session_after_last_shift_remains_outside_shift(self):
        session = core.Session("session_1", "/tmp/session")
        session.start = dt.datetime(2026, 11, 25, 23, 30, tzinfo=core.WIB)
        core.split_shifts(session, [["07:00", "20:00", "Day", 1]])
        self.assertEqual(core.UNSHIFTED, session.shift)

    def test_hand_check_gui_string_values_are_normalized(self):
        cfg = handcheck.get_cfg({"frames": "24", "max_error_pct": "25", "conf": "0.65"})
        self.assertEqual(24, cfg["frames"])
        self.assertEqual(25.0, cfg["max_error_pct"])
        self.assertEqual(0.65, cfg["conf"])

    def test_hand_check_rejects_invalid_frame_ranges(self):
        with self.assertRaisesRegex(ValueError, "Maximum frames"):
            handcheck.get_cfg({"min_frames": "100", "max_frames": "20"})


if __name__ == "__main__":
    unittest.main()
