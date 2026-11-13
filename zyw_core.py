"""ZYWtool core: scan sesi, cek kesehatan mcap, durasi, pembagian shift, Excel, dan salin per folder.
ZYWtool contributors"""
import sys
import json
import os
import re
import shutil
import datetime as dt
from dataclasses import dataclass, field

from mcap.reader import make_reader

WIB = dt.timezone(dt.timedelta(hours=7))
MAGIC = b"\x89MCAP0\r\n"
HERE = (os.environ.get("ZYWTOOL_HOME") or
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = (os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ZYWtool", "zyw_config.json")
                if getattr(sys, "frozen", False) else os.path.join(HERE, "zyw_config.json"))
SHEET = "ZY White"
CHECK_SHEET = "Cek File"
UNSHIFTED = "DI LUAR SHIFT"
CREDIT = "ZYWtool contributors"
STATUS_LABELS = ["OSS Not Yet", "Galaxea Not Yet", "HDD Not Yet"]

HEADERS = ["Device No.", "Date", "Activity", "Status", "QC", "Recorder Name", "Location", "Shift",
           "Raw Recording Hours", "No. of Raw Sessions", "No. of Qualified Sessions",
           "Qualified Hours", "Rejected Hours", "Supervisor", "Total data"]

DEFAULT_CONFIG = {
    # [jam mulai, jam selesai, label persis seperti dropdown di sheet, nomor shift]
    "shifts": [
        ["07:00", "11:00", "7 AM - 11 PM", 1],
        ["12:00", "16:00", "12 PM - 4 PM", 2],
        ["16:10", "18:30", "4:10 PM - 6:30 PM", 3],
        ["18:30", "20:30", "6:30 PM - 8:80 PM", 4],
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
    "excel_path": r"C:\ZYW\ZYW_Rekap.xlsx",
    "organized_root": r"C:\ZYW_organized",
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(cfg):
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


def scan_session(path, full=False):
    s = Session(name=os.path.basename(path), path=path)
    try:
        with open(os.path.join(path, "session.json"), encoding="utf-8") as f:
            m = json.load(f)
    except Exception as e:
        m = {}
        s.errors.append(f"session.json rusak: {e}")
    s.device_id = m.get("device_id", "")
    s.task = m.get("task", "")
    s.location = m.get("location", "")
    s.capturer = m.get("capturer", "")
    s.stop_cause = m.get("stop_cause", "")
    s.client_unix_us = m.get("client_unix_us")
    s.device_no, s.activity = _task_fields(s.task)
    if "start_time_unix" in m:
        s.start = dt.datetime.fromtimestamp(m["start_time_unix"], WIB)
    else:
        s.errors.append("start_time_unix tidak ada")
    if not s.location:
        s.warnings.append("location kosong")

    mcaps = sorted(x for x in os.listdir(path) if x.lower().endswith(".mcap"))
    if not mcaps:
        s.errors.append("tanpa file mcap")
    for fn in mcaps:
        mf = check_mcap(os.path.join(path, fn), full=full)
        s.files.append(mf)
        s.size += mf.size
        if mf.ok:
            s.duration_s += mf.duration_s
        else:
            s.errors.append(f"{fn}: {mf.error}")
    if mcaps and len(mcaps) <= 1:
        s.warnings.append("hanya 1 file mcap (sesi pendek / mungkin tidak lengkap)")
    if not s.stop_cause:
        s.warnings.append("stop_cause kosong")
    if s.client_unix_us and s.start and abs(s.start.timestamp() - s.client_unix_us / 1e6) > 60:
        s.warnings.append("start_time beda >60 dtk dari client_unix_us")
    # session.json ditulis saat sesi selesai: waktu tulis harus sama dengan mulai + durasi
    try:
        written = os.path.getmtime(os.path.join(path, "session.json"))
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
    """Cari folder sesi (session_* yang punya session.json) sampai 2 level di bawah root.
    Mendukung struktur baru root/<folder grup>/session_xxx. Folder yang diawali titik diabaikan."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if os.path.basename(dirpath).startswith("session_") and "session.json" in filenames:
            found.append(dirpath)
            dirnames[:] = []
        elif depth >= 2:
            dirnames[:] = []
    return sorted(found)


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


def split_shifts(s, shifts):
    """Satu sesi = satu shift, ditentukan dari waktu MULAI sesi:
    1. Shift yang memuat waktu mulai.
    2. Mulai di celah (sebelum shift pertama atau di antara dua shift) -> shift berikutnya.
    3. Mulai setelah shift terakhir -> DI LUAR SHIFT.
    Menit yang lewat batas akhir shift terpilih dicatat sebagai lembur."""
    s.split, s.shift, s.overtime_min = {}, UNSHIFTED, 0.0
    if not s.start:
        return s
    day = s.start.date()
    wins = sorted(((dt.datetime.combine(day, parse_hm(st), WIB),
                    dt.datetime.combine(day, parse_hm(en), WIB), label)
                   for st, en, label, *_ in shifts), key=lambda w: w[0])
    t = s.start
    cont = [w for w in wins if w[0] <= t < w[1]]
    if cont:
        chosen = max(cont, key=lambda w: w[0])
    else:
        nxt = [w for w in wins if w[0] > t]
        chosen = min(nxt, key=lambda w: w[0]) if nxt else None
    if chosen is None:
        return s
    a, b, label = chosen
    s.shift = label
    s.split = {label: s.duration_s / 60}
    s.overtime_min = round(max(0.0, (s.end - b).total_seconds() / 60), 1)
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
    """Nama folder: yyyymmdd_LOKASI_NamaRecorder_ZYWxxx_S<nomor shift>_Aktivitas
    contoh: YYYYMMDD_LOKASI_RecorderContoh_DEVICE_S1_Aktivitas
    Semua sesi dengan kunci yang sama masuk ke folder grup yang sama."""
    base = {}
    for s in sessions:
        if not s.start:
            continue
        base[s.name] = "_".join([
            s.start.strftime("%Y%m%d"), _alnum(s.location) or "NOLOC",
            _alnum(s.capturer) or "NOREC", s.device_no or "NODEV",
            f"S{shift_number(s.shift, cfg)}", _alnum(s.activity) or "NOACT"])
    return base
    return names


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
    """Susun sesi ke folder grup di dalam root (direktori asli).
    Folder session_xxx TIDAK di-rename, hanya dipindah. Sesi CORRUPT ke root/_REJECTED, sesi WARN tetap di grupnya.
    Setelah dipindah, s.path ikut diperbarui. Log pemindahan selalu ditulis (juga kalau berhenti di tengah)."""
    plan = []
    names = name_map(sessions, cfg)
    for s in sessions:
        if not s.start or s.name not in names:
            continue
        if s.health == "CORRUPT":
            dest_dir = os.path.join(root, "_REJECTED")
        else:
            dest_dir = os.path.join(root, names[s.name])
        if os.path.normpath(os.path.dirname(s.path)) == os.path.normpath(dest_dir):
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
                os.rename(src_dir, dst_dir)
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

    path = cfg["excel_path"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
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
                None if str(ws.cell(r + i, 4).value or '').startswith('鈽?) else ws.cell(r + i, 4).value
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
    """Hitung total sesi, size, dan durasi di dalam sebuah folder (rekursif, sampai 2 level).
    Mengembalikan (total, per_grup). Grup = nama folder induk tiap sesi."""
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

