"""Preview frame per sesi: ambil maksimum N frame yang tersebar merata berdasarkan waktu session, hindari timestamp sampel Hand Check, lalu susun jadi contact sheet PNG.
Output: C:/ZYWtool/preview/<folder grup>/<session>_cam<N>.png
Pakai: python preview_frames.py <folder root atau folder sesi> [--n 30] [--cam 0] [--cam 0,1]
"""
import glob
import math
import os
import sys

import av
from PIL import Image, ImageDraw
from mcap.reader import make_reader

HERE = (os.environ.get("ZYWTOOL_HOME") or
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
from zyw_core import find_session_dirs  # noqa: E402

OUT_ROOT = os.path.join(HERE, "preview")
THUMB_W, THUMB_H, LABEL_H, COLS = 360, 203, 22, 4


def _varint(b, i):
    shift = result = 0
    while True:
        byte = b[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, i
        shift += 7


def parse_proto(b):
    """Parser protobuf minimal untuk foxglove.CompressedVideo: 1=timestamp, 2=frame_id, 3=data, 4=format."""
    i, out = 0, {}
    while i < len(b):
        key, i = _varint(b, i)
        fn, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
            out.setdefault(fn, []).append(v)
        elif wt == 2:
            n, i = _varint(b, i)
            out.setdefault(fn, []).append(b[i:i + n])
            i += n
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        else:
            break
    return out


def is_keyframe(data, fmt):
    b = bytes(data)
    i = 0
    while True:
        p = b.find(b"\x00\x00\x01", i)
        if p < 0 or p + 3 >= len(b):
            return False
        byte = b[p + 3]
        if fmt == "h265":
            t = (byte >> 1) & 0x3F
            if 16 <= t <= 21:
                return True
        elif byte & 0x1F == 5:
            return True
        i = p + 3


def topic_count(path, topic):
    with open(path, "rb") as f:
        summ = make_reader(f).get_summary()
    if summ is None or summ.statistics is None:
        return None
    for cid, ch in summ.channels.items():
        if ch.topic == topic:
            return summ.statistics.channel_message_counts.get(cid, 0)
    return 0


def decode_last(packets, fmt):
    """Decode dari keyframe sampai paket terakhir; kembalikan frame terakhir (atau None)."""
    ctx = av.CodecContext.create("hevc" if fmt == "h265" else "h264", "r")
    last = None
    for data in packets:
        for fr in ctx.decode(av.Packet(data)):
            last = fr
    for fr in ctx.decode(None):
        last = fr
    return last


def frame_at(path, topic, t_target):
    """Ambil frame di waktu t_target (ns). Hanya membaca jendela 3 dtk sebelumnya (pakai index mcap),
    decode dari keyframe pertama di jendela itu. Kembalikan (frame PIL, log_time) atau (None, None)."""
    lo = max(0, t_target - 3_000_000_000)
    with open(path, "rb") as fh:
        msgs = [m for _, _, m in make_reader(fh).iter_messages(
            topics=[topic], starting_at=lo, ending_at=t_target)]
    if not msgs:
        return None, None
    parsed = []
    for m in msgs:
        p = parse_proto(m.data)
        parsed.append((p.get(3, [b""])[0], p.get(4, [b""])[0].decode("utf-8", "replace")))
    key = next((i for i, (d, f) in enumerate(parsed) if is_keyframe(d, f)), None)
    if key is None:
        return None, None
    fr = decode_last([d for d, _ in parsed[key:]], parsed[-1][1])
    if fr is None:
        return None, None
    return fr.to_image(), msgs[-1].log_time


def _handcheck_blocked_intervals(infos, cam):
    """Rentang waktu sampel Hand Check agar Preview tidak mengambil frame yang sama."""
    try:
        import handcheck
        cfg = core.load_config()
        hc = handcheck.get_cfg(cfg.get("hand_check", {}))
        if int(hc.get("cam", 0)) != int(cam):
            return []
        total = sum(i[1] for i in infos)
        duration = sum((i[3] - i[2]) / 1e9 for i in infos if i[1] > 0)
        if total <= 0 or duration <= 0:
            return []
        n = min(handcheck.choose_n(duration, hc), total)
    except Exception as exc:
        print(f"  konfigurasi Hand Check tidak terbaca; gunakan jarak aman default: {exc}", flush=True)
        total = sum(i[1] for i in infos)
        n = min(20, total)
        if total <= 0 or n <= 0:
            return []

    targets = sorted({int((k + 0.5) * total / n) for k in range(n)})
    blocked, base, ti = [], 0, 0
    for _path, cnt, st, en in infos:
        while ti < len(targets) and targets[ti] < base + cnt:
            local = targets[ti] - base
            t_target = int(st + (local / cnt) * (en - st))
            # Frame Hand Check yang didecode dapat berada sedikit sebelum target.
            # Margin dua interval frame menghindari pemilihan ulang gambar yang sama.
            frame_step = max(1, int((en - st) / max(cnt, 1)))
            margin = max(50_000_000, frame_step * 2)
            blocked.append((t_target - margin, t_target + margin))
            ti += 1
        base += cnt
    return blocked


def _distance_from_blocked(t, blocked):
    if not blocked:
        return float("inf")
    best = float("inf")
    for lo, hi in blocked:
        if lo <= t <= hi:
            return 0
        best = min(best, lo - t if t < lo else t - hi)
    return best


def _even_timeline_targets(start_ns, end_ns, n, blocked):
    """Pilih satu titik waktu per bin timeline, sejauh mungkin dari sampel Hand Check."""
    if n <= 0 or end_ns <= start_ns:
        return []
    span = end_ns - start_ns
    chosen = []
    for slot in range(n):
        lo = start_ns + span * slot / n
        hi = start_ns + span * (slot + 1) / n
        width = hi - lo
        mid = (lo + hi) / 2
        intervals = [(max(lo, a), min(hi, b)) for a, b in blocked if b >= lo and a <= hi]
        intervals.sort()
        merged = []
        for a, b in intervals:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        points = [lo] + [v for pair in merged for v in pair] + [hi]
        candidates = {
            int(lo + width * frac) for frac in (0.10, 0.25, 0.50, 0.75, 0.90)
        }
        for a, b in zip(points, points[1:]):
            if b > a:
                candidates.add(int((a + b) / 2))
        candidates = [t for t in candidates if lo <= t <= hi]
        if not candidates:
            continue
        best = max(candidates, key=lambda t: (
            _distance_from_blocked(t, blocked),
            -abs(t - mid)
        ))
        chosen.append(int(best))
    return chosen


def sample_session(sess_dir, n, cam):
    """Ambil maksimum N frame yang merata berdasarkan waktu, bukan jumlah frame/FPS."""
    topic = f"/ego/camera/{cam}"
    files = sorted(glob.glob(os.path.join(sess_dir, "ego_*.mcap")))
    infos = []
    for f in files:
        try:
            with open(f, "rb") as fh:
                summ = make_reader(fh).get_summary()
            if summ is None or summ.statistics is None:
                raise ValueError("summary tidak terbaca")
            cid = [c for c, ch in summ.channels.items() if ch.topic == topic]
            cnt = summ.statistics.channel_message_counts.get(cid[0], 0) if cid else 0
            if cnt:
                infos.append((f, cnt, summ.statistics.message_start_time, summ.statistics.message_end_time))
        except Exception as e:
            print(f"  lewati {os.path.basename(f)}: {type(e).__name__}: {e}", flush=True)

    total = sum(i[1] for i in infos)
    if total == 0 or n <= 0:
        return []
    session_start = min(i[2] for i in infos)
    session_end = max(i[3] for i in infos)
    if session_end <= session_start:
        return []

    # Gunakan konfigurasi Hand Check yang benar-benar aktif. Sampelnya tidak disentuh
    # dan tidak dihitung ulang; Preview hanya menjauhi timestamp tersebut.
    blocked = _handcheck_blocked_intervals(infos, cam)
    targets = _even_timeline_targets(session_start, session_end, min(int(n), total), blocked)

    results, seen = [], set()
    for slot, t_target in enumerate(targets, 1):
        # Jika ada jeda antarfail MCAP, gunakan file dengan waktu terdekat lalu clamp.
        path, _cnt, st, en = min(
            infos,
            key=lambda item: 0 if item[2] <= t_target <= item[3]
            else min(abs(t_target - item[2]), abs(t_target - item[3]))
        )
        read_at = min(max(t_target, st), en)
        try:
            img, log_time = frame_at(path, topic, read_at)
        except Exception as e:
            print(f"  preview titik {slot} dilewati: {type(e).__name__}: {e}", flush=True)
            img, log_time = None, None
        if img is None or log_time is None or log_time in seen:
            continue
        seen.add(log_time)
        elapsed = max(0.0, (log_time - session_start) / 1e9)
        percent = min(100.0, max(0.0, 100.0 * (log_time - session_start) / (session_end - session_start)))
        results.append((slot, elapsed, percent, img))

    if len(results) < len(targets):
        print(f"  catatan: {len(results)}/{len(targets)} titik berhasil didecode (sebagian berdekatan dengan batas/jeda file)", flush=True)
    return results

def contact_sheet(frames, title):
    rows = math.ceil(len(frames) / COLS)
    sheet = Image.new("RGB", (COLS * THUMB_W + 10, rows * (THUMB_H + LABEL_H) + 30), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    draw.text((6, 6), title, fill=(230, 230, 230))
    for k, (idx, t, pct, img) in enumerate(frames):
        r, c = divmod(k, COLS)
        x, y = c * THUMB_W + 5, 30 + r * (THUMB_H + LABEL_H)
        sheet.paste(img.resize((THUMB_W, THUMB_H)), (x, y + LABEL_H))
        mm, ss = divmod(int(t), 60)
        draw.text((x + 4, y + 5), f"P{idx:02d}  {pct:05.1f}%  {mm:02d}:{ss:02d}", fill=(255, 255, 255))
    return sheet


def preview_session(sess_dir, n=30, cams=(0,)):
    group = os.path.basename(os.path.dirname(sess_dir))
    name = os.path.basename(sess_dir)
    written = []
    for cam in cams:
        frames = sample_session(sess_dir, n, cam)
        if not frames:
            continue
        out_dir = os.path.join(OUT_ROOT, group)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"{name}_cam{cam}.png")
        contact_sheet(frames, f"{group} | {name} | camera {cam}").save(out)
        written.append(out)
    return written


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 1
    target = args[0]
    n, cams = 30, (0,)
    if "--n" in args:
        n = int(args[args.index("--n") + 1])
    if "--cam" in args:
        cams = tuple(int(x) for x in args[args.index("--cam") + 1].split(","))
    if os.path.isfile(os.path.join(target, "session.json")):
        sessions = [target]
    else:
        sessions = find_session_dirs(target)
    print(f"{len(sessions)} sesi, maksimum {n} titik timeline per sesi, kamera {cams}")
    for sd in sessions:
        try:
            outs = preview_session(sd, n, cams)
            print("OK  ", os.path.basename(sd), "->", outs)
        except Exception as e:
            print("GAGAL", os.path.basename(sd), type(e).__name__, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
