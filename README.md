# ZYWtool

**Version: 1.0.4**

Recording Operations Toolkit for reviewing MCAP recording sessions, checking recording integrity, organizing session folders, and preparing operational Excel reports.

## Features

- Deep discovery of session_* folders at arbitrary nesting depth; sessions with MCAP files remain visible even when session.json is missing or invalid.
- Recursive MCAP discovery within each session folder.
- Excel Scan Audit worksheet with per-session metadata, MCAP counts, parse counts, duration, storage, errors and warnings.
- Complete recursive folder-size accounting.
- Recording health checks, session explorer, shift/activity mapping and Excel recap.
- Arrange folders and Undo Arrange directly from the GUI. Undo validates paths and refuses unsafe overwrites.
- Optional MediaPipe Hand Check and HTML reports; up to 30 timeline snapshots in Preview.
- Background job management.

## Windows portable release

The portable ZIP bundles the Python runtime and pinned Python application dependencies. No separate Python installation or pip install is required on the target PC.

1. Extract ZYWtool-Windows-Portable.zip.
2. Keep install.ps1 and the ZYWtool folder together.
3. Run PowerShell and execute: powershell -ExecutionPolicy Bypass -File .\\install.ps1
4. Installer checks Microsoft Visual C++ Redistributable x64 and installs it automatically if missing (winget or Microsoft-signed official installer).
5. Launch from the Desktop shortcut and configure paths in Preferences.

The MediaPipe Hand Landmarker model is downloaded automatically and SHA-256 verified on first Hand Check use. Internet is required for that first download.

## Run from source

Windows 10/11; Python 3.12 recommended. Install with python -m pip install -r requirements.txt, then run python zywtool.py.

## Data safety

Keep operational workbooks and source recordings outside the application directory. Back up source data before bulk operations. Do not commit real configuration, workbooks, recordings, logs, reports, model caches or private paths. Sessions missing valid start metadata remain visible in Scan Audit but cannot safely populate date-dependent actual rows.

## Development

Run python -m pytest tests -q. Tests use temporary directories and synthetic files only. Build with .\\build_portable.ps1; the script provisions an isolated Python 3.12 environment, installs pinned dependencies, builds the Windows one-folder executable and packages release\\ZYWtool-Windows-Portable.zip. GitHub Actions runs compilation, tests and lint on the new recorder-discovery tests.

Source code is MIT licensed. The MediaPipe model is a third-party asset under Apache License 2.0; see MODEL.md and THIRD_PARTY_NOTICES.md.
