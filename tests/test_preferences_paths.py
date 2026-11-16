import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import zyw_core as core
import handcheck
import preview_frames
import undo_arrange


class PreferencesPathTests(unittest.TestCase):
    def test_legacy_excel_file_setting_migrates_to_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = os.path.join(tmp, "Book1.xlsx")
            config_path = os.path.join(tmp, "zyw_config.json")
            Path(config_path).write_text(json.dumps({"excel_path": legacy, "organized_root": ""}), encoding="utf-8")
            with patch.object(core, "CONFIG_PATH", config_path):
                cfg = core.load_config()
            self.assertEqual(os.path.abspath(tmp), cfg["excel_root"])
            self.assertEqual("Book1.xlsx", cfg["excel_filename"])
            self.assertTrue(cfg["organized_root"].endswith(os.path.join("ZYWtool", "organized")))
            for key in ("excel_root", "preview_root", "hand_check_root", "organized_root"):
                self.assertTrue(os.path.isabs(cfg[key]), key)

    def test_excel_workbook_is_created_automatically_in_selected_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, rows = core.export_excel([], {"excel_root": tmp, "excel_filename": "Auto.xlsx"})
            self.assertEqual(os.path.join(os.path.abspath(tmp), "Auto.xlsx"), path)
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(0, rows)
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True)
            self.assertIn(core.SHEET, wb.sheetnames)
            self.assertIn(core.CHECK_SHEET, wb.sheetnames)
            wb.close()

    def test_preview_uses_latest_selected_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(core, "load_config", return_value={"preview_root": tmp}):
                self.assertEqual(os.path.abspath(tmp), preview_frames.output_root())

    def test_handcheck_reports_stay_under_selected_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(core, "load_config", return_value={"hand_check_root": tmp}):
                self.assertEqual(os.path.join(os.path.abspath(tmp), "reports"), handcheck.report_root())

    def test_undo_accepts_arranged_folder_outside_recording_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "recordings")
            output = os.path.join(tmp, "organized")
            original = os.path.join(root, "session_00001")
            arranged = os.path.join(output, "Group A", "session_00001")
            os.makedirs(arranged)
            os.makedirs(root)
            log = os.path.join(tmp, "arrange.json")
            Path(log).write_text(json.dumps([{"from": original, "to": arranged}]), encoding="utf-8")
            moves = undo_arrange.prepare_undo(log, root)
            self.assertEqual([(arranged, original)], moves)
            undo_arrange.execute_undo(moves, root)
            self.assertTrue(os.path.isdir(original))
            self.assertFalse(os.path.exists(arranged))

    def test_arrange_targets_selected_directory_not_recording_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source")
            destination = os.path.join(tmp, "chosen-output")
            os.makedirs(source)
            os.makedirs(destination)
            name = "session_00001"
            session = SimpleNamespace(name=name, start=dt.datetime(2026, 1, 1), health="OK",
                                      path=os.path.join(source, name))
            with patch.object(core, "name_map", return_value={name: "Group A"}):
                plan = core.arrange([session], {"organized_root": destination}, source, apply=False)
            self.assertEqual(1, len(plan))
            self.assertEqual(os.path.join(destination, "Group A", name), plan[0][1])


if __name__ == "__main__":
    unittest.main()
