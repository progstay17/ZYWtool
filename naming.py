"""JSON-backed folder naming helpers for ZYWtool Preferences."""
from __future__ import annotations

import datetime as dt
import json
import os
import re

DEFAULT_TEMPLATE = "{DATE}_{LOCATION_CODE}_{PERSON_NAME}_{DEVICE_ID}_{SESSION}_{ACTIVITY}"
TOKENS = ("DATE", "LOCATION_CODE", "PERSON_NAME", "DEVICE_ID", "SESSION", "ACTIVITY")
DEFAULT_FIELD_MAP = {
    "DATE": "start_time_unix",
    "LOCATION_CODE": "location",
    "PERSON_NAME": "capturer",
    "DEVICE_ID": "task",
    "SESSION": "",
    "ACTIVITY": "",
}


def _flatten(value, prefix=""):
    """Return JSON paths and representative values, including nested objects/arrays."""
    found = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.update(_flatten(child, path))
    elif isinstance(value, list):
        if value:
            path = f"{prefix}[0]"
            found.update(_flatten(value[0], path))
        else:
            found[prefix] = []
    else:
        found[prefix] = value
    return found


def scan_json_file(path):
    """Read a selected JSON file and report every discoverable leaf path."""
    path = os.path.abspath(os.path.expanduser(os.path.expandvars(str(path or ""))))
    if not path or not os.path.isfile(path):
        raise ValueError("Pilih file JSON yang tersedia terlebih dahulu.")
    if os.path.getsize(path) > 25 * 1024 * 1024:
        raise ValueError("File JSON terlalu besar (batas scanner 25 MB).")
    try:
        with open(path, "r", encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON tidak bisa dibaca: {exc}") from exc
    if not isinstance(data, (dict, list)):
        raise ValueError("JSON harus berupa object atau array.")
    fields = _flatten(data)
    if not fields:
        raise ValueError("Tidak ditemukan field di dalam JSON.")
    return [{"path": key, "sample": value, "type": type(value).__name__}
            for key, value in fields.items() if key]


def _read_path(data, path):
    if not path:
        return None
    current = data
    parts = [part for part in str(path).replace("[", ".").replace("]", "").split(".") if part]
    for part in parts:
        if part.isdigit():
            if not isinstance(current, list) or int(part) >= len(current):
                return None
            current = current[int(part)]
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        if current is None:
            return None
    return current


def _safe(value):
    value = str(value or "").strip()
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"_+", "_", value).strip(" ._")
    return value


def _date_value(value, session):
    if session is not None and getattr(session, "start", None):
        return session.start.strftime("%Y%m%d")
    if isinstance(value, (int, float)):
        try:
            stamp = float(value)
            if stamp > 10**12:
                stamp /= 1e6 if stamp > 10**14 else 1e3
            return dt.datetime.fromtimestamp(stamp).strftime("%Y%m%d")
        except (ValueError, OSError, OverflowError):
            return ""
    if value:
        raw = str(value).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 8:
            return digits[:8]
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y%m%d")
        except ValueError:
            return _safe(raw)
    return ""


def _derived_value(token, metadata, session, cfg):
    task = str(metadata.get("task") or getattr(session, "task", "") or "")
    if token == "DATE":
        return _date_value(metadata.get("start_time_unix"), session)
    if token == "LOCATION_CODE":
        return metadata.get("location") or getattr(session, "location", "")
    if token == "PERSON_NAME":
        return metadata.get("capturer") or getattr(session, "capturer", "")
    if token == "DEVICE_ID":
        device_no = getattr(session, "device_no", "")
        if device_no:
            return device_no
        match = re.search(r"ZYW\s*0*(\d+)", task, re.I)
        return f"ZYW{int(match.group(1)):03d}" if match else metadata.get("device_id", "")
    if token == "ACTIVITY":
        activity = getattr(session, "activity", "")
        if activity:
            return activity
        if metadata.get("activity"):
            return metadata["activity"]
        cleaned = re.sub(r"(?i)\bcleaning\b", "", task)
        cleaned = re.sub(r"(?i)\bZYW\s*\d+\b", "", cleaned)
        cleaned = re.sub(r"\(\s*\d+\s*\)", "", cleaned)
        return " ".join(cleaned.split())
    if token == "SESSION":
        if (cfg or {}).get("shift_mode", "enabled") == "none":
            return ""
        shifts = (cfg or {}).get("shifts", [])
        label = getattr(session, "shift", "")
        for item in shifts:
            if len(item) > 3 and str(item[2]) == str(label):
                return f"S{int(item[3])}"
        return ""
    return ""


def build_folder_name(session, cfg):
    """Build a safe group name from a customizable token template."""
    naming = (cfg or {}).get("naming", {}) or {}
    template = str(naming.get("template") or DEFAULT_TEMPLATE)
    field_map = dict(DEFAULT_FIELD_MAP)
    field_map.update(naming.get("field_map") or {})
    metadata = getattr(session, "metadata", {}) or {}
    values = {}
    for token in TOKENS:
        mapped = _read_path(metadata, field_map.get(token, ""))
        derived = _derived_value(token, metadata, session, cfg)
        value = mapped if mapped not in (None, "") else derived
        if token == "DATE":
            value = _date_value(value, None if mapped not in (None, "") else session)
        elif token == "DEVICE_ID" and value:
            match = re.search(r"ZYW\s*0*(\d+)", str(value), re.I)
            if match:
                value = f"ZYW{int(match.group(1)):03d}"
        elif token == "SESSION" and (cfg or {}).get("shift_mode", "enabled") == "none":
            value = ""
        values[token] = _safe(value)

    # Remove a token and its adjacent separator cleanly when it is unavailable,
    # especially SESSION in No Shift mode.
    result = template
    for token, value in values.items():
        result = result.replace("{" + token + "}", value)
    result = re.sub(r"([_ .-]){2,}", r"\1", result)
    result = re.sub(r"[_ .-]+$", "", result)
    result = re.sub(r"^[_ .-]+", "", result)
    result = re.sub(r"[_ .-]{2,}", "_", result)
    if not result:
        raise ValueError("Template nama folder menghasilkan nama kosong.")
    if len(result) > 180:
        raise ValueError("Nama folder melebihi 180 karakter.")
    return result
