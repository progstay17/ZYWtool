"""handcheck - cek tangan (MediaPipe Hand Landmarker) per sesi MCAP.
ZYWtool contributors

Dipakai dua cara (hasilnya sama karena memakai fungsi check_sessions yang sama):
  1. Mode independen : python handcheck.py <folder root atau folder sesi> [opsi]
  2. Mode scan opsional: zyw_core.scan_all(..., hand_check=True) / centang "Hand check" di GUI

Sampling: frame diambil merata sepanjang sesi, sekitar 1 sampel tiap `sample_every_s` detik
(minimal `min_frames`, maksimal `max_frames`). Kalau sample_every_s = 0, dipakai tepat `frames` frame.

Aturan per frame sampel:
  strict  : error kalau jumlah tangan != 2, atau ada titik tangan di luar frame
  lenient : error kalau tangan = 0, tangan > 2, atau ada titik tangan di luar frame
Tangan > 2 berarti ada tangan orang lain atau jari kaki yang terbaca sebagai tangan.
Sesi ditandai (FLAG / WARN) kalau persentase frame error > max_error_pct (default 30).

Laporan (hand_check/reports/), mengikuti struktur direktori asli:
  <nama root>/<folder grup = per orang>/handcheck_report.html           laporan grup
  <nama root>/<folder grup>/<sesi>/handcheck_report.html (+ gambar)      laporan per sesi
Menjalankan ulang menimpa laporan yang sama (tidak membuat salinan dobel).
Hasil bersifat probabilistik: pakai sebagai penanda untuk dicek manual, bukan keputusan otomatis.
"""
import argparse
import datetime as dt
import glob
import json
import math
import os
import re
import sys
import time

HERE = (os.environ.get("ZYWTOOL_HOME") or
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__))))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

CREDIT = "ZYWtool contributors"
DEFAULTS = {"frames": 20, "sample_every_s": 15, "min_frames": 20, "max_frames": 120,
            "max_error_pct": 30.0, "rule": "strict", "conf": 0.3, "tiles": True, "cam": 0,
            "report": True, "use_cache": False}
