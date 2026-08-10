# Repository Guidelines

## Project Overview

Cat Bowl Monitor is a HACS-compatible Home Assistant custom integration (`cat_bowl_monitor`). It uses an OpenAI-compatible vision model to estimate separate dry- and wet-food bowl state, track consumption, schedule checks, notify household members, and optionally request guarded feeder actions through Home Assistant scenes, scripts, or buttons.

Safety behavior is central: unknown, hidden, dark, or low-confidence readings fail closed; manual **Check now** never feeds; feeder actions are validated before use and are not automatically retried.

## Architecture & Data Flow

- `custom_components/cat_bowl_monitor/__init__.py` is the config-entry entry point. It creates and stores a `BowlRuntime`, forwards Home Assistant platform setup, starts the runtime, and stops it during unload.
- `runtime.py` is the orchestration/state layer. It restores persistent state and image slots, schedules daily/repeating checks, serializes checks and feed cycles, applies confirmation rules, emits events, updates notifications, and coordinates optional feeder actions and post-feed baselines.
- Typical flow: config entry or manual/scheduled trigger → camera snapshot (`camera_source.py`) → Pillow quality gate/normalization (`image.py`) → bounded OpenAI-compatible vision request (`ai.py`) → strict structured parsing and pure decision rules (`logic.py`) → persisted runtime state and platform entities → optional validated feeder action → settled after-image/baseline.
- Scheduled feeding requires two AI samples 30 seconds apart. The configured dry zone controls the primary action; a secondary action additionally requires the wet zone to be confidently empty. Cycle keys are persisted before actuation, and failed or unverified actions are not retried.
- `config_flow.py` contains setup/options schemas and validates camera, Home Assistant entities/services, and provider settings. Provider credentials may be direct or reused from the loaded UBox Camera integration without copying them.
- Platform modules expose runtime state as Home Assistant sensors, binary sensors, buttons, and cameras. `entity.py` supplies shared entity/device behavior; `const.py` defines domain constants and platform registration.

## Key Directories

- `custom_components/cat_bowl_monitor/` — integration implementation, metadata, translations, and brand assets.
- `custom_components/cat_bowl_monitor/brand/` — HACS/Home Assistant icon assets.
- `custom_components/cat_bowl_monitor/translations/` — UI translations; `strings.json` contains source strings.
- `tests/` — synchronous pytest coverage for pure parsing, image, and camera-source helpers.
- `.github/workflows/` — CI validation workflow.

## Development Commands

From the repository root, with dependencies installed:

```bash
pytest -q
ruff check custom_components tests
```

CI installs the test tools with `pip install pillow pytest ruff`, then runs the same two commands under Python 3.13. There is no Makefile, setup script, lockfile, or project-specific build command; Home Assistant loads the integration from `custom_components/`.

## Code Conventions & Common Patterns

- Python modules and functions use `snake_case`; classes use `CapWords`; constants use uppercase names. Modules use `from __future__ import annotations` and explicit type hints.
- Home Assistant lifecycle and I/O are asynchronous (`async_setup_entry`, `async_start`, `async_stop`, scheduled callbacks, HTTP/camera calls). Keep blocking work out of the event loop and preserve runtime locks around checks/cycles.
- Keep decision logic pure where possible. `logic.py` uses frozen, slotted dataclasses (`BowlReading`, `Assessment`, `Consumption`, `Confirmation`) and small validation/state-transition helpers; extend these seams rather than coupling tests to Home Assistant.
- Runtime state belongs in `BowlRuntime` and is exposed through `entry.runtime_data`; platform entities read that state and call shared entity helpers instead of maintaining duplicate state.
- Use explicit domain exceptions such as `ProviderError` and `AssessmentError`. Provider responses are strictly parsed, bounded/retried only where documented, and invalid or inconclusive input must remain fail-closed.
- Preserve image privacy and retention rules: only bounded `latest.jpg`, `before.jpg`, `after.jpg`, and `baseline.jpg` slots are retained under `/config/cat_bowl_monitor/<entry-id>/`, with atomic replacement.
- Match existing Home Assistant APIs and type aliases. Do not introduce a second configuration, state, or dependency-injection pattern without a concrete integration need.

## Important Files

- `custom_components/cat_bowl_monitor/__init__.py` — config-entry setup/unload and `BowlConfigEntry` type alias.
- `custom_components/cat_bowl_monitor/runtime.py` — scheduling, persistence, state machine orchestration, feeding safeguards, events, and notifications.
- `custom_components/cat_bowl_monitor/logic.py` — pure response parsing, validation, confirmation, schedule, freshness, and safety-feed decisions.
- `custom_components/cat_bowl_monitor/ai.py` — provider selection, OpenAI-compatible HTTPS requests, prompts, and bounded response handling.
- `custom_components/cat_bowl_monitor/config_flow.py` — initial setup and options validation.
- `custom_components/cat_bowl_monitor/camera_source.py` and `image.py` — bounded camera retrieval plus image quality/normalization helpers.
- `custom_components/cat_bowl_monitor/sensor.py`, `binary_sensor.py`, `button.py`, `camera.py`, `entity.py` — Home Assistant entity platforms and shared entity behavior.
- `custom_components/cat_bowl_monitor/manifest.json` — integration metadata and Pillow requirement (`Pillow>=12.3.0,<13.0.0`).
- `custom_components/cat_bowl_monitor/const.py` — domain constants and `PLATFORMS`.
- `README.md` — user-facing behavior, installation, safety rules, entities/events, privacy, and development commands.
- `pyproject.toml` — pytest discovery/path configuration; `hacs.json` — HACS metadata; `.github/workflows/validate.yml` — HACS, Hassfest, lint, and test CI.

## Runtime/Tooling Preferences

- Target runtime is Home Assistant, with Python code loaded as a custom integration. CI explicitly tests Python 3.13; the code uses modern Python syntax, including a PEP 695 type alias, so use a current Python version compatible with that syntax.
- The integration declares Pillow as its only package requirement; Home Assistant supplies the Home Assistant and Voluptuous APIs at runtime. Do not add a separate dependency-management convention unless the repository adopts one.
- Use `pip` for the documented CI dependency install. Ruff is the repository's configured/CI-enforced linter, but no Ruff, formatter, type-checker, or coverage configuration file exists; follow existing source style rather than inventing settings.
- Preserve HACS and Hassfest compatibility. Metadata lives in `manifest.json` and `hacs.json`; validate integration metadata through the existing CI workflow when relevant.

## Testing & QA

- Pytest is configured with `testpaths = ["tests"]` and `pythonpath = ["."]` in `pyproject.toml`.
- Tests are synchronous plain pytest functions. The suite has `tests/test_logic.py`, `tests/test_image.py`, and `tests/test_camera_source.py`; tests directly import these dependency-light modules with `importlib.util` so they do not require a full Home Assistant installation. Existing patterns use small input builders and `pytest.raises`, not fixtures, mocks, or async test plugins.
- Coverage focuses on strict provider parsing, invalid/truncated responses, confirmation and safety-feed boundaries, wet-food freshness, notification/photo deduplication, schedules, image low-light/black/truncated handling, and private camera URL selection.
- Run the local checks with `pytest -q` and `ruff check custom_components tests`. CI also runs HACS validation and Hassfest on every push, pull request, or manual dispatch.
- There is no configured coverage threshold and no direct test coverage for `runtime.py`, `ai.py`, `config_flow.py`, or the Home Assistant platform modules. When changing those paths, add focused tests at a dependency-light seam where practical and manually exercise Home Assistant behavior when available.
