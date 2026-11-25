"""ZYWtool core: scan sesi, cek kesehatan mcap, durasi, pembagian shift, Excel, dan salin per folder.
Fadhil Ghifarion 法迪 for AIT"""
import sys
import json
import os
import re
import shutil
import tempfile
import datetime as dt
from dataclasses import dataclass, field

from mcap.reader import make_reader
import naming

WIB = dt.timezone(dt.timedelta(hours=7))
MAGIC = b"\x89MCAP0\r\n"
HERE = (os.environ.get("ZYWTOOL_HOME") or
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__))))
APP_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ZYWtool")
CONFIG_PATH = (os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ZYWtool", "zyw_config.json")
                if getattr(sys, "frozen", False) else os.path.join(HERE, "zyw_config.json"))
SHEET = "ZY White"
CHECK_SHEET = "Cek File"
UNSHIFTED = "DI LUAR SHIFT"
NO_SHIFT = "TANPA SHIFT"
CREDIT = "Fadhil Ghifarion 法迪 for AIT"
STATUS_LABELS = ["OSS Not Yet", "Galaxea Not Yet", "HDD Not Yet"]

HEADERS = ["Device No.", "Date", "Activity", "Status", "QC", "Recorder Name", "Location", "Shift",
           "Raw Recording Hours", "No. of Raw Sessions", "No. of Qualified Sessions",
           "Qualified Hours", "Rejected Hours", "Supervisor", "Total data"]

