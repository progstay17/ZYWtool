# ZYWtool

<p align="center">
  <strong>Recording Operations Toolkit</strong><br>
  <sub>Discover · Inspect · Organize · Verify · Report</sub>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-1.0.6-2563eb">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11-0f766e">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776ab">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-16a34a">
</p>

ZYWtool is a desktop toolkit for recording operations teams working with MCAP sessions. It brings session discovery, recording checks, folder organization, visual review and Excel reporting into one practical Windows application.

**Built for real-world recording folders:** nested sessions, incomplete metadata and large collections should be inspected transparently—not silently disappear from the workflow.

---

## At a glance

| Workflow | What it does |
| --- | --- |
| **Discover** | Finds nested `session_*` folders and MCAP files recursively. |
| **Audit** | Shows metadata, MCAP counts, parse results, duration, storage, warnings and errors in the Excel Scan Audit sheet. |
| **Review** | Explores sessions, checks recording health and previews timeline snapshots. |
| **Organize** | Arranges session folders and provides a guarded Undo Arrange workflow. |
| **Report** | Produces operational Excel recaps and optional Hand Check HTML reports. |

## Highlights

- **Resilient session discovery** — a session containing MCAP data remains discoverable even when `session.json` is missing or invalid.
- **Recursive MCAP scanning** — nested MCAP files are included in discovery and individual read/parse failures are isolated.
- **Transparent scan audit** — partial results, missing metadata, warnings and errors are surfaced instead of being hidden.
- **Storage accounting** — folder sizes are calculated recursively.
- **Operational recap** — session explorer, shift/activity mapping, recording health checks and Excel export.
- **Safer file operations** — Arrange and Undo Arrange are available in the GUI; undo validates paths and refuses unsafe overwrites.
- **Visual inspection** — optional MediaPipe Hand Check, HTML reports and up to 30 timeline snapshots in Preview.
- **Background jobs** — long-running tasks are managed without blocking the main interface.

## Get started — Windows portable

The portable package includes the Python runtime and pinned application dependencies. **You do not need to install Python, run pip, or open PowerShell to use ZYWtool.**

1. Download **ZYWtool-Windows-Portable.zip** from the [latest release](https://github.com/progstay17/ZYWtool/releases/latest).
2. Extract the ZIP to a folder where you have write access.
3. Open the extracted `ZYWtool` folder and double-click **`ZYWtool.exe`**.
4. On first launch, complete **Initial Setup** by choosing the output folders described below.
5. Start scanning your recording root.

### First-run folder setup

A fresh installation intentionally has **no preselected output directories**. This avoids writing reports or workbooks into an unexpected location.

| Setup field | Used for |
| --- | --- |
| **Excel** | The folder where the operational workbook is created or updated. |
| **Preview** | Timeline preview images and related output. |
| **Hand Check** | Hand Check reports and output files. |
| **Organized folders** | Destination for the Arrange operation. |

Choose an existing folder or enter a new destination path. ZYWtool creates missing output folders and checks that each destination is writable before saving Preferences. You can change these locations later in **Preferences**.

> **Tip:** Keep source recordings separate from output folders. For Arrange, choose a destination that will not overwrite or mix with your original recording data.

### No installer or administrator permission required

The portable release is self-contained: extract the ZIP and run ZYWtool/ZYWtool.exe. The application bundles its Python runtime and application libraries. It runs with the current Windows user (asInvoker), does not register services, write to Program Files, change machine-wide settings, or request administrator elevation. No separate Python, pip, or application dependency installation is required. Keep the extracted folder in a location where your Windows user can write.

### Hand Check model

The MediaPipe Hand Landmarker model is downloaded automatically on the first Hand Check run and verified with SHA-256. Internet access is required for that initial download; the model is cached for later runs. See [MODEL.md](MODEL.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Run from source

- Windows 10/11
- Python 3.12 recommended

```powershell
python -m pip install -r requirements.txt
python zywtool.py
```

## Data safety

- Keep operational workbooks and source recordings outside the application directory.
- Back up source data before bulk file operations.
- Review the Arrange destination before confirming a move or copy operation.
- Do not commit real configuration files, operational workbooks, recordings, logs, reports, model caches or private machine paths.
- Sessions without valid start metadata remain visible in Scan Audit, but date-dependent operational rows cannot be populated safely without reliable date information.

## Development and verification

Run the test suite:

```powershell
python -m compileall -q .
python -m pytest tests -q
```

Build the Windows portable package:

```powershell
.\build_portable.ps1
```

The build script provisions an isolated Python 3.12 environment, installs pinned dependencies, creates the Windows one-folder executable and packages `release\ZYWtool-Windows-Portable.zip`. GitHub Actions validates compilation, tests and lint for the recorder-discovery regression tests.

Tests use temporary directories and synthetic fixtures; they do not require operational recordings or workbooks.

## Project structure

| Path | Purpose |
| --- | --- |
| `zywtool.py` | Main desktop GUI |
| `zyw_core.py` | Discovery, scanning, organization and Excel logic |
| `handcheck.py` / `handreport.py` | Hand Check and HTML reporting |
| `preview_frames.py` | Timeline preview generation |
| `undo_arrange.py` | Guarded restoration for Arrange operations |
| `tests/` | Regression and safety tests |
| `build_portable.ps1` | Windows portable build |
| `install.ps1` / `uninstall.ps1` | Optional Windows installation and removal |

## License and attribution

Copyright © Fadhil Ghifarion 法迪 for AIT.

Application source code is released under the [MIT License](LICENSE). The MediaPipe model is a third-party asset distributed under Apache License 2.0; consult [MODEL.md](MODEL.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for its terms and notices.
