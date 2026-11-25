"""Portable, path-safe export/import for ZYWtool presets."""
from __future__ import annotations

import json
import os

import naming

FORMAT_ID = "zywtool.preset"
FORMAT_VERSION = 1
PRESET_KEYS = (
    "shift_mode", "shifts", "check_mode", "qc", "supervisor",
    "activities", "hand_check", "naming",
)


def _portable_config(config):
    if not isinstance(config, dict):
        raise ValueError("Preset harus berupa object JSON.")
    result = {key: config[key] for key in PRESET_KEYS if key in config}
    if "naming" in result:
        result["naming"] = json.loads(json.dumps(result["naming"], ensure_ascii=False))
        # Do not leak machine-specific paths in exported files.
        result["naming"]["source_json"] = ""
        naming.validate_naming_config(result["naming"])
    return result


def export_preset_file(path, name, config):
    """Write a portable preset atomically; paths and data locations are never exported."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("Nama preset belum diisi.")
    payload = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "name": name,
        "config": _portable_config(config),
    }
    target = os.path.abspath(os.path.expanduser(str(path)))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temporary = target + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
    return target


def import_preset_file(path):
    """Read and validate a portable preset without applying it or touching local paths."""
    target = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isfile(target):
        raise ValueError("File preset tidak ditemukan.")
    if os.path.getsize(target) > 2 * 1024 * 1024:
        raise ValueError("Ukuran preset melebihi batas 2 MB.")
    try:
        with open(target, "r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Preset tidak bisa dibaca: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != FORMAT_ID:
        raise ValueError("Format file bukan preset ZYWTool.")
    if payload.get("version") != FORMAT_VERSION:
        raise ValueError(f"Versi preset tidak didukung: {payload.get('version')}")
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 80:
        raise ValueError("Nama preset tidak valid.")
    config = _portable_config(payload.get("config"))
    if "naming" not in config:
        raise ValueError("Preset tidak memiliki konfigurasi Naming Convention.")
    return name, config
