"""Configurable, JSON-backed folder naming pipeline for ZYWtool."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
BUILTIN_TIMEZONES = {
    "WIB": "Asia/Jakarta",
    "WITA": "Asia/Makassar",
    "WIT": "Asia/Jayapura",
    "UTC": "UTC",
}
ALLOWED_OPERATIONS = {
    "split", "regex_extract", "replace", "remove", "trim", "collapse_spaces",
    "case", "datetime", "prefix", "suffix",
}
VARIABLE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")


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
    # A top-level list represents multiple records; paths are relative to each record.
    # Nested arrays inside a record still retain their [0] sample path.
    sample = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else data
    fields = _flatten(sample)
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
    """Historical sanitizer retained for built-in tokens and old profiles."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "").strip())


def _safe_component(value):
    """Windows-safe custom value; retain intentional spaces, hyphens and underscores."""
    text = str(value if value is not None else "").strip()
    text = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(" .")


def _timezone(name):
    alias = BUILTIN_TIMEZONES.get(str(name or "").upper(), str(name or "Asia/Jakarta"))
    try:
        return ZoneInfo(alias)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Zona waktu tidak dikenal: {name}") from exc


def _epoch_datetime(value):
    stamp = float(value)
    absolute = abs(stamp)
    if absolute >= 1e14:
        stamp /= 1e6
    elif absolute >= 1e11:
        stamp /= 1e3
    return dt.datetime.fromtimestamp(stamp, tz=dt.timezone.utc)


def _parse_datetime(value, source_timezone="UTC"):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _epoch_datetime(value)
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip()
    if re.fullmatch(r"\d{10}|\d{13}|\d{16}", raw):
        return _epoch_datetime(int(raw))
    parsed = None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = dt.datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"Nilai tanggal tidak dikenali: {raw}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone(source_timezone))
    return parsed


def _date_value(value, session):
    if session is not None and getattr(session, "start", None):
        return session.start.strftime("%Y%m%d")
    try:
        parsed = _parse_datetime(value, "Asia/Jakarta")
        return parsed.astimezone(_timezone("Asia/Jakarta")).strftime("%Y%m%d") if parsed else ""
    except (ValueError, OSError, OverflowError):
        return _safe(value)


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


def _apply_operation(value, operation):
    """Apply one ordered transformation. Disabled operations remain in profiles."""
    if not operation.get("enabled", True):
        return value
    op = str(operation.get("op") or "").lower()
    if op not in ALLOWED_OPERATIONS:
        raise ValueError(f"Operasi transformasi tidak dikenal: {op}")
    if value is None:
        value = ""
    text = str(value)
    if op == "split":
        delimiter = str(operation.get("delimiter", ""))
        if not delimiter:
            raise ValueError("Split membutuhkan delimiter.")
        parts = text.split(delimiter)
        index = int(operation.get("index", 0))
        return parts[index].strip() if -len(parts) <= index < len(parts) else ""
    if op == "regex_extract":
        pattern = str(operation.get("pattern", ""))
        if not pattern:
            raise ValueError("Regex Extract membutuhkan pattern.")
        match = re.search(pattern, text)
        if not match:
            return ""
        group = int(operation.get("group", 1))
        try:
            return match.group(group)
        except IndexError as exc:
            raise ValueError(f"Regex group {group} tidak tersedia.") from exc
    if op == "replace":
        find = str(operation.get("find", ""))
        if not find:
            raise ValueError("Replace membutuhkan teks yang dicari.")
        return text.replace(find, str(operation.get("replace", "")))
    if op == "remove":
        target = str(operation.get("text", ""))
        if not target:
            raise ValueError("Remove membutuhkan teks yang dihapus.")
        return re.sub(target, "", text) if operation.get("regex") else text.replace(target, "")
    if op == "trim":
        chars = str(operation.get("chars", "") or "")
        return text.strip(chars or None)
    if op == "collapse_spaces":
        return " ".join(text.split())
    if op == "case":
        mode = str(operation.get("mode", "upper")).lower()
        if mode == "upper":
            return text.upper()
        if mode == "lower":
            return text.lower()
        if mode == "title":
            return text.title()
        raise ValueError(f"Mode Case tidak dikenal: {mode}")
    if op == "datetime":
        parsed = _parse_datetime(value, operation.get("source_timezone", "UTC"))
        if parsed is None:
            return ""
        target = _timezone(operation.get("timezone", "Asia/Jakarta"))
        fmt = str(operation.get("format", "%Y%m%d"))
        try:
            return parsed.astimezone(target).strftime(fmt)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Format tanggal tidak valid: {fmt}") from exc
    if op == "prefix":
        return str(operation.get("text", "")) + text
    if op == "suffix":
        return text + str(operation.get("text", ""))
    return value


