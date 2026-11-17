import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import handcheck
import preview_frames
import undo_arrange
import zyw_core as core


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
            self.assertEqual("", cfg["organized_root"])
            self.assertEqual("", cfg["preview_root"])
            self.assertEqual("", cfg["hand_check_root"])

    def test_new_install_has_no_default_output_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(core, "CONFIG_PATH", os.path.join(tmp, "missing.json")):
                cfg = core.load_config()
            for key in ("excel_root", "preview_root", "hand_check_root", "organized_root"):
                self.assertEqual("", cfg[key], key)
                self.assertEqual("", core.config_output_dir(cfg, key))

    def test_blank_excel_destination_is_rejected_instead_of_using_fallback(self):
        with self.assertRaisesRegex(ValueError, "Excel output"):
            core.export_excel([], {"excel_root": "", "excel_filename": "ZYW_Rekap.xlsx"})

    def test_prepare_output_dir_creates_missing_nested_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "new", "excel")
            self.assertEqual(os.path.abspath(target), core.prepare_output_dir(target))
            self.assertTrue(os.path.isdir(target))

    def test_prepare_output_dir_rejects_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "not-a-folder.txt")
            Path(file_path).write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bukan folder"):
                core.prepare_output_dir(file_path)

    def test_preview_and_handcheck_require_explicit_paths(self):
        with patch.object(core, "load_config", return_value={"preview_root": ""}), self.assertRaisesRegex(
            ValueError, "Preview output"
        ):
            preview_frames.output_root()
        with patch.object(core, "load_config", return_value={"hand_check_root": ""}), self.assertRaisesRegex(
            ValueError, "Hand Check output"
        ):
            handcheck.report_root()

    def test_arrange_requires_explicit_destination(self):
        with self.assertRaisesRegex(ValueError, "Organized folders"):
            core.arrange([], {"organized_root": ""}, "source", apply=False)

    def test_save_config_creates_missing_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "new", "nested", "zyw_config.json")
            with patch.object(core, "CONFIG_PATH", config_path):
                core.save_config({"excel_root": "", "preview_root": ""})
            self.assertTrue(os.path.isfile(config_path))
            self.assertEqual({"excel_root": "", "preview_root": ""},
                             json.loads(Path(config_path).read_text(encoding="utf-8")))

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
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            core, "load_config", return_value={"preview_root": tmp}
        ):
            self.assertEqual(os.path.abspath(tmp), preview_frames.output_root())

    def test_handcheck_reports_stay_under_selected_folder(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            core, "load_config", return_value={"hand_check_root": tmp}
        ):
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
