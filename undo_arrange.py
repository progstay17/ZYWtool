"""Undo folder arrangement using a ZYWtool logs/arrange_*.json file.
Fadhil Ghifarion 法迪 for AIT

Usage: python undo_arrange.py <arrange-log.json> --root <original-recording-root>
The command validates every move and asks for confirmation before changing folders.
The arranged destination may be outside the original recording root.
"""
import argparse
import datetime as dt
import json
import os
import sys

CREDIT = "Fadhil Ghifarion 法迪 for AIT"
HERE = os.path.dirname(os.path.abspath(__file__))


def _inside(root, path):
    # Windows temp paths may mix 8.3 aliases (RUNNER~1) and long names.
    # Canonicalize both sides before checking containment.
    try:
        root = os.path.normcase(os.path.realpath(os.path.abspath(root)))
        path = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        return os.path.commonpath((root, path)) == root
    except (OSError, ValueError):
        return False


def prepare_undo(log_path, root):
    """Validate an arrange log; --root membatasi asal rekaman, tujuan boleh di luar root."""
    root = os.path.realpath(os.path.abspath(root))
    if not os.path.isdir(root):
        raise ValueError(f"Folder root tidak ditemukan: {root}")
    log_path = os.path.abspath(log_path)
    with open(log_path, encoding="utf-8") as f:
        records = json.load(f)
    if not isinstance(records, list) or not records:
        raise ValueError("Log arrange kosong atau formatnya tidak valid.")
    moves, seen_src, seen_dst = [], set(), set()
    for i, item in enumerate(records, 1):
        if not isinstance(item, dict) or not isinstance(item.get("from"), str) or not isinstance(item.get("to"), str):
            raise ValueError(f"Entri log #{i} tidak memiliki from/to yang valid.")
        original = os.path.abspath(item["from"])
        arranged = os.path.abspath(item["to"])
        name = os.path.basename(original)
        if not name.startswith("session_") or os.path.basename(arranged) != name:
            raise ValueError(f"Entri log #{i} bukan perpindahan folder sesi yang valid.")
        # --root membatasi folder asal rekaman. Tujuan arrange boleh berada
        # di direktori output terpisah sesuai Preferences.
        if not _inside(root, original):
            raise ValueError(f"Entri log #{i}: folder asal berada di luar --root.")
        if os.path.islink(arranged) or os.path.islink(os.path.dirname(arranged)):
            raise ValueError(f"Entri log #{i} melewati symbolic link; dibatalkan.")
        if arranged in seen_src or original in seen_dst:
            raise ValueError("Log berisi perpindahan duplikat; dibatalkan.")
        seen_src.add(arranged); seen_dst.add(original)
        if not os.path.isdir(arranged):
            raise FileNotFoundError(f"Folder hasil arrange tidak ditemukan: {arranged}")
        if os.path.lexists(original):
            raise FileExistsError(f"Tujuan asal sudah ada, tidak akan ditimpa: {original}")
        moves.append((arranged, original))
    return list(reversed(moves))


def execute_undo(moves, root):
    """Apply prevalidated moves and write an undo receipt; never overwrite existing folders."""
    root = os.path.realpath(os.path.abspath(root))
    completed = []
    try:
        for source, destination in moves:
            # Source adalah lokasi hasil arrange dan boleh berada di luar --root.
            # Destination wajib kembali ke root rekaman yang sudah divalidasi.
            if not _inside(root, destination):
                raise ValueError("Path tujuan berubah ke luar --root setelah validasi.")
            if not os.path.isdir(source) or os.path.lexists(destination):
                raise FileExistsError(f"Kondisi folder berubah; tidak dipindahkan: {source} -> {destination}")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            import shutil
            shutil.move(source, destination)
            completed.append({"from": source, "to": destination})
    finally:
        if completed:
            log_dir = os.path.join(HERE, "logs")
            os.makedirs(log_dir, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            receipt = os.path.join(log_dir, f"undo_{stamp}.json")
            tmp = receipt + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"root": root, "moved": completed, "credit": CREDIT}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, receipt)
    return completed


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Undo pemindahan folder ZYWtool dari logs/arrange_*.json")
    ap.add_argument("log", help="path ke logs/arrange_*.json")
    ap.add_argument("--root", required=True, help="folder root rekaman yang menjadi batas aman undo")
    ap.add_argument("--yes", action="store_true", help="lewati prompt konfirmasi (gunakan dengan hati-hati)")
    ap.add_argument("--dry-run", action="store_true", help="validasi dan tampilkan rencana tanpa memindahkan folder")
    args = ap.parse_args(argv)
    try:
        moves = prepare_undo(args.log, args.root)
        print(f"ZYWtool Undo - {CREDIT}")
        print(f"Log: {os.path.abspath(args.log)}")
        print(f"Akan mengembalikan {len(moves)} folder sesi:")
        for source, destination in moves:
            print(f"  {source} -> {destination}")
        if args.dry_run:
            print("DRY RUN: tidak ada folder yang dipindahkan.")
            return 0
        if not args.yes:
            answer = input("Lanjutkan undo? Ketik YA untuk mengonfirmasi: ").strip()
            if answer != "YA":
                print("Dibatalkan; tidak ada perubahan.")
                return 2
        completed = execute_undo(moves, args.root)
        print(f"UNDO SELESAI: {len(completed)} folder dikembalikan.")
        print("Bukti undo tersimpan di logs/undo_*.json")
        return 0
    except Exception as e:
        print(f"UNDO GAGAL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

