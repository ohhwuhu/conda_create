# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A Windows tkinter GUI ("Miniconda 环境管理器") for creating and deleting conda environments without needing conda on PATH at runtime. UI strings are in Simplified Chinese. No third-party runtime dependencies; stdlib only (tkinter, subprocess, json, threading). Packaged to a single exe with PyInstaller.

## Commands

- Run the app: `python main.py`
- Run all tests: `python -m unittest test_conda_api`
- Run one test class/method: `python -m unittest test_conda_api.TestBuildCreateArgs`
  `python -m unittest test_conda_api.TestParseEnvPaths.test_case_insensitive_base_match`
- Build the exe: run `build.bat` (wraps `python -m PyInstaller --onefile --windowed --noconfirm --name CondaEnvManager main.py`), output in `dist\CondaEnvManager.exe`. The checked-in `CondaEnvManager.spec` is a generated artifact, not the source of truth for builds.

## Architecture

Two files, deliberately separated so the logic layer is testable without a conda install:

- **conda_api.py** — pure logic. Locating conda, building argv, parsing output. Functions with no side effects (`build_create_args`, `build_remove_args`, `parse_env_paths`, `resolve_prefix_env_path`) are pure and unit-tested. All conda invocations use the absolute path of a located conda executable; `find_conda()` resolves it in order: explicit choice → `CONDA_EXE` env var → PATH → common install roots (`~/miniconda3`, `~/anaconda3`, `D:/app`, `C:/ProgramData`, `C:`).
- **main.py** — `CondaEnvManagerApp(tk.Tk)`, the whole GUI. Contains validation, the create/delete flows, and the env list. Calls into `conda_api` only.

### Threading model (important)

The GUI is single-threaded. Every conda operation runs on a daemon `threading.Thread`; the worker never touches widgets. Results flow back as `(kind, payload)` tuples on a `queue.Queue`, drained every 100 ms by `_poll_queue` on the main thread (kinds: `status`, `log`, `env_list`, `detected`, `detect_failed`, `create_done`, `remove_done`, `error`). `_enqueue` is the only way workers communicate with the UI.

### Subprocess conventions

- `conda_api.run_sync` / `run_streaming` always pass `CREATE_NO_WINDOW` (Windows) so conda never pops a console window from under the GUI exe.
- Streaming reads stdout/stderr on two separate daemon threads to avoid pipe deadlock on long `conda create` output.
- Output decoding is utf-8 with `errors="replace"` — conda may emit non-UTF-8 (e.g. GBK) text on some systems; don't change this or parsing can crash.

### Key invariants

- `parse_env_paths` derives each env's `name`, `path`, `is_base`; a path under an `envs_dirs` root gets the folder basename as name, anything else keeps the full path as its name, and base sorts first.
- `resolve_prefix_env_path` maps a chosen folder to `<folder>\.conda` (the env root for prefix environments); a folder already named `.conda` is used as-is.
- The GUI protects the base env from deletion and validates env names against `INVALID_NAME_CHARS` in `main.py`.

## Testing

Tests are `unittest` (no pytest), covering only `conda_api.py` pure functions and `_candidate_roots`. They must not require a conda install or network. When adding a conda operation, keep the argv-building and output-parsing as pure functions in `conda_api.py` so the GUI behavior stays testable; add matching tests in `test_conda_api.py`.