def validate_variables(variables):
    """Validate custom variables before saving or importing a naming profile."""
    if not isinstance(variables, list):
        raise ValueError("Custom variables harus berupa list.")
    names = set()
    for index, variable in enumerate(variables, 1):
        if not isinstance(variable, dict):
            raise ValueError(f"Variable #{index} harus berupa object.")
        name = str(variable.get("name", "")).strip().upper()
        if not VARIABLE_NAME_RE.fullmatch(name):
            raise ValueError(f"Nama variable '{name}' tidak valid.")
        if name in TOKENS:
            raise ValueError(f"Nama {name} sudah dipakai built-in variable.")
        if name in names:
            raise ValueError(f"Nama variable duplikat: {name}")
        names.add(name)
        source = str(variable.get("source", "")).strip()
        if not source:
            raise ValueError(f"Source untuk {name} belum diisi.")
        operations = variable.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError(f"Operations untuk {name} harus berupa list.")
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("op") not in ALLOWED_OPERATIONS:
                raise ValueError(f"Operasi untuk {name} tidak valid.")
    return True


def evaluate_variables(session, cfg):
    """Return built-in and user-defined values, resolving custom dependencies safely."""
    naming_cfg = (cfg or {}).get("naming", {}) or {}
    metadata = getattr(session, "metadata", {}) or {}
    field_map = dict(DEFAULT_FIELD_MAP)
    field_map.update(naming_cfg.get("field_map") or {})
    values = {}
    for token in TOKENS:
        mapped = _read_path(metadata, field_map.get(token, ""))
        derived = _derived_value(token, metadata, session, cfg)
        value = mapped if mapped not in (None, "") else derived
        if token == "DATE":
            use_session_date = mapped in (None, "") or mapped == metadata.get("start_time_unix")
            value = _date_value(value, session if use_session_date else None)
        elif token == "DEVICE_ID" and value:
            match = re.search(r"ZYW\s*0*(\d+)", str(value), re.I)
            if match:
                value = f"ZYW{int(match.group(1)):03d}"
        elif token == "SESSION" and (cfg or {}).get("shift_mode", "enabled") == "none":
            value = ""
        values[token] = _safe(value)

    variables = naming_cfg.get("variables", []) or []
    validate_variables(variables)
    definitions = {str(item["name"]).strip().upper(): item for item in variables}
    resolving = set()

    def resolve(name):
        key = str(name).strip().upper()
        if key in values:
            return values[key]
        if key not in definitions:
            return ""
        if key in resolving:
            raise ValueError(f"Dependency cycle terdeteksi pada variable {key}.")
        resolving.add(key)
        definition = definitions[key]
        if not definition.get("enabled", True):
            result = ""
        else:
            source = str(definition.get("source", "")).strip()
            if source.startswith("var:"):
                result = resolve(source[4:])
            elif source.startswith("builtin:"):
                result = values.get(source[8:].strip().upper(), "")
            elif source.startswith("literal:"):
                result = source[8:]
            else:
                path = source[5:] if source.startswith("json:") else source
                result = _read_path(metadata, path)
            if result in (None, ""):
                result = definition.get("fallback", "")
            for operation in definition.get("operations", []):
                result = _apply_operation(result, operation)
            result = _safe_component(result)
        resolving.remove(key)
        if definition.get("required") and result in (None, ""):
            raise ValueError(f"Variable wajib {key} menghasilkan nilai kosong.")
        values[key] = "" if result is None else str(result)
        return values[key]

    for key in definitions:
        resolve(key)
    return values


