# 000054 Project Gitignore

## Original prompt

add gitignore to the project please and add everything that should be ignored and not commited to the repository

## What changed

- Added project root `.gitignore`.
- Ignored Python bytecode and cache folders:
  - `__pycache__/`
  - `*.pyc`, `*.pyo`, `*.pyd`
- Ignored local Python virtual environments:
  - `.venv/`
  - `venv/`
  - `env/`
- Ignored test/type/lint coverage caches:
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `.mypy_cache/`
  - `.coverage`
  - `htmlcov/`
- Ignored build and bundling outputs:
  - `build/`
  - `dist/`
  - `*.egg-info/`
  - `*.spec`
  - native compiled/linker artifacts
- Ignored installer/download artifacts:
  - `*.msi`
  - archives such as `*.zip`, `*.7z`, `*.tar.gz`
- Ignored runtime logs:
  - `logs/`
  - `*.log`
- Ignored runtime user settings/data:
  - `data/*.json`
  - `data/*.tmp`
  - `install_info.json`
- Ignored generated launcher/shortcut files:
  - `run_gaze_mouse.bat`
  - `run_gaze_mouse.ps1`
  - `assets/icon.ico`
- Ignored local prompt/test scratch files:
  - `promps.txt`
  - `promops.txt`
  - `test`
  - `test.txt`
  - `test.xt`
  - `file2.txt`
- Ignored IDE/editor and OS metadata:
  - `.vscode/`
  - `.idea/`
  - `.DS_Store`
  - `Thumbs.db`
  - `Desktop.ini`
- Ignored Codex/agent runtime metadata directories:
  - `.agents/`
  - `.codex/`

## What should stay commit-ready

- Source code under `gaze_mouse/`.
- PowerShell source scripts such as `setup_windows.ps1` and `start_gaze_mouse.ps1`.
- `requirements.txt`.
- `README.md`.
- `AGENTS.md`.
- Source assets such as `assets/icon.png` and `gaze_mouse/assets/checkbox_x.svg`.
- Agent prompt history documents.

## Validation

- Verified no `__pycache__`, `.pyc`, or `.pyo` files are present after the change.

## Notes

- `*.spec` is ignored as generated PyInstaller output. If the project later creates a hand-maintained PyInstaller spec file, remove that ignore rule for the specific spec file.
