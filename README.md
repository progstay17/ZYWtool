# ZYWtool

**Recording Operations Toolkit** - desktop utility for reviewing MCAP recording sessions, checking recording integrity, organizing session folders, and preparing operational Excel reports.

> ZYWtool is designed for an internal recording-operations workflow. Review generated flags and reports before making operational decisions. The hand-check feature is probabilistic and supports manual review; it does not replace it.

## Features

- **MCAP session scanning** - discovers session folders and reads MCAP metadata.
- **Recording health checks** - checks MCAP file validity and reports session duration and statistics.
- **Session explorer** - presents discovered sessions in a desktop dashboard.
- **Shift and activity mapping** - maps sessions to configured time shifts and activity labels.
- **Excel reporting** - exports the operational recap workbook, including the ZY White and Cek File worksheets.
- **Folder tools** - organizes/copies session folders to a configured destination.
- **Optional hand check** - uses MediaPipe Hand Landmarker to sample frames and flag sessions for manual review.
- **HTML hand-check reports** - can produce per-session and group reports with supporting thumbnails.
- **Session footage preview** - creates up to 30 evenly spaced timeline snapshots per session, independent of video FPS. Preview timestamps avoid Hand Check sample points on the same camera and show each frame's session percentage and timestamp.
- **Background jobs** - manages long-running operations separately from the main GUI.
- **Arrange undo utility** - undo_arrange.py provides a guarded workflow to inspect and reverse supported arrange operations.

## Requirements

### Packaged Windows application

Use the Windows portable release supplied with this project. It bundles Python runtime dependencies. The MediaPipe Hand Landmarker model is downloaded automatically and checksum-verified the first time Hand Check is used. Extract the release ZIP before running the installer.

### Run from source

- Windows 10/11 (the GUI uses Tkinter; other platforms may require additional setup).
- Python version compatible with the pinned dependencies in requirements.txt.

Install dependencies: python -m pip install -r requirements.txt

Run the application: python zywtool.py

Optional command-line tools:
- python handcheck.py "D:\recordings"
- python preview_frames.py "D:\recordings" --n 30 --cam 0
- python undo_arrange.py --help

## Install the Windows portable release

1. Extract ZYWtool-Windows-Portable.zip.
2. Keep install.ps1 and the ZYWtool folder together.
3. Open PowerShell in the extracted directory.
4. Run: powershell -ExecutionPolicy Bypass -File .\install.ps1
5. Launch ZYWtool from the Desktop shortcut.
6. Open Preferences and configure the source folder, workbook path, and organized output folder before processing data.

The installer copies application files only. It does not bundle operational workbooks, recordings, reference datasets, reports, the MediaPipe model, or user-specific configuration. The model is downloaded on first Hand Check use and cached under %LOCALAPPDATA%\ZYWtool\models. An internet connection is required for that first download.

## Configuration and data locations

When running from source, zyw_config.json is read from the project directory.

In the packaged Windows build, user configuration is stored separately at:

    %APPDATA%\ZYWtool\zyw_config.json

zyw_config.example.json is a sanitized template. Set the following values in the app's Preferences:

- data_root - source directory containing recording sessions.
- excel_path - path to the operational Excel workbook.
- organized_root - destination for organized/copied session folders.
- shifts - configured shift start/end times, display labels, and shift identifiers.
- activities - canonical activity labels and aliases.
- hand_check - optional MediaPipe sampling and reporting settings.

Do not commit a real zyw_config.json, operational workbook, or private filesystem paths to a public repository.

## Hand-check modes

The optional hand-check feature supports two rules:

- **Strict** - a sampled frame is treated as an error when the detected hand count is not exactly two, or a detected hand point lies outside the frame.
- **Lenient** - a sampled frame is treated as an error when no hands or more than two hands are detected, or a detected hand point lies outside the frame.

A session is flagged when its sampled-frame error percentage exceeds the configured threshold. Detection depends on frame sampling and model confidence; inspect the generated report and source footage before drawing conclusions.

## Data safety

- Keep the original operational workbook and source recordings outside the application installation directory.
- Back up the workbook and source data before bulk operations.
- Review source and destination paths before organizing folders.
- Treat delete, overwrite, and undo operations as potentially destructive; inspect the plan and confirmation prompts.
- Generated previews, logs, caches, reports, and test fixtures may contain private operational information. Keep them out of public source control.
- The uninstall script removes the installed application and its Desktop shortcut. It intentionally preserves %APPDATA%\ZYWtool and external workbook/data folders.

## Development and tests

Core modules:

| File | Responsibility |
|---|---|
| zywtool.py | Tkinter desktop application |
| zyw_core.py | MCAP scanning, session logic, configuration, Excel and folder operations |
| handcheck.py | MediaPipe-based optional hand check and HTML reporting |
| handreport.py | Hand-check report generation |
| preview_frames.py | Time-based footage preview, offset from Hand Check sample points |
| jobs.py | Background job management |
| undo_arrange.py | Guarded arrange undo utility |

Automated test runners are maintained separately from this public source snapshot. Do not run internal test scripts against production data or the original workbook.

Compile-check Python modules:
python -m compileall -q handcheck.py handreport.py jobs.py preview_frames.py zywtool.py zyw_core.py undo_arrange.py

Build the portable Windows application on Windows:
.\build_portable.ps1

## Known limitations

- MediaPipe hand detection is probabilistic and may produce false positives or false negatives.
- The hand-check report is a review aid, not an automatic acceptance/rejection decision.
- Processing time depends on video codec, resolution, session length, hardware, and sampling settings.
- Shift labels and operational workbook conventions are workflow-specific; confirm them with the process owner before changing them.
- The portable executable should be tested on a clean Windows machine before broad deployment.

## Privacy

This application may process recording metadata, recorder identifiers, operational workbook data, file paths, logs, and report thumbnails. Do not publish real operational datasets, screenshots, reports, logs, model caches, credentials, or personal information. Use synthetic fixtures for demonstrations and public issue reports.

## License

The ZYWtool source code is licensed under the MIT License (see LICENSE). The separately downloaded MediaPipe model is a third-party asset under Apache License 2.0; see MODEL.md and THIRD_PARTY_NOTICES.md.