def validate_naming_config(config):
    """Validate a naming profile, including templates, variables and operations."""
    if not isinstance(config, dict):
        raise ValueError("Naming profile harus berupa object.")
    template = str(config.get("template") or DEFAULT_TEMPLATE)
    if len(template) > 500:
        raise ValueError("Template nama terlalu panjang.")
    if re.search(r"\{[^{}]*\}", re.sub(r"\{[A-Za-z][A-Za-z0-9_]*\}", "", template)):
        raise ValueError("Template memiliki placeholder yang tidak valid.")
    variables = config.get("variables", []) or []
    validate_variables(variables)
    definitions = {str(item["name"]).strip().upper(): item for item in variables}
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting:
            raise ValueError(f"Dependency cycle terdeteksi pada variable {name}.")
        if name in visited:
            return
        visiting.add(name)
        source = str(definitions[name].get("source", "")).strip()
        if source.startswith("var:"):
            dependency = source[4:].strip().upper()
            if dependency in definitions:
                visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in definitions:
        visit(name)
    for variable in variables:
        for operation in variable.get("operations", []) or []:
            _validate_operation(operation)
    return True


def _validate_operation(operation):
    """Validate operation parameters without needing a real session."""
    op = operation.get("op")
    if op == "split" and not str(operation.get("delimiter", "")):
        raise ValueError("Split membutuhkan delimiter.")
    if op == "regex_extract" and str(operation.get("pattern", "")):
        try:
            re.compile(str(operation["pattern"]))
        except re.error as exc:
            raise ValueError(f"Regex tidak valid: {exc}") from exc
    elif op == "regex_extract":
        raise ValueError("Regex Extract membutuhkan pattern.")
    if op == "replace" and not str(operation.get("find", "")):
        raise ValueError("Replace membutuhkan teks yang dicari.")
    if op == "remove" and not str(operation.get("text", "")):
        raise ValueError("Remove membutuhkan teks yang dihapus.")
    if op == "datetime":
        _timezone(operation.get("timezone", "Asia/Jakarta"))
        _timezone(operation.get("source_timezone", "UTC"))
        fmt = str(operation.get("format", "%Y%m%d"))
        try:
            dt.datetime(2000, 1, 2, 3, 4, 5).strftime(fmt)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Format tanggal tidak valid: {fmt}") from exc


def build_folder_name(session, cfg):
    """Build a safe group name from built-in tokens plus dynamic custom variables."""
    naming_cfg = (cfg or {}).get("naming", {}) or {}
    template = str(naming_cfg.get("template") or DEFAULT_TEMPLATE)
    values = evaluate_variables(session, cfg)

    def substitute(match):
        name = match.group(1).upper()
        if name not in values:
            raise ValueError(f"Variable {{{name}}} belum dibuat atau tidak tersedia.")
        return values[name]

    result = re.sub(r"\{([A-Za-z][A-Za-z0-9_]*)\}", substitute, template)
    result = re.sub(r"([_ .-]){2,}", r"\1", result)
    result = re.sub(r"[_ .-]+$", "", result)
    result = re.sub(r"^[_ .-]+", "", result)
    result = re.sub(r"[_ .-]{2,}", "_", result)
    result = result.rstrip(" .")
    if not result:
        raise ValueError("Template nama folder menghasilkan nama kosong.")
    if len(result) > 180:
        raise ValueError("Nama folder melebihi 180 karakter.")
    if result.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                          *(f"LPT{i}" for i in range(1, 10))}:
        result = "_" + result
    if any(char in result for char in '<>:"/\\|?*') or any(ord(char) < 32 for char in result):
        raise ValueError("Nama folder mengandung karakter yang tidak didukung Windows.")
    return result
