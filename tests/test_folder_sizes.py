import json
import os
import tempfile
import unittest
from pathlib import Path

import zyw_core as core


class FolderSizeTests(unittest.TestCase):
    def _make_session(self, folder):
        os.makedirs(folder)
        (Path(folder) / "session.json").write_text(
            json.dumps({
                "device_id": "device-1",
                "task": "ZYW001 Kitchen",
                "location": "MM3006",
                "capturer": "Recorder",
                "stop_cause": "completed",
                "start_time_unix": 1790000000,
            }),
            encoding="utf-8",
        )

    def test_session_size_includes_every_file_and_nested_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session_00001"
            self._make_session(session)
            (session / "camera.mcap").write_bytes(b"mcap-data")
            (session / "metadata.bin").write_bytes(b"metadata")
            nested = session / "camera" / "front"
            nested.mkdir(parents=True)
            (nested / "video.h265").write_bytes(b"video-payload")
            hidden = session / ".cache"
            hidden.mkdir()
            (hidden / "index.dat").write_bytes(b"hidden-data")

            expected = sum(p.stat().st_size for p in session.rglob("*") if p.is_file())
            scanned = core.scan_session(str(session))

            self.assertEqual(expected, scanned.size)
            self.assertEqual(1, len(scanned.files))
            self.assertFalse(scanned.files[0].ok)  # MCAP validation stays MCAP-specific.

    def test_folder_stats_group_and_root_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "recordings"
            session = root / "Group A" / "session_00001"
            self._make_session(session)
            (session / "camera.mcap").write_bytes(b"mcap-data")
            (session / "sidecar.json").write_text("{}", encoding="utf-8")
            nested = session / "assets"
            nested.mkdir()
            (nested / "frame.jpg").write_bytes(b"frame-data")
            (root / "root-notes.txt").write_text("outside session", encoding="utf-8")

            total, groups = core.folder_stats(str(root))
            session_size = sum(p.stat().st_size for p in session.rglob("*") if p.is_file())
            root_size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())

            self.assertEqual(session_size, groups["Group A"]["size"])
            self.assertEqual(root_size, total["size"])
            self.assertGreater(total["size"], groups["Group A"]["size"])


if __name__ == "__main__":
    unittest.main()