_MODEL_HOME = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
MODEL_DIR = os.path.join(_MODEL_HOME, "ZYWtool", "models")
MODEL = os.path.join(MODEL_DIR, "hand_landmarker.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"
OUT_DIR = os.path.join(HERE, "hand_check")
REPORT_DIR = os.path.join(OUT_DIR, "reports")
_DETECTORS = {}
THUMB_W = 480            # frame penuh tidak disimpan; hanya thumbnail untuk gambar laporan


class Cancelled(Exception):
    """Proses dihentikan pengguna (Stop)."""


def get_cfg(hc=None):
    cfg = dict(DEFAULTS)
    if isinstance(hc, dict):
        cfg.update({k: v for k, v in hc.items() if k in DEFAULTS})
    return cfg


# ----------------------------------------------------------------------------- deteksi
def ensure_model():
    """Download the official model on first use and verify it before atomic install."""
    import hashlib
    import shutil
    import urllib.request

    os.makedirs(MODEL_DIR, exist_ok=True)

    def sha256(path):
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    if os.path.isfile(MODEL):
        actual = sha256(MODEL)
        if actual == MODEL_SHA256:
            return MODEL
        raise RuntimeError(
            f"Model MediaPipe sudah ada tetapi checksum tidak cocok: {MODEL}. "
            "File tidak diubah; periksa atau pindahkan file tersebut lalu coba lagi."
        )

    partial = MODEL + ".part"
    try:
        request = urllib.request.Request(
            MODEL_URL, headers={"User-Agent": "ZYWtool-model-bootstrap/1.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
            shutil.copyfileobj(response, out)
        actual = sha256(partial)
        if actual != MODEL_SHA256:
            raise RuntimeError(
                f"Checksum model tidak cocok (SHA256 {actual}); unduhan ditolak."
            )
        os.replace(partial, MODEL)
        return MODEL
    except Exception as exc:
        try:
            if os.path.exists(partial):
                os.remove(partial)
        except OSError:
            pass
        raise RuntimeError(
            "Gagal mengunduh atau memverifikasi model MediaPipe. "
            "Periksa koneksi internet lalu coba fitur Hand Check lagi. "
            f"Detail: {type(exc).__name__}: {exc}"
        ) from exc


def _get_detector(conf):
    if conf not in _DETECTORS:
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        ensure_model()
        opts = vision.HandLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=MODEL), num_hands=6,
            min_hand_detection_confidence=conf, min_hand_presence_confidence=conf,
            min_tracking_confidence=conf)
        _DETECTORS[conf] = vision.HandLandmarker.create_from_options(opts)
    return _DETECTORS[conf]


def _detect(det, img, ox=0, oy=0):
    import numpy as np
    import mediapipe as mp
    rgb = np.ascontiguousarray(np.asarray(img.convert("RGB")))
    res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    w, h = img.size
    return [[(ox + p.x * w, oy + p.y * h) for p in hand] for hand in res.hand_landmarks]


def _centroid(h):
    return (sum(p[0] for p in h) / len(h), sum(p[1] for p in h) / len(h))


def _merge(hands, width):
    out = []
    for h in hands:
        c = _centroid(h)
        if all(((c[0] - _centroid(o)[0]) ** 2 + (c[1] - _centroid(o)[1]) ** 2) ** 0.5 > 0.10 * width
               for o in out):
            out.append(h)
    return out


def detect_hands(img, hc):
    """Deteksi tangan di satu frame. tiles=True: frame penuh + 4 potongan (lebih sensitif, lebih lambat)."""
    det = _get_detector(float(hc["conf"]))
    W, H = img.size
    hands = _detect(det, img)
    if hc.get("tiles", True):
        tw, th = int(W * 0.6), int(H * 0.6)
        for ox, oy in [(0, 0), (W - tw, 0), (0, H - th), (W - tw, H - th)]:
            hands += _detect(det, img.crop((ox, oy, ox + tw, oy + th)), ox, oy)
        hands = _merge(hands, W)
    return hands


def _is_out(h, W, H):
    return any(x < 0 or x > W or y < 0 or y > H for x, y in h)


def _is_err(r, rule):
    if rule == "strict":
        return r["n"] != 2 or r["out"]
    return r["n"] == 0 or r["n"] > 2 or r["out"]


# ----------------------------------------------------------------------------- pengambilan frame
def choose_n(duration_s, hc):
    step = float(hc.get("sample_every_s") or 0)
    if step <= 0:
        return int(hc["frames"])
    return max(int(hc["min_frames"]), min(int(hc["max_frames"]), math.ceil(duration_s / step)))


def _summaries(sess_dir, cam):
    """(file, jumlah frame kamera, waktu awal, waktu akhir) tiap file mcap yang terbaca + nama file yang dilewati."""
    from mcap.reader import make_reader
    topic = f"/ego/camera/{cam}"
    infos, skipped = [], []
    for f in sorted(glob.glob(os.path.join(sess_dir, "ego_*.mcap"))):
        try:
            with open(f, "rb") as fh:
                s = make_reader(fh).get_summary()
            if s is None or s.statistics is None:
                raise ValueError("summary tidak terbaca")
            cid = [c for c, ch in s.channels.items() if ch.topic == topic]
            cnt = s.statistics.channel_message_counts.get(cid[0], 0) if cid else 0
            infos.append((f, cnt, s.statistics.message_start_time, s.statistics.message_end_time))
        except Exception:
            skipped.append(os.path.basename(f))
    return infos, skipped


def frame_at(path, topic, t_target):
    """Frame terdekat sebelum t_target (ns). Baca jendela 3 dtk, decode mulai dari KEYFRAME TERAKHIR
    di jendela itu (maksimal sekitar 1 detik di belakang). Mengembalikan (gambar PIL, log_time) atau (None, None)."""
    from mcap.reader import make_reader
    import preview_frames as pf
    lo = max(0, t_target - 3_000_000_000)
    with open(path, "rb") as fh:
        msgs = [m for _, _, m in make_reader(fh).iter_messages(topics=[topic], starting_at=lo, ending_at=t_target)]
    if not msgs:
        return None, None
    parsed = []
    for m in msgs:
        p = pf.parse_proto(m.data)
        parsed.append((p.get(3, [b""])[0], p.get(4, [b""])[0].decode("utf-8", "replace")))
    keys = [i for i, (d, f) in enumerate(parsed) if pf.is_keyframe(d, f)]
    for k in reversed(keys[-2:]):          # coba keyframe terakhir, lalu satu sebelumnya
        fr = pf.decode_last([d for d, _ in parsed[k:]], parsed[k][1])
        if fr is not None:
            return fr.to_image(), msgs[-1].log_time
    return None, None


def sample_even(infos, n, cam, should_stop=None):
    """Generator: (idx, detik, gambar PIL) satu per satu, n frame yang tersebar merata di seluruh file sesi.
    Frame diberikan satu-satu supaya memori tidak menumpuk."""
    topic = f"/ego/camera/{cam}"
    infos = [i for i in infos if i[1] > 0]
    total = sum(i[1] for i in infos)
    if total == 0 or n <= 0:
        return
    targets = sorted({int((k + 0.5) * total / n) for k in range(n)})
    first_lt = infos[0][2]
    base, ti = 0, 0
    for f, cnt, st, en in infos:
        while ti < len(targets) and targets[ti] < base + cnt:
            if should_stop and should_stop():
                raise Cancelled()
            local = targets[ti] - base
            t_target = int(st + (local / cnt) * (en - st))
            try:
                img, lt = frame_at(f, topic, t_target)
            except Exception:
                img, lt = None, None
            if img is not None:
                yield targets[ti], max(0.0, (lt - first_lt) / 1e9), img
            ti += 1
        base += cnt


def iter_frames(sess_dir, infos, n, cam, use_cache, should_stop=None):
    """Generator frame sampel; use_cache (khusus pengujian) menyimpan/membaca frame di _cache."""
    from PIL import Image
    name = os.path.basename(os.path.normpath(sess_dir))
    cache = os.path.join(HERE, "_cache", name if cam == 0 else f"{name}_cam{cam}")
    if use_cache:
        files = sorted(glob.glob(os.path.join(cache, "f_*.png")))
        if len(files) == n:
            for f in files:
                parts = os.path.basename(f)[2:-4].split("_")
                yield int(parts[0]), float(parts[1]), Image.open(f).convert("RGB")
            return
        os.makedirs(cache, exist_ok=True)
        for old in glob.glob(os.path.join(cache, "f_*.png")):
            os.remove(old)
    for idx, t, img in sample_even(infos, n, cam, should_stop):
        if use_cache:
            img.convert("RGB").save(os.path.join(cache, f"f_{idx:07d}_{t:07.1f}.png"))
        yield idx, t, img


# ----------------------------------------------------------------------------- gambar
def _sheet(rows, imgs, W, H, tw, cols, title, rule):
    from PIL import Image, ImageDraw
    th = int(tw * H / W)
    nrows = max(1, -(-len(rows) // cols))
    sheet = Image.new("RGB", (cols * tw + 8, nrows * (th + 18) + 28), (30, 30, 30))
    sd = ImageDraw.Draw(sheet)
    sd.text((6, 6), title, fill=(230, 230, 230))
    for k, (r, img) in enumerate(zip(rows, imgs)):
        rr, cc = divmod(k, cols)
        x0, y0 = cc * tw + 4, rr * (th + 18) + 24
        t_img = img.convert("RGB").resize((tw, th))
        d = ImageDraw.Draw(t_img)
        for h in r["hands"]:
            pts = [(x * tw / W, y * th / H) for x, y in h]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            d.rectangle((min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3), outline=(255, 220, 0), width=2)
        sheet.paste(t_img, (x0, y0 + 16))
        err = _is_err(r, rule)
        sd.text((x0 + 2, y0 + 2),
                f"{int(r['t']) // 60:02d}:{int(r['t']) % 60:02d} #{r['idx']} tangan={r['n']}"
                f"{' keluar' if r['out'] else ''} {'ERROR' if err else 'ok'}",
                fill=(255, 90, 90) if err else (255, 255, 255))
    return sheet


def _save_png(img, path):
    tmp = path + ".tmp"
    img.save(tmp, format="PNG")
    os.replace(tmp, path)
    return path


# ----------------------------------------------------------------------------- analisis satu sesi
def _wilson(k, n, z=1.96):
    """Interval kepercayaan 95% (Wilson) untuk proporsi k/n, dalam persen."""
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, 100 * (c - half)), min(100.0, 100 * (c + half))


def analyze_session(sess_dir, hc=None, report_dir=None, use_cache=None, should_stop=None):
    """Analisis satu sesi. report_dir (opsional): simpan gambar sampel & gambar frame bermasalah di sana.
    Frame diproses satu per satu (hanya thumbnail yang disimpan di memori). should_stop() dicek di antara frame;
    kalau True, melempar Cancelled tanpa menulis apa pun. Mengembalikan dict hasil."""
    hc = get_cfg(hc)
    cam = int(hc["cam"])
    infos, skipped = _summaries(sess_dir, cam)
    total = sum(i[1] for i in infos)
    if total == 0:
        return {"frames": 0, "note": "tidak ada frame kamera yang bisa dibaca", "skipped_files": skipped}
    dur = sum((i[3] - i[2]) / 1e9 for i in infos if i[1])
    n = min(choose_n(dur, hc), total)
    use_cache = hc["use_cache"] if use_cache is None else use_cache
    rows, thumbs = [], []
    W = H = 0
    for idx, t, img in iter_frames(sess_dir, infos, n, cam, use_cache, should_stop):
        if should_stop and should_stop():
            raise Cancelled()
        if not W:
            W, H = img.size
        hands = detect_hands(img, hc)
        rows.append({"idx": idx, "t": t, "n": len(hands), "hands": hands,
                     "out": any(_is_out(h, W, H) for h in hands)})
        th = img.convert("RGB")
        thumbs.append(th.resize((THUMB_W, max(1, int(THUMB_W * H / W)))) if W > THUMB_W else th)
    if not rows:
        return {"frames": 0, "note": "tidak ada frame yang berhasil di-decode", "skipped_files": skipped}
    N = len(rows)
    counts = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for r in rows:
        counts[str(r["n"]) if r["n"] < 3 else "3+"] += 1
    rule = hc["rule"] if hc["rule"] in ("strict", "lenient") else "strict"
    err_strict = sum(1 for r in rows if _is_err(r, "strict"))
    err_len = sum(1 for r in rows if _is_err(r, "lenient"))
    err_n = err_strict if rule == "strict" else err_len
    pct = 100.0 * err_n / N
    res = {"frames": N, "counts": counts, "out": sum(1 for r in rows if r["out"]),
           "pct_strict": 100.0 * err_strict / N, "pct_lenient": 100.0 * err_len / N,
           "rule": rule, "pct": pct, "max": float(hc["max_error_pct"]), "flag": pct > float(hc["max_error_pct"]),
           "total_frames": total, "duration_s": dur, "interval_s": (dur / N) if dur else 0,
           "ci": list(_wilson(err_n, N)), "skipped_files": skipped, "sheet": "", "errors_sheet": "",
           "detail": [{"idx": r["idx"], "t": r["t"], "n": r["n"], "out": r["out"]} for r in rows]}
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
        name = os.path.basename(os.path.normpath(sess_dir))
        tw, cols = (400, 3) if N <= 24 else (240, 6)
        res["sheet"] = _save_png(
            _sheet(rows, thumbs, W, H, tw, cols, f"{name} | semua frame sampel ({N}) | rule {rule}", rule),
            os.path.join(report_dir, "handcheck_sample.png"))
        bad = [(r, th) for r, th in zip(rows, thumbs) if _is_err(r, rule)]
        ep = os.path.join(report_dir, "handcheck_error_frames.png")
        if bad:
            if len(bad) > 12:                       # pilih 12 frame bermasalah yang tersebar merata
                bad = [bad[int(k * len(bad) / 12)] for k in range(12)]
            res["errors_sheet"] = _save_png(
                _sheet([b[0] for b in bad], [b[1] for b in bad], W, H, 420, 3,
                       f"{name} | frame bermasalah (rule {rule})", rule), ep)
        elif os.path.exists(ep):
            os.remove(ep)                           # sisa dari run sebelumnya
    return res


def summary_line(h):
    if not h:
        return "Hand check: -"
    if not h.get("frames"):
        return f"Hand check: {h.get('note', '-')}"
    c = h["counts"]
    return (f"Hand check ({h['rule']}): {h['pct']:.0f}% frame error dari {h['frames']} sampel "
            f"[tangan 0/1/2/3+ = {c['0']}/{c['1']}/{c['2']}/{c['3+']}] | strict {h['pct_strict']:.0f}%, "
            f"lenient {h['pct_lenient']:.0f}% | batas {h['max']:.0f}% -> {'FLAG' if h['flag'] else 'ok'}")


# ----------------------------------------------------------------------------- laporan
def _safe(name):
    return re.sub(r'[<>:"|?*]', "_", name) or "_"


def report_dir_for(sess_dir, root):
    """Folder laporan sesi, mengikuti struktur direktori asli: <nama root>/<folder grup>/<sesi>."""
    sd, rt = os.path.normpath(sess_dir), os.path.normpath(root)
    try:
        if sd == rt:
            rel = os.path.join(os.path.basename(os.path.dirname(sd)), os.path.basename(sd))
        else:
            sub = os.path.relpath(sd, rt)
            if sub.startswith(".."):
                raise ValueError
            rel = os.path.join(os.path.basename(rt) or "root", sub)
    except ValueError:
        rel = os.path.join(os.path.basename(os.path.dirname(sd)), os.path.basename(sd))
    return os.path.join(REPORT_DIR, *[_safe(p) for p in rel.split(os.sep) if p])


def _root_is_session(root):
    return os.path.isfile(os.path.join(root, "session.json"))


def _meta(hc, root):
    return {"rule": hc["rule"], "max": hc["max_error_pct"], "conf": hc["conf"], "tiles": hc["tiles"],
            "every": hc["sample_every_s"], "min_frames": hc["min_frames"], "max_frames": hc["max_frames"],
            "frames": hc["frames"], "source": root, "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "credit": CREDIT}


def _read_meta(sd):
    try:
        with open(os.path.join(sd, "session.json"), encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        return {}
    start = ""
    if "start_time_unix" in m:
        start = dt.datetime.fromtimestamp(
            m["start_time_unix"], dt.timezone(dt.timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
    return {"recorder": m.get("capturer", ""), "location": m.get("location", ""), "start": start}


def write_session_report(entry, hc, root):
    import handreport
    rdir = report_dir_for(entry["path"], root)
    os.makedirs(rdir, exist_ok=True)
    out = handreport.build_report([entry], _meta(hc, root), os.path.join(rdir, "handcheck_report.html"),
                                  mode="session")
    tmp = os.path.join(rdir, "handcheck_result.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, os.path.join(rdir, "handcheck_result.json"))
    return out


def write_group_reports(entries, hc, root):
    """Satu laporan per folder grup (per orang), berisi tabel semua sesi di folder itu + link ke laporan sesi."""
    import handreport
    if _root_is_session(root):
        return []
    groups = {}
    for e in entries:
        groups.setdefault(os.path.dirname(os.path.normpath(e["path"])), []).append(e)
    out = []
    for gdir, items in groups.items():
        for e in items:
            e["link"] = f"{os.path.basename(os.path.normpath(e['path']))}/handcheck_report.html" if e.get("report") else ""
        rdir = os.path.dirname(report_dir_for(items[0]["path"], root))
        out.append(handreport.build_report(items, _meta(hc, root), os.path.join(rdir, "handcheck_report.html"),
                                           mode="group", title=os.path.basename(gdir) or "root"))
    return out


def write_summary_tsv(entries, hc, root):
    """Ringkasan teks (tab-separated, bisa langsung di-paste ke Excel) untuk satu kali proses."""
    if _root_is_session(root):
        return ""
    d = os.path.join(REPORT_DIR, _safe(os.path.basename(os.path.normpath(root)) or "root"))
    os.makedirs(d, exist_ok=True)
    cols = ["Grup", "Sesi", "Recorder", "Mulai", "Frame sampel", "Tangan 0", "Tangan 1", "Tangan 2",
            "Tangan 3+", "Error strict (%)", "Error lenient (%)", "Rule", "Batas (%)", "Flag", "Laporan", "Catatan"]
    lines = ["\t".join(cols)]
    comma = lambda v: f"{v:.1f}".replace(".", ",")
    for e in entries:
        h = e.get("hand") or {}
        ok = bool(h.get("frames"))
        c = h.get("counts", {})
        rep = os.path.relpath(e["report"], REPORT_DIR) if e.get("report") else ""
        row = [e.get("group", ""), e["name"], e.get("recorder", ""), e.get("start", ""),
               h.get("frames", 0) if ok else 0, c.get("0", ""), c.get("1", ""), c.get("2", ""), c.get("3+", ""),
               comma(h["pct_strict"]) if ok else "", comma(h["pct_lenient"]) if ok else "",
               h.get("rule", "") if ok else "", comma(h["max"]) if ok else "",
               ("YA" if h.get("flag") else "tidak") if ok else "", rep, e.get("note", "")]
        lines.append("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row))
    path = os.path.join(d, "_ringkasan.tsv")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path


def output_path(root, entries):
    """Path yang cocok untuk dibuka setelah selesai: laporan sesi (kalau root = satu sesi) atau folder laporan root."""
    if _root_is_session(root):
        return entries[0].get("report", "") if entries else ""
    d = os.path.join(REPORT_DIR, _safe(os.path.basename(os.path.normpath(root)) or "root"))
    return d if os.path.isdir(d) else ""


def check_sessions(items, hc, root, progress=None, should_stop=None, on_entry=None):
    """Analisis banyak sesi. items: list dict {path, name, recorder, location, start, duration_min, health, skip}.
    Laporan sesi ditulis SEGERA setelah tiap sesi selesai (jadi tetap ada kalau proses dihentikan),
    laporan grup + ringkasan ditulis di akhir. Mengembalikan list entry (sesuai urutan yang sempat diproses)."""
    hc = get_cfg(hc)
    entries, n = [], len(items)
    for i, it in enumerate(items, 1):
        if should_stop and should_stop():
            break
        e = dict(it)
        e.setdefault("group", os.path.basename(os.path.dirname(os.path.normpath(e["path"]))))
        e["note"], e["hand"] = "", None
        if e.get("skip"):
            e["note"] = e["skip"]
        else:
            if progress:
                progress(i, n, e["name"] + " (hand check)")
            try:
                rdir = report_dir_for(e["path"], root) if hc["report"] else None
                e["hand"] = analyze_session(e["path"], hc, report_dir=rdir, should_stop=should_stop)
                if e["hand"].get("frames"):
                    if e.get("duration_min") is None and e["hand"].get("duration_s"):
                        e["duration_min"] = e["hand"]["duration_s"] / 60
                else:
                    e["note"] = e["hand"].get("note", "")
            except Cancelled:
                break                      # dihentikan: sesi ini tidak ditulis setengah jadi
            except Exception as ex:
                e["note"] = f"{type(ex).__name__}: {ex}"
            if hc["report"]:
                try:
                    e["report"] = write_session_report(e, hc, root)
                except Exception as ex:
                    e["note"] = (e["note"] + " | " if e["note"] else "") + f"laporan gagal: {type(ex).__name__}: {ex}"
        entries.append(e)
        if on_entry:
            on_entry(e, i, n)
    if hc["report"] and entries:
        try:
            write_group_reports(entries, hc, root)
            write_summary_tsv(entries, hc, root)
        except Exception as ex:
            print(f"Peringatan: laporan grup/ringkasan gagal ditulis: {type(ex).__name__}: {ex}", flush=True)
    return entries


# ----------------------------------------------------------------------------- CLI
def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Cek tangan MediaPipe per sesi MCAP (mode independen).")
    ap.add_argument("target", help="folder root (berisi banyak sesi / folder grup) atau satu folder sesi")
    ap.add_argument("--n", type=int, help="pakai tepat N frame sampel per sesi (menonaktifkan sampling per detik)")
    ap.add_argument("--every", type=float, help="1 sampel tiap S detik (default 15)")
    ap.add_argument("--max-frames", type=int, help="batas maksimal frame sampel per sesi (default 120)")
    ap.add_argument("--rule", choices=["strict", "lenient"])
    ap.add_argument("--conf", type=float, help="ambang kepercayaan deteksi (default 0.3)")
    ap.add_argument("--max-error", type=float, help="batas persen frame error (default 30)")
    ap.add_argument("--cam", type=int, help="nomor kamera (default 0)")
    ap.add_argument("--no-tiles", action="store_true", help="deteksi frame penuh saja (lebih cepat)")
    ap.add_argument("--no-report", action="store_true", help="jangan tulis laporan (hanya cetak ringkasan)")
    ap.add_argument("--cache", action="store_true", help="pakai/simpan cache frame sampel di _cache")
    a = ap.parse_args(argv)

    import zyw_core as core
    hc = get_cfg(core.load_config().get("hand_check"))
    if a.n:
        hc["frames"], hc["sample_every_s"] = a.n, 0
    if a.every is not None:
        hc["sample_every_s"] = a.every
    if a.max_frames:
        hc["max_frames"] = a.max_frames
    if a.rule:
        hc["rule"] = a.rule
    if a.conf:
        hc["conf"] = a.conf
    if a.max_error:
        hc["max_error_pct"] = a.max_error
    if a.cam is not None:
        hc["cam"] = a.cam
    if a.no_tiles:
        hc["tiles"] = False
    if a.no_report:
        hc["report"] = False
    if a.cache:
        hc["use_cache"] = True

    target = os.path.normpath(a.target)
    sessions = [target] if _root_is_session(target) else core.find_session_dirs(target)
    print(f"handcheck - {CREDIT}")
    if not sessions:
        print(f"Tidak ada sesi ditemukan di: {target}")
        return 1
    every = hc["sample_every_s"]
    print(f"{len(sessions)} sesi | sampling {'1 per %g detik (min %d, maks %d)' % (every, hc['min_frames'], hc['max_frames']) if every else '%d frame tetap' % hc['frames']}"
          f" | rule {hc['rule']} | conf {hc['conf']} | tiles {hc['tiles']} | batas {hc['max_error_pct']}%", flush=True)
    items = []
    for sd in sessions:
        m = _read_meta(sd)
        items.append({"path": sd, "name": os.path.basename(sd), "recorder": m.get("recorder", ""),
                      "location": m.get("location", ""), "start": m.get("start", ""), "duration_min": None,
                      "health": "-"})
    t0 = {"t": time.time()}

    def progress(i, n, name):
        t0["t"] = time.time()
        print(f"[{i}/{n}] memproses {name} ...", flush=True)

    def on_entry(e, i, n):
        if e.get("skip"):
            return
        tag = "GAGAL" if (e.get("note") and not (e.get("hand") or {}).get("frames")) else (
            "FLAG " if (e.get("hand") or {}).get("flag") else "ok   ")
        print(f"[{i}/{n}] {tag} {e['name']} ({time.time() - t0['t']:.0f} dtk) "
              f"{e.get('note') or summary_line(e.get('hand'))}", flush=True)

    entries = check_sessions(items, hc, target, progress=progress, on_entry=on_entry)
    # Tutup native MediaPipe task secara eksplisit sebelum interpreter shutdown.
    for detector in list(_DETECTORS.values()):
        try:
            detector.close()
        except Exception:
            pass
    _DETECTORS.clear()
    flagged = sum(1 for e in entries if (e.get("hand") or {}).get("flag"))
    print(f"\nSelesai: {len(entries)} sesi, {flagged} ditandai FLAG.")
    out = output_path(target, entries) if hc["report"] else ""
    if out:
        print(f"Hasil laporan: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())





