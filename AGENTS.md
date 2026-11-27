# Repository Guidelines

Axon is a Windows desktop ARM telemetry configurator. A pywebview window (named Axon) hosts a framework-free HTML/JS dashboard backed by an authenticated loopback HTTP server. There is no frontend build, CDN, database, or network service beyond loopback.

## Commands

Use the repo virtualenv; the system Python may lack `pyelftools` / `pywebview` / `pyserial`.

```powershell
.\start.bat                                      # create venv, install deps, run
.\.venv\Scripts\python.exe main.py               # desktop window
.\.venv\Scripts\python.exe main.py --browser     # browser mode; prints loopback URL

.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_core.py" -k fingerprint -v
node --check web/app.js

.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm Axon.spec
```

- Run tests from the repo root. `tests/` is the discovery import root; running a test module from inside `tests/` makes `telemetry` unimportable.
- `node` is only for JavaScript syntax checking; the app does not need Node.js. No linter, formatter, typechecker, or CI is configured.
- The PyInstaller spec bundles `web/` and produces the windowed `dist/Axon.exe`; startup errors are logged to `~/.axf_telemetry/startup.log`.

## Architecture and invariants

- `main.py` is the only entry point. It serves exactly `/`, `/app.js`, and `/style.css`, replaces `__API_TOKEN__` in `index.html`, and exposes one authenticated `POST /api`. Any new static asset must be added to that route table. `web/` is read from disk per request, so a stale Python process can serve the latest UI against old backend actions ("Unknown action"); fully restart after backend changes.
- `telemetry/bridge.py` is the UI action surface. `web/app.js` polls `state` every 1.2s and renders the complete `snapshot()`; add new actions in `Bridge._action` and new device I/O behind `TransportManager`.
- `telemetry/protocol.py` stays pure and independent of windowing/transport. Wire layout: `header[2] | cmd=01[1] | fingerprint u32 LE | N u8 | (address u32 LE, type u8) × N | CRC16/MODBUS u16 LE`; length is `10+5N`; type IDs 0-6; bool is displayed as `bool` but encoded as uint8 type 6. RAM intervals are half-open and must cover each variable's full width.
- `telemetry/parser.py` accepts only linked 32-bit little-endian ARM `ET_EXEC` with DWARF, and only statically addressed variables (`DW_OP_addr` exactly) in allocated writable sections. It expands structs/classes/unions/fixed arrays and skips pointers, bitfields, `double`, and dynamic/location-list entries. Limits are 32 levels and 100000 leaves; keep them tested.
- Fingerprint invariant: CRC32 of the `g_telemetry_build_stamp` bytes found through `.symtab`, stopping at the first NUL. Never CRC the whole AXF, include the NUL, or hardcode a file hash. A missing symbol yields fingerprint `0` with source `Missing g_telemetry_build_stamp`; parsing still succeeds. The frame field and UI must show this same value.
- Change detection uses a background mtime/size poll and exposes the `changed` flag via `snapshot()`; it must not auto-reparse. The UI auto-opens a reparse dialog with update/ignore choices; update verifies the user has flashed the new `.axf`, then `reload` reparses and rebinds symbol paths. Ignoring suppresses the same stamp until the file changes again. If reload runs while the file is missing/locked or parsing fails, re-arm the ignored stamp so the watcher prompts again after the next stable change instead of staying stuck. A failed parse keeps the last good symbols.
- Favorites, presets, and active slots persist as symbol paths only; resolve addresses on every parse. Never store addresses in `.axon` files.
- `telemetry/storage.py` owns `.axon` schema 1 validation and atomic writes (temp file + `fsync` + `os.replace`); `Bridge` debounces autosave at 500ms. `.tmws` remains readable for compatibility. `writable_ram_ranges` is an optional, separate schema field reserved for V2 write access; it must not be used by read-frame generation. Firmware paths are relative to the workspace when possible; global state and the default workspace live under `~/.axf_telemetry/`.
- `telemetry/onboarding.py` is project-agnostic: protocol and build-stamp fingerprint rules are fixed, while MCU/RTOS/link/receive path/RAM must come from a project survey. Workspace RAM ranges are comparison candidates only; the actual linker script and `.map` are authoritative. Keep the safe fixed-channel-table fallback when RAM cannot be confirmed.
- `TransportManager` switches between `MockTransport`, a real `SerialTransport`, and a single upstream `TCPClientTransport`. Frames are written by the same `send()` path; bytes received from either serial or TCP are raw-forwarded to `LocalProxyServer` (`127.0.0.1:9000` by default), which broadcasts to VOFA+ clients and ignores their writes. The proxy is receive-only and is auto-started on serial/TCP connect when the UI supplies proxy settings, stopped on disconnect/workspace switch; it never auto-starts on app launch. Serial settings persist under `transport.serial`, TCP under `transport.tcp`, proxy under `transport.proxy`. Neither link parses telemetry, sends ACK, or reconnects automatically; serial uses a bounded reader thread.

## Testing

- Use standard-library `unittest`. Tests build an ARM ELF32/DWARF4 fixture in `tests/elf_fixture.py`, so no cross compiler or real firmware is required. Serial tests patch `serial.Serial` and cover read/forwarding without opening a real COM port. TCP/proxy tests use temporary loopback servers and ephemeral ports; never bind the production proxy port or reach a real vehicle. Real Keil/ARM Compiler output and hardware links still need manual acceptance.
- `Bridge()` defaults to the real `~/.axf_telemetry`; tests must inject a temporary `Storage` (or `config_dir`) so they never touch a user workspace.
- UI changes: exercise demo mode, including search, favorites, slot ordering, output copying, and the changed/reload flow. There is no browser automation suite.

## Conventions and safety

- Four spaces in Python, two in JavaScript/CSS. Type annotations at module boundaries; `snake_case` functions/modules, `PascalCase` classes, `camelCase` JavaScript.
- Recent commits use imperative scoped subjects such as `feat(parser): expand fixed arrays` and `fix(parser): fingerprint telemetry build stamp`; follow that.
- Do not commit `.venv/`, `build/`, `dist/`, `*.axon`, `*.tmws`, `*.axf`, `*.elf`, `app_state.json`, or `~/.axf_telemetry/` contents. Firmware images and workspaces are user data.
- `README.md` is the Chinese user-facing reference; update it when protocol or UX behavior changes rather than duplicating detail here. `ROADMAP.md` tracks V1/V2 scope and tech-stack decisions.

## Status and next work

- Done: build-stamp/fingerprint display, mtime/size change alert, manual reparse with symbol-path rebinding, real serial/TCP connect/send, and local VOFA+ proxy for both links.
- Pending: UDP forwarding and any parsed telemetry-uplink format. Do not invent upstream framing or present the proxy as parsing data.
