# Repository Guidelines

## Project Structure & Module Organization

This repository implements a desktop ARM telemetry configuration MVP. `main.py` launches the application. `telemetry/` contains the DWARF parser, protocol codec, application bridge, JSON persistence, and `transports/` plugins. `web/` holds the local dashboard HTML, CSS, and JavaScript. `tests/` contains Python unit tests and generated ELF fixtures. See `README.md` for architecture, supported DWARF forms, and launch options.

## Build, Test, and Development Commands

- `python -m venv .venv` creates an isolated environment; activate it with `.venv\Scripts\Activate.ps1` on Windows.
- `python -m pip install -r requirements.txt` installs desktop and ELF dependencies.
- `python main.py` starts the native desktop window.
- `python main.py --browser` serves the same UI on loopback for browser development.
- `python -m unittest discover -s tests -v` runs core regression tests.
- `node --check web/app.js` checks frontend JavaScript syntax.

No frontend compilation is required. Keep UI assets local so the desktop app works offline.

## Coding Style & Naming Conventions

Use four spaces in Python and two spaces in JavaScript/CSS. Use Python type annotations at module boundaries, `snake_case` for functions/modules, and `PascalCase` for classes. JavaScript uses `camelCase`. Keep protocol encoding pure and independent of windowing and transport libraries. Route application actions through the bridge and `TransportManager`. No formatter or linter is configured initially; keep changes consistent with nearby code.

## Testing Guidelines

Use standard-library `unittest`; name files `test_*.py` and methods `test_*`. Test CRC reference vectors, exact wire bytes, decoding, invalid slots and RAM boundaries, persistence rebinding, and parser fixtures. No numeric coverage threshold is established. Verify UI changes with demo mode, including search, favorites, slot ordering, and output copying. Document checks that require an actual ARM firmware file.

## Commit & Pull Request Guidelines

Use imperative, scoped subjects such as `feat(parser): expand fixed arrays`. Describe behavior changes, validation, and limitations. Link relevant issues and include screenshots for UI changes.

## Feature Branch & Acceptance Workflow

1. Before implementing each new feature, create a dedicated `feat/<short-name>` branch from the latest `origin/main` (for example, `feat/serial-transport`). Keep unrelated features on separate branches.
2. Develop, test, commit, and push on that feature branch. Never commit new features directly to `main`.
3. Deliver the branch link, changes, test results, and any runnable artifact for user acceptance. Requests to commit or push authorize updating the feature branch, not merging it.
4. Merge into `main` only after the user explicitly accepts the delivered feature. Passing tests is not acceptance; subsequent feature changes require renewed acceptance.
5. After approval, preserve remote history, merge the accepted branch, verify `main`, and report the merge commit. Keep unaccepted branches separate when starting another feature.

## Configuration & Safety

Persist favorites and presets as symbol paths, resolving addresses on each firmware load. Validate complete variable extents against configured half-open RAM intervals before frame generation. Communication remains mock-only in V1. Keep generated firmware, local settings, and virtual environments out of version control.
