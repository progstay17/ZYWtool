import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zyw_core as core


class RecorderDiscoveryTests(unittest.TestCase):
    def _session(self, path, metadata=True):
        path.mkdir(parents=True)
        if metadata:
            (path / "session.json").write_text(json.dumps({
                "device_id": "device-1", "task": "ZYW001 Kitchen",
                "location": "Room A", "capturer": "Recorder A",
                "stop_cause": "completed", "start_time_unix": 1790000000,
            }), encoding="utf-8")
        return path

    def test_discovers_session_deeper_than_two_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(Path(tmp) / "group" / "batch" / "nested" / "session_00001")
            (session / "record.mcap").write_bytes(b"not-a-real-mcap")
            self.assertEqual([str(session)], core.find_session_dirs(tmp))

    def test_discovers_session_with_mcap_in_nested_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(Path(tmp) / "group" / "session_00002")
            nested = session / "recorder" / "camera"
            nested.mkdir(parents=True)
            (nested / "record.mcap").write_bytes(b"not-a-real-mcap")
            scanned = core.scan_session(str(session))
            self.assertEqual(1, len(scanned.files))
            self.assertIn("recorder", scanned.files[0].path)
            self.assertTrue(scanned.errors)

    def test_reports_session_with_mcap_but_missing_session_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(Path(tmp) / "session_00003", metadata=False)
            (session / "record.mcap").write_bytes(b"not-a-real-mcap")
            found = core.find_session_dirs(tmp)
            self.assertEqual([str(session)], found)
            scanned = core.scan_session(str(session))
            self.assertTrue(any("session.json" in e for e in scanned.errors))
            self.assertEqual(1, len(scanned.files))

    def test_scan_audit_excel_keeps_sessions_without_start_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = core.Session(name="session_00004", path=os.path.join(tmp, "session_00004"))
            session.errors.append("start_time_unix tidak ada")
            path, _ = core.export_excel([session], {"excel_root": tmp, "excel_filename": "audit.xlsx"})
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True)
            self.assertIn("Scan Audit", wb.sheetnames)
            ws = wb["Scan Audit"]
            self.assertEqual("session_00004", ws["A2"].value)
            self.assertIn("start_time_unix", ws["K2"].value)
            wb.close()

    def test_gui_undo_core_restores_arrange_log_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "recordings"
            arranged_root = Path(tmp) / "organized"
            original = root / "Group" / "session_00005"
            arranged = arranged_root / "Group" / "session_00005"
            (root / "Group").mkdir(parents=True)
            arranged.mkdir(parents=True)
            (arranged / "payload.bin").write_bytes(b"safe")
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            log = log_dir / "arrange_20261117_000000.json"
            log.write_text(json.dumps([{"from": str(original), "to": str(arranged)}]), encoding="utf-8")
            import undo_arrange as undo_tool
            with patch.object(core, "HERE", tmp), patch.object(undo_tool, "HERE", tmp):
                count, receipt = core.undo_arrange(str(log_dir))
            self.assertEqual(1, count)
            self.assertTrue(original.is_dir())
            self.assertFalse(arranged.exists())
            self.assertTrue(Path(receipt).is_file())


if __name__ == "__main__":
    unittest.main()