DEFAULT_CONFIG = {
    # [jam mulai, jam selesai, label persis seperti dropdown di sheet, nomor shift]
    "config_version": 2,
    "shift_mode": "enabled",
    "shifts": [
        ["07:00", "11:00", "7 AM - 11 AM", 1],
        ["12:00", "16:00", "12 PM - 4 PM", 2],
        ["16:10", "18:30", "4:10 PM - 6:30 PM", 3],
        ["18:30", "20:30", "6:30 PM - 8:30 PM", 4],
    ],
    "qc": "",
    "supervisor": "",
    # Nama ruangan/aktivitas: {nama kanonik: [alias...]}. Teks yang tidak cocok dipakai apa adanya (kustom).
    # Daftar ini juga jadi dropdown kolom Activity di Excel (teks lain tetap boleh diketik).
    "activities": {
        "Kitchen": ["kitchen", "dapur"],
        "Livingroom": ["livingroom", "living room", "living", "ruang tamu", "ruang keluarga"],
        "Bedroom": ["bedroom", "kamar tidur", "kamar"],
    },
    # Cek tangan MediaPipe (opsional, lambat): lihat handcheck.py
    "hand_check": {"frames": 20, "sample_every_s": 15, "min_frames": 20, "max_frames": 120,
                   "max_error_pct": 30, "rule": "strict", "conf": 0.3, "tiles": True, "cam": 0,
                   "report": True, "use_cache": False},
    "data_root": "",
    # excel_root adalah folder tujuan; nama workbook dibuat otomatis.
    "excel_path": "",  # kompatibilitas konfigurasi lama
    "excel_root": "",
    "excel_filename": "ZYW_Rekap.xlsx",
    "organized_root": "",
    "preview_root": "",
    "hand_check_root": "",
    "check_mode": "quick",
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    loaded = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("File konfigurasi harus berupa JSON object.")
            cfg.update(loaded)

    # Migrasi file Excel lama hanya jika pengguna memang menyimpan excel_path.
    # Jangan pernah menghidupkan kembali default path C:\ZYW atau fallback tersembunyi.
    if "excel_root" not in loaded and loaded.get("excel_path"):
        legacy = str(loaded["excel_path"]).strip()
        if legacy and legacy.lower() not in (r"c:\zyw\zyw_rekap.xlsx", r"c:\zyw"):
            cfg["excel_root"] = os.path.dirname(legacy) if os.path.splitext(legacy)[1] else legacy
            if os.path.basename(legacy).lower().endswith((".xlsx", ".xlsm")):
                cfg["excel_filename"] = os.path.basename(legacy)

    cfg.setdefault("config_version", 2)
    cfg.setdefault("shift_mode", "enabled")
    # Correct two display-only typos from the original defaults without changing shift times.
    legacy_labels = {"7 AM - 11 PM": "7 AM - 11 AM", "6:30 PM - 8:80 PM": "6:30 PM - 8:30 PM"}
    for item in cfg.get("shifts", []):
        if isinstance(item, list) and len(item) >= 3 and item[2] in legacy_labels:
            item[2] = legacy_labels[item[2]]
    cfg.setdefault("custom_presets", {})
    cfg.setdefault("naming", {"source_json": "", "template": naming.DEFAULT_TEMPLATE,
                              "field_map": dict(naming.DEFAULT_FIELD_MAP)})
    # Preserve the existing v1.0.5 operational setup as the users legacy default preset.
    if loaded and "active_preset" not in loaded:
        cfg["custom_presets"]["Default (Legacy Workflow)"] = {
            key: json.loads(json.dumps(cfg.get(key, DEFAULT_CONFIG.get(key))))
            for key in ("shift_mode", "shifts", "check_mode", "qc", "supervisor", "activities", "hand_check")
        }
        cfg["active_preset"] = "Default (Legacy Workflow)"
    for key in ("excel_root", "preview_root", "hand_check_root", "organized_root"):
        raw = str(cfg.get(key) or "").strip()
        cfg[key] = os.path.abspath(os.path.expandvars(os.path.expanduser(raw))) if raw else ""
    if loaded and "active_preset" not in loaded:
        try:
            save_config(cfg)
        except OSError:
            pass
    return cfg


def config_output_dir(cfg, key, fallback=None):
    """Return configured output directory; blank means setup is still required."""
    raw = (cfg or {}).get(key, fallback)
    raw = str(raw or "").strip()
    return os.path.abspath(os.path.expandvars(os.path.expanduser(raw))) if raw else ""


def prepare_output_dir(path):
    """Create and verify a user-selected output directory; never substitute a default."""
    raw = os.path.expandvars(os.path.expanduser(str(path or "").strip()))
    if not raw:
        raise ValueError("Folder tujuan belum dipilih.")
    target = os.path.abspath(raw)
    if os.path.exists(target) and not os.path.isdir(target):
        raise ValueError(f"Path menunjuk ke file, bukan folder: {target}")
    os.makedirs(target, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(prefix=".zywtool-write-test-", dir=target, delete=True):
            pass
    except OSError as exc:
        raise ValueError(f"Folder tidak bisa ditulisi: {target} ({exc})") from exc
    return target


def save_config(cfg):
    os.makedirs(os.path.dirname(os.path.abspath(CONFIG_PATH)), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def preset_catalog(cfg=None):
    """Built-in presets preserve the original ZYWtool workflow as the default."""
    base = DEFAULT_CONFIG
    legacy = {k: json.loads(json.dumps(base.get(k, DEFAULT_CONFIG.get(k))))
              for k in ("shift_mode", "shifts", "check_mode", "qc", "supervisor", "activities", "hand_check")}
    morning = json.loads(json.dumps(legacy))
    morning["shift_mode"] = "enabled"
    morning["shifts"] = [["07:00", "15:00", "7 AM - 3 PM", 1]]
    full_day = json.loads(json.dumps(legacy))
    full_day["shift_mode"] = "enabled"
    full_day["shifts"] = [
        ["07:00", "11:00", "7 AM - 11 AM", 1],
        ["11:00", "15:00", "11 AM - 3 PM", 2],
        ["15:00", "19:00", "3 PM - 7 PM", 3],
        ["19:00", "23:00", "7 PM - 11 PM", 4],
    ]
    no_shift = json.loads(json.dumps(legacy))
    no_shift["shift_mode"] = "none"
    return {
        "Default (Legacy Workflow)": legacy,
        "No Shift": no_shift,
        "Morning Shift": morning,
        "Full Day Operations": full_day,
    }


def apply_preset(cfg, name):
    """Apply operational settings only; never overwrite user paths or data locations."""
    catalog = preset_catalog(cfg)
    catalog.update((cfg.get("custom_presets") or {}))
    if name not in catalog:
        raise ValueError(f"Preset tidak ditemukan: {name}")
    result = json.loads(json.dumps(cfg))
    for key in ("shift_mode", "shifts", "check_mode", "qc", "supervisor", "activities", "hand_check", "naming"):
        if key in catalog[name]:
            result[key] = json.loads(json.dumps(catalog[name][key]))
    result["active_preset"] = name
    return result


def validate_shifts(shifts):
    if not isinstance(shifts, list):
        raise ValueError("Daftar shift harus berupa list.")
    if not shifts:
        raise ValueError("Minimal satu shift harus tersedia pada mode Shift-based.")
    parsed = []
    for i, item in enumerate(shifts, 1):
        if not isinstance(item, (list, tuple)) or len(item) < 4:
            raise ValueError(f"Shift {i} tidak lengkap.")
        start, end, label, number = item[:4]
        try:
            a = parse_hm(str(start))
            b = parse_hm(str(end))
        except Exception as exc:
            raise ValueError(f"Jam Shift {i} harus format HH:MM.") from exc
        if a == b:
            raise ValueError(f"Jam mulai dan selesai Shift {i} tidak boleh sama.")
        if not str(label).strip():
            raise ValueError(f"Nama Shift {i} belum diisi.")
        start_min = a.hour * 60 + a.minute
        end_min = b.hour * 60 + b.minute
        if end_min <= start_min:
            end_min += 1440
        parsed.append((start_min, end_min, str(label).strip()))
    labels = [item[2].casefold() for item in parsed]
    if len(labels) != len(set(labels)):
        raise ValueError("Nama shift harus unik.")
    for i, first in enumerate(parsed):
        for second in parsed[i + 1:]:
            for offset in (-1440, 0, 1440):
                if max(first[0], second[0] + offset) < min(first[1], second[1] + offset):
                    raise ValueError(f"Jadwal shift bertumpuk: {first[2]} dan {second[2]}.")
    return True


def parse_hm(t):
    h, m = map(int, t.strip().split(":"))
    return dt.time(h, m)


@dataclass
class McapFile:
    path: str
    size: int
    ok: bool = False
    duration_s: float = 0.0
    messages: int = 0
    error: str = ""


def check_mcap(path, full=False):
    """quick: magic header+footer, summary terbaca. full: + CRC chunk dan hitung semua pesan."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return McapFile(path, 0, error=f"tidak bisa dibaca: {e}")
    mf = McapFile(path, size)
    try:
        if mf.size == 0:
            raise ValueError("file kosong (0 byte)")
        with open(path, "rb") as f:
            if f.read(8) != MAGIC:
                raise ValueError("header MCAP tidak valid")
            f.seek(-8, os.SEEK_END)
            if f.read(8) != MAGIC:
                raise ValueError("footer MCAP hilang (file mungkin terpotong)")
            f.seek(0)
            reader = make_reader(f, validate_crcs=full)
            summ = reader.get_summary()
            if summ is None or summ.statistics is None:
                raise ValueError("summary/statistik tidak terbaca")
            st = summ.statistics
            mf.messages = st.message_count
            mf.duration_s = (st.message_end_time - st.message_start_time) / 1e9
            if full:
                n = sum(1 for _ in reader.iter_messages())
                if n != st.message_count:
                    raise ValueError(f"jumlah pesan {n} != footer {st.message_count}")
        mf.ok = True
    except Exception as e:
        mf.error = f"{type(e).__name__}: {e}"
    return mf


@dataclass
class Session:
    name: str
    path: str
    device_id: str = ""
    device_no: str = ""
    activity: str = ""
    location: str = ""
    capturer: str = ""
    task: str = ""
    start: dt.datetime | None = None
    client_unix_us: int | None = None
    stop_cause: str = ""
    files: list = field(default_factory=list)
    size: int = 0
    duration_s: float = 0.0
    shift: str = ""
    split: dict = field(default_factory=dict)   # label shift -> menit (satu sesi = satu shift)
    overtime_min: float = 0.0                   # menit yang lewat batas akhir shift
    hand: dict = field(default_factory=dict)    # hasil handcheck (kosong kalau tidak dijalankan)
    metadata: dict = field(default_factory=dict) # raw session.json for configurable folder naming
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def number(self):
        m = re.match(r"session_(\d+)", self.name)
        return int(m.group(1)) if m else None

    @property
    def health(self):
        if self.errors:
            return "CORRUPT"
        if self.warnings:
            return "WARN"
        return "OK"

    @property
    def end(self):
        return self.start + dt.timedelta(seconds=self.duration_s) if self.start else None


def canonical_activity(text, options=None):
    """Samakan nama ruangan dengan daftar 'activities' di config (mis. 'Living Room (2)' -> 'Livingroom').
    Kalau tidak ada yang cocok, teks dipakai apa adanya (kustom)."""
    text = " ".join((text or "").split())
    if options is None:
        options = load_config().get("activities", DEFAULT_CONFIG["activities"])
    norm = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "
    best, best_len = None, 0
    for canon, aliases in options.items():
        for a in [canon] + list(aliases):
            key = " " + re.sub(r"[^a-z0-9]+", " ", a.lower()).strip() + " "
            if key.strip() and key in norm and len(key) > best_len:
                best, best_len = canon, len(key)
    return best or text


def _task_fields(task):
    m = re.search(r"ZYW\s*0*(\d+)", task or "", re.I)
    device_no = f"ZYW{int(m.group(1)):03d}" if m else ""
    t = re.sub(r"(?i)\bcleaning\b", "", task or "")
    t = re.sub(r"(?i)\bZYW\s*\d+\b", "", t)
    t = re.sub(r"\(\s*\d+\s*\)", "", t)          # penanda urutan seperti "(2)"
    return device_no, canonical_activity(" ".join(t.split()))


def folder_size_bytes(path):
    """Jumlahkan ukuran semua file di folder secara rekursif, termasuk file tersembunyi.

    Symlink tidak diikuti agar target di luar folder atau file yang sama tidak terhitung
    dua kali. File/folder yang tidak dapat diakses dilewati.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [name for name in dirnames
                       if not os.path.islink(os.path.join(dirpath, name))]
        for name in filenames:
            file_path = os.path.join(dirpath, name)
            try:
                if not os.path.islink(file_path):
                    total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def scan_session(path, full=False):
    s = Session(name=os.path.basename(path), path=path)
    meta_path = os.path.join(path, "session.json")
    try:
        with open(meta_path, encoding="utf-8-sig") as f:
            m = json.load(f)
        if not isinstance(m, dict):
            raise ValueError("metadata bukan object JSON")
    except Exception as e:
        m = {}
        s.errors.append(f"session.json tidak tersedia/valid: {type(e).__name__}: {e}")
    s.metadata = m
    s.device_id = m.get("device_id", "")
    s.task = m.get("task", "")
    s.location = m.get("location", "")
    s.capturer = m.get("capturer", "")
    s.stop_cause = m.get("stop_cause", "")
    s.client_unix_us = m.get("client_unix_us")
    s.device_no, s.activity = _task_fields(s.task)
    try:
        if m.get("start_time_unix") is not None:
            s.start = dt.datetime.fromtimestamp(float(m["start_time_unix"]), WIB)
        else:
            s.errors.append("start_time_unix tidak ada")
    except (TypeError, ValueError, OSError, OverflowError) as e:
        s.errors.append(f"start_time_unix tidak valid: {e}")
    if not s.location:
        s.warnings.append("location kosong")

    # Recorder exports may nest MCAP files below session subdirectories.
    mcaps = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        mcaps.extend(os.path.join(dirpath, fn) for fn in filenames if fn.lower().endswith(".mcap"))
    mcaps.sort(key=str.casefold)
    if not mcaps:
        s.errors.append("tanpa file mcap (termasuk subfolder)")
    for file_path in mcaps:
        fn = os.path.relpath(file_path, path)
        try:
            mf = check_mcap(file_path, full=full)
            s.files.append(mf)
            if mf.ok:
                s.duration_s += mf.duration_s
            else:
                s.errors.append(f"{fn}: {mf.error}")
        except Exception as e:
            s.errors.append(f"{fn}: {type(e).__name__}: {e}")
    s.size = folder_size_bytes(path)
    if mcaps and len(mcaps) <= 1:
        s.warnings.append("hanya 1 file mcap (sesi pendek / mungkin tidak lengkap)")
    if not s.stop_cause:
        s.warnings.append("stop_cause kosong")
    if s.client_unix_us and s.start:
        try:
            if abs(s.start.timestamp() - float(s.client_unix_us) / 1e6) > 60:
                s.warnings.append("start_time beda >60 dtk dari client_unix_us")
        except (TypeError, ValueError, OSError):
            s.warnings.append("client_unix_us tidak valid")
    try:
        written = os.path.getmtime(meta_path)
        if s.start:
            gap = written - (s.start.timestamp() + s.duration_s)
            if abs(gap) > 60:
                s.warnings.append(f"session.json ditulis {gap:+.0f} dtk dari (mulai + durasi)")
            if not s.stop_cause and written - s.start.timestamp() < 10:
                s.warnings.append("session.json tidak diperbarui saat stop (recording kemungkinan terputus)")
    except OSError:
        pass
    return s


def find_session_dirs(root):
    """Temukan folder session_* pada kedalaman berapa pun, tanpa mensyaratkan session.json.
    Folder sesi dikenali dari nama session_* dan keberadaan metadata atau MCAP di dalamnya.
    Sesi tanpa metadata tetap dilaporkan agar tidak hilang diam-diam.
    """
    found = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted((d for d in dirnames if not d.startswith(".")), key=str.casefold)
        if os.path.basename(dirpath).lower().startswith("session_"):
            has_mcap = any(fn.lower().endswith(".mcap") for _, _, files in os.walk(dirpath)
                           for fn in files)
            if "session.json" in filenames or has_mcap:
                found.append(dirpath)
                dirnames[:] = []
    return sorted(set(found), key=str.casefold)


def scan_all(root, full=False, progress=None, hand_check=False, hand_cfg=None, should_stop=None):
    paths = find_session_dirs(root)
    sessions = []
    for i, p in enumerate(paths, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(i, len(paths), os.path.basename(p))
        try:
            sessions.append(scan_session(p, full=full))
        except Exception as e:
            bad = Session(name=os.path.basename(p), path=p)
            bad.errors.append(f"gagal dipindai: {type(e).__name__}: {e}")
            sessions.append(bad)
    if hand_check:
        # mode opsional & lambat: cek tangan MediaPipe per sesi (sesi CORRUPT dilewati).
        # Laporan per sesi & per grup ditulis ke hand_check/reports mengikuti struktur direktori asli.
        import handcheck
        hc = handcheck.get_cfg(hand_cfg if hand_cfg is not None else load_config().get("hand_check"))
        items = []
        for s in sessions:
            it = {"path": s.path, "name": s.name, "recorder": s.capturer, "location": s.location,
                  "start": s.start.strftime("%Y-%m-%d %H:%M") if s.start else "",
                  "duration_min": s.duration_s / 60 if s.duration_s else None, "health": s.health}
            if s.health == "CORRUPT" or not s.files:
                it["skip"] = "dilewati (sesi CORRUPT)"
            items.append(it)
        entries = handcheck.check_sessions(items, hc, root, progress=progress, should_stop=should_stop)
        by_path = {os.path.normpath(e["path"]): e for e in entries}
        for s in sessions:
            e = by_path.get(os.path.normpath(s.path))
            if e is None or e.get("skip"):
                continue
            h = e.get("hand")
            if h and h.get("frames"):
                s.hand = h
                if h.get("flag"):
                    s.warnings.append(f"tangan: {h['pct']:.0f}% frame error ({h['rule']}) > batas {h['max']:.0f}%")
            elif e.get("note"):
                s.warnings.append("hand check gagal: " + e["note"])
        stopped = bool(should_stop and should_stop())
        globals()["LAST_HAND_REPORT"] = (handcheck.output_path(root, entries)
                                         if hc.get("report") and entries and not stopped else None)
    seen = {}
    for s in sessions:
        if s.client_unix_us:
            seen.setdefault(s.client_unix_us, []).append(s)
    for group in seen.values():
        if len(group) > 1:
            for s in group:
                s.warnings.append("client_unix_us sama dengan sesi lain")
    by_dev = {}
    for s in sessions:
        if s.start and s.duration_s > 0:
            by_dev.setdefault(s.device_id, []).append(s)
    for group in by_dev.values():
        group.sort(key=lambda s: s.start)
        for a, b in zip(group, group[1:]):
            if b.start < a.end:
                a.warnings.append(f"overlap waktu dengan {b.name}")
                b.warnings.append(f"overlap waktu dengan {a.name}")
    sessions.sort(key=lambda s: s.start or dt.datetime.min.replace(tzinfo=WIB))
    return sessions


def split_shifts(s, shifts, enabled=True):
    """Assign one shift by session start; supports gaps and overnight shift windows."""
    s.split, s.shift, s.overtime_min = {}, (UNSHIFTED if enabled else NO_SHIFT), 0.0
    if not enabled or not s.start:
        return s
    validate_shifts(shifts)
    day = s.start.date()
    wins = []
    for day_offset in (-1, 0):
        target_day = day + dt.timedelta(days=day_offset)
        for st, en, label, *_ in shifts:
            a = dt.datetime.combine(target_day, parse_hm(st), WIB)
            b = dt.datetime.combine(target_day, parse_hm(en), WIB)
            if b <= a:
                b += dt.timedelta(days=1)
            wins.append((a, b, label))
    wins.sort(key=lambda w: w[0])
    t = s.start
    containing = [w for w in wins if w[0] <= t < w[1]]
    if containing:
        chosen = max(containing, key=lambda w: w[0])
    else:
        following = [w for w in wins if w[0] > t and w[0].date() == day]
        chosen = min(following, key=lambda w: w[0]) if following else None
    if chosen is None:
        return s
    a, b, label = chosen
    s.shift = label
    s.split = {label: s.duration_s / 60}
    s.overtime_min = round(max(0.0, (s.end - b).total_seconds() / 60), 2) if s.end else 0.0
    return s


def apply_filter(sessions, sess_from=None, sess_to=None, time_from=None, time_to=None, shift=None):
    out = []
    for s in sessions:
        n = s.number
        if sess_from is not None and (n is None or n < sess_from):
            continue
        if sess_to is not None and (n is None or n > sess_to):
            continue
        if time_from and s.start and s.start.time() < parse_hm(time_from):
            continue
        if time_to and s.start and s.start.time() > parse_hm(time_to):
            continue
        if shift and shift != "(semua)" and shift not in s.split and s.shift != shift:
            continue
        out.append(s)
    return out


def build_rows(sessions):
    """Satu baris Excel = (device, tanggal, activity, lokasi, shift, recorder).
    Durasi dipecah per shift sesuai menit yang jatuh di shift itu.
    Jumlah sesi & size dihitung di shift utama sesi (tidak dobel)."""
    rows = {}
    for s in sessions:
        if not s.start:
            continue
        parts = s.split or {s.shift: s.duration_s / 60}
        for label, minutes in parts.items():
            key = (s.device_no or s.device_id, s.start.date(), s.activity, s.location, label, s.capturer)
            g = rows.setdefault(key, {"raw_s": 0, "raw_dur": 0.0, "q_s": 0, "q_dur": 0.0,
                                      "rej_dur": 0.0, "size": 0})
            secs = minutes * 60
            g["raw_dur"] += secs
            if s.health == "CORRUPT":
                g["rej_dur"] += secs
            else:
                g["q_dur"] += secs
            if label == s.shift:
                g["raw_s"] += 1
                g["size"] += s.size
                if s.health != "CORRUPT":
                    g["q_s"] += 1
    return rows


def _alnum(text):
    return re.sub(r"[^A-Za-z0-9]", "", text or "")


def shift_number(label, cfg):
    for entry in cfg["shifts"]:
        if entry[2] == label and len(entry) > 3:
            return entry[3]
    return 0


def name_map(sessions, cfg):
    """Build group folder names from the Preferences naming template."""
    base = {}
    for s in sessions:
        if not s.start:
            continue
        base[s.name] = naming.build_folder_name(s, cfg)
    return base


def resolve_session_path(s, root=None):
    """Pastikan s.path menunjuk folder yang ada. Kalau folder sudah dipindah (mis. setelah arrange),
    cari ulang berdasarkan nama sesi di root. Mengembalikan path baru, atau None kalau tidak ketemu."""
    if os.path.isdir(s.path):
        return s.path
    here = os.path.dirname(s.path)
    for base in (root, os.path.dirname(here), here):
        if base and os.path.isdir(base):
            for p in find_session_dirs(base):
                if os.path.basename(p) == s.name:
                    s.path = p
                    return p
    return None


def arrange(sessions, cfg, root, apply=False):
    """Susun sesi ke folder grup di organized_root (atau root jika belum diatur).
    Folder sesi tidak di-rename. Sesi CORRUPT masuk _REJECTED.
    Log menyimpan path asal dan tujuan untuk mendukung undo lintas direktori."""
    destination_root = config_output_dir(cfg, "organized_root")
    if not destination_root:
        raise ValueError("Lokasi Organized folders belum diatur. Buka Preferences terlebih dahulu.")
    plan = []
    names = name_map(sessions, cfg)
    for s in sessions:
        if not s.start or s.name not in names:
            continue
        if s.health == "CORRUPT":
            dest_dir = os.path.join(destination_root, "_REJECTED")
        else:
            dest_dir = os.path.join(destination_root, names[s.name])
        if os.path.normcase(os.path.normpath(os.path.dirname(s.path))) == os.path.normcase(os.path.normpath(dest_dir)):
            continue
        plan.append((s.path, os.path.join(dest_dir, s.name)))
    if apply and plan:
        by_path = {os.path.normpath(s.path): s for s in sessions}
        log_dir = os.path.join(HERE, "logs")
        os.makedirs(log_dir, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_path = os.path.join(log_dir, f"arrange_{stamp}.json")
        moved = []
        try:
            for src_dir, dst_dir in plan:
                if os.path.exists(dst_dir) or not os.path.isdir(src_dir):
                    continue
                os.makedirs(os.path.dirname(dst_dir), exist_ok=True)
                # shutil.move mendukung tujuan di drive/volume berbeda.
                shutil.move(src_dir, dst_dir)
                moved.append({"from": src_dir, "to": dst_dir})
                s = by_path.get(os.path.normpath(src_dir))
                if s is not None:
                    s.path = dst_dir
        finally:
            tmp_log = log_path + ".tmp"
            with open(tmp_log, "w", encoding="utf-8") as f:
                json.dump(moved, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_log, log_path)
    return plan


def undo_arrange(log_dir=None):
    """Undo the newest arrange log using the same guarded validator as the CLI."""
    import undo_arrange as undo_tool
    log_dir = log_dir or os.path.join(HERE, "logs")
    logs = sorted((os.path.join(log_dir, n) for n in os.listdir(log_dir)
                   if n.startswith("arrange_") and n.endswith(".json")),
                  key=os.path.getmtime, reverse=True) if os.path.isdir(log_dir) else []
    for log_path in logs:
        with open(log_path, encoding="utf-8") as f:
            records = json.load(f)
        if not isinstance(records, list) or not records:
            continue
        original_dirs = [os.path.abspath(m["from"]) for m in records if isinstance(m, dict) and m.get("from")]
        if not original_dirs:
            continue
        root = os.path.commonpath([os.path.dirname(p) for p in original_dirs])
        moves = undo_tool.prepare_undo(log_path, root)
        completed = undo_tool.execute_undo(moves, root)
        receipt_log = log_path[:-5] + ".undone.json"
        os.replace(log_path, receipt_log)
        return len(completed), receipt_log
    raise RuntimeError("Tidak ada riwayat Arrange yang bisa di-undo.")


def _key_of_row(vals):
    d = vals[1].date() if isinstance(vals[1], dt.datetime) else vals[1]
    return (vals[0], d, vals[2], vals[6], vals[7], vals[5])


def _write_check_sheet(wb, sessions, names):
    from openpyxl.styles import Font, PatternFill
    if CHECK_SHEET in wb.sheetnames:
        del wb[CHECK_SHEET]
    hs = wb.create_sheet(CHECK_SHEET)
    hs.append(["Session", "ZYW", "Lokasi", "Recorder", "Mulai WIB", "Durasi (menit)",
               "Size (MB)", "Health", "Masalah", "Nama folder", "Lembur (menit)", "Tangan error (%)",
               "Tangan error strict (%)", "Tangan error lenient (%)", "Tangan 0/1/2/3+"])
    for c in hs[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9D9D9")
    fills = {"CORRUPT": "F8D7DA", "WARN": "FFF3CD"}
    for s in sessions:
        issues = "; ".join(s.errors + s.warnings) or "-"
        hs.append([s.name, s.device_no, s.location, s.capturer,
                   s.start.strftime("%Y-%m-%d %H:%M") if s.start else "-",
                   round(s.duration_s / 60, 1), round(s.size / 1e6, 1), s.health, issues,
                   names.get(s.name, ""), s.overtime_min,
                   (round(s.hand["pct"], 1) if s.hand.get("frames") else ""),
                   (round(s.hand["pct_strict"], 1) if s.hand.get("frames") else ""),
                   (round(s.hand["pct_lenient"], 1) if s.hand.get("frames") else ""),
                   ("/".join(str(s.hand["counts"][k]) for k in ("0", "1", "2", "3+"))
                    if s.hand.get("frames") else "")])
        if s.health in fills:
            for c in hs[hs.max_row]:
                c.fill = PatternFill("solid", fgColor=fills[s.health])
    for col, w in zip("ABCDEFGHIJKLMNO", [40, 9, 10, 34, 17, 14, 12, 10, 90, 60, 14, 16, 18, 18, 16]):
        hs.column_dimensions[col].width = w
    hs.freeze_panes = "A2"


def export_excel(sessions, cfg):
    """Tulis ke sheet 'ZY White' (kolom mulai dari A, tiap recorder = blok 3 baris yang digabung).
    Checkbox Status yang sudah diisi dipertahankan saat export ulang.
    Sheet 'Cek File' berisi status tiap sesi (sehat / WARN / CORRUPT) beserta alasannya."""
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    # Workbook dibuat otomatis di folder pilihan. Jangan meminta pengguna
    # memilih file; jika workbook sudah ada, pertahankan isi/status sebelumnya.
    output_root = config_output_dir(cfg, "excel_root")
    if not output_root:
        raise ValueError("Lokasi Excel output belum diatur. Buka Preferences terlebih dahulu.")
    filename = os.path.basename(str(cfg.get("excel_filename") or "ZYW_Rekap.xlsx"))
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        filename = "ZYW_Rekap.xlsx"
    path = os.path.join(output_root, filename)
    os.makedirs(output_root, exist_ok=True)
    if os.path.exists(path):
        wb = load_workbook(path)
        ws = wb[SHEET] if SHEET in wb.sheetnames else wb.create_sheet(SHEET, 0)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = SHEET
        ws.append([SHEET])
        ws.merge_cells("A1:O1")
        ws["A1"].font = Font(bold=True, color="FFFFFF")
        ws["A1"].fill = PatternFill("solid", fgColor="2E5E3E")
        ws["A1"].alignment = Alignment(horizontal="center")
        ws.append(HEADERS)
        for c in ws[2]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="EBE3A0")
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 1) simpan status checkbox yang sudah diisi manual, per blok recorder
    saved_status = {}
    r = 3
    while r <= ws.max_row:
        if ws.cell(r, 1).value and ws.cell(r, 2).value:
            key = _key_of_row([ws.cell(r, c).value for c in range(1, 16)])
            saved_status[key] = [
                None if str(ws.cell(r + i, 4).value or '').startswith(('\u2610', '\u2611', '\u2612', '\u2713', '\u2714')) else ws.cell(r + i, 4).value
                for i in range(3)]
        r += 3

    # 2) bersihkan area data (lepas merge dulu)
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row >= 3:
            ws.unmerge_cells(str(rng))
    if ws.max_row >= 3:
        ws.delete_rows(3, ws.max_row - 2)

    # 3) tulis ulang blok per recorder
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    rows = build_rows(sessions)
    items = sorted(rows.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], str(kv[0][3]),
                                                 str(kv[0][4]), str(kv[0][5])))
    r = 3
    for key, g in items:
        dev, date, act, loc, shift, cap = key
        # Status, QC, Qualified Sessions/Hours, Rejected Hours, Supervisor dibiarkan kosong (diisi manual)
        vals = [dev, date, act, None, cfg.get("qc") or None, cap, loc, shift,
                g["raw_dur"] / 86400, g["raw_s"], None, None,
                None, cfg.get("supervisor") or None, g["size"] / 1e9]
        status = saved_status.get(key) or [None, None, None]
        for i in range(3):
            ws.cell(r + i, 4, status[i]).alignment = Alignment(vertical="center")
        for c, v in enumerate(vals, 1):
            if c != 4:
                ws.cell(r, c, v)
        ws.cell(r, 2).number_format = "yyyy-mm-dd"
        for c in (9, 12, 13):
            ws.cell(r, c).number_format = "[h]:mm:ss"
        ws.cell(r, 15).number_format = '0.0 "GB"'
        for c in range(1, 16):
            if c != 4:
                ws.merge_cells(start_row=r, start_column=c, end_row=r + 2, end_column=c)
            for i in range(3):
                cell = ws.cell(r + i, c)
                cell.border = border
                if c != 4:
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        r += 3

    for col, w in zip("ABCDEFGHIJKLMNO", [11, 12, 12, 16, 10, 36, 11, 16, 14, 12, 14, 14, 14, 13, 12]):
        ws.column_dimensions[col].width = w

    # dropdown Activity (kolom C): daftar dari config 'activities'; teks lain tetap boleh diketik
    try:
        from openpyxl.worksheet.datavalidation import DataValidation
        opts = list(cfg.get("activities", DEFAULT_CONFIG["activities"]).keys())
        ws.data_validations.dataValidation = [d for d in ws.data_validations.dataValidation
                                              if str(d.sqref) != "C3:C20000"]   # hanya milik tool ini
        dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True,
                            showErrorMessage=False)
        ws.add_data_validation(dv)
        dv.add("C3:C20000")
    except Exception:
        pass

    # 4) sheet cek file: sesi tidak sehat ditandai di sini
    _write_check_sheet(wb, sorted(sessions, key=lambda s: s.start or dt.datetime.min.replace(tzinfo=WIB)),
                       name_map(sessions, cfg))
    # Audit worksheet makes skipped/incomplete sessions visible instead of silently omitting them.
    audit_name = "Scan Audit"
    if audit_name in wb.sheetnames:
        del wb[audit_name]
    audit = wb.create_sheet(audit_name)
    audit.append(["Session", "Path", "Recorder", "Device", "Start (WIB)", "MCAP files",
                  "Parsed MCAP", "Duration (s)", "Size (bytes)", "Health", "Errors", "Warnings"])
    for session in sessions:
        audit.append([
            session.name, session.path, session.capturer, session.device_no or session.device_id,
            session.start.strftime("%Y-%m-%d %H:%M:%S") if session.start else "",
            len(session.files), sum(1 for f in session.files if getattr(f, "ok", False)),
            round(session.duration_s, 3), session.size, session.health,
            " | ".join(session.errors), " | ".join(session.warnings)])
    audit.freeze_panes = "A2"
    audit.auto_filter.ref = audit.dimensions
    for col, width in {"A":24,"B":65,"C":24,"D":16,"E":22,"F":12,"G":14,
                       "H":16,"I":18,"J":14,"K":60,"L":60}.items():
        audit.column_dimensions[col].width = width

    wb.properties.creator = CREDIT
    tmp_path = path + ".tmp"
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, path)
    except PermissionError:
        raise PermissionError(f"File Excel sedang dibuka. Tutup dulu lalu export ulang:\n{path}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return path, len(rows)


def fmt_hms(seconds):
    s = int(round(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


LAST_REPORT = None
LAST_HAND_REPORT = None
REPORT_DIR = os.path.join(HERE, "reports")


def save_report(sessions, tag="scan"):
    """Simpan tabel sesi sebagai TSV (tab-separated) supaya mudah di-copy-paste ke Excel."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"{tag}_{stamp}.tsv")
    cols = ["Session", "Grup", "ZYW", "Lokasi", "Recorder", "Mulai WIB", "Durasi (menit)",
            "Size (MB)", "Shift", "Lembur (menit)", "Health", "Masalah"]

    def clean(v):
        return str(v).replace("\t", " ").replace("\n", " ")

    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\t".join(cols) + "\n")
        for s in sessions:
            grup = os.path.basename(os.path.dirname(s.path))
            row = [s.name, grup, s.device_no, s.location, s.capturer,
                   s.start.strftime("%Y-%m-%d %H:%M:%S") if s.start else "-",
                   f"{s.duration_s / 60:.1f}".replace(".", ","),
                   f"{s.size / 1e6:.1f}".replace(".", ","),
                   s.shift, f"{s.overtime_min:.1f}".replace(".", ","), s.health,
                   "; ".join(s.errors + s.warnings) or "-"]
            f.write("\t".join(clean(v) for v in row) + "\n")
    return path


def folder_stats(folder, full=False, progress=None):
    """Hitung sesi, ukuran seluruh isi folder, dan durasi.
    Size per grup menjumlahkan semua file di dalam sesi grup; total size mencakup
    seluruh file di root yang dipilih, termasuk file di luar folder sesi.
    """
    sessions = scan_all(folder, full=full, progress=progress)
    groups = {}
    for s in sessions:
        parent = os.path.dirname(s.path)
        if os.path.normpath(parent) == os.path.normpath(folder):
            g = "(langsung di folder ini)"
        else:
            g = os.path.basename(parent)
        row = groups.setdefault(g, {"sesi": 0, "size": 0, "durasi_s": 0.0, "ok": 0, "warn": 0, "corrupt": 0})
        row["sesi"] += 1
        row["size"] += s.size
        row["durasi_s"] += s.duration_s
        row[s.health.lower()] += 1
    total = {"sesi": 0, "size": 0, "durasi_s": 0.0, "ok": 0, "warn": 0, "corrupt": 0}
    for row in groups.values():
        for k in total:
            total[k] += row[k]
    # Total Storage merepresentasikan seluruh folder sumber, bukan hanya sesi MCAP.
    total["size"] = folder_size_bytes(folder)
    return total, dict(sorted(groups.items()))


def _gb(v):
    return f"{v / 1e9:.2f}".replace(".", ",")


def folder_summary_tsv(total, groups):
    """Tabel hitung folder: satu baris per folder grup + baris TOTAL. Pisah tab, siap paste ke Excel."""
    lines = ["Grup\tSesi\tSize (GB)\tDurasi\tOK\tWARN\tCORRUPT"]
    for g, r in groups.items():
        lines.append(f"{g}\t{r['sesi']}\t{_gb(r['size'])}\t{fmt_hms(r['durasi_s'])}\t"
                     f"{r['ok']}\t{r['warn']}\t{r['corrupt']}")
    lines.append(f"TOTAL\t{total['sesi']}\t{_gb(total['size'])}\t{fmt_hms(total['durasi_s'])}\t"
                 f"{total['ok']}\t{total['warn']}\t{total['corrupt']}")
    return "\n".join(lines) + "\n"


def save_folder_summary(folder, total, groups):
    os.makedirs(REPORT_DIR, exist_ok=True)
    name = os.path.basename(os.path.normpath(folder)) or "root"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"hitung_{name}_{stamp}.tsv")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(folder_summary_tsv(total, groups))
    return path


def print_stats(folder, full=False):
    total, groups = folder_stats(folder, full=full)
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"ZYWtool - {CREDIT}")
    print(f"Folder: {folder}")
    print(f"{'Grup':<70} {'Sesi':>5} {'Size (GB)':>10} {'Durasi':>10} {'OK':>4} {'WARN':>5} {'CORRUPT':>8}")
    for g, r in groups.items():
        print(f"{g:<70} {r['sesi']:>5} {r['size']/1e9:>10.2f} {fmt_hms(r['durasi_s']):>10} "
              f"{r['ok']:>4} {r['warn']:>5} {r['corrupt']:>8}")
    print("-" * 120)
    print(f"{'TOTAL':<70} {total['sesi']:>5} {total['size']/1e9:>10.2f} {fmt_hms(total['durasi_s']):>10} "
          f"{total['ok']:>4} {total['warn']:>5} {total['corrupt']:>8}")
    print(f"Tersimpan: {save_folder_summary(folder, total, groups)}")
