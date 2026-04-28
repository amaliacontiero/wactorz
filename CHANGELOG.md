# Changelog

All notable changes to Wactorz are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versioning follows [SemVer](https://semver.org/).

---

## [Unreleased]

---

## [0.3.0] — 2026-04-27
### Added

- **Home Assistant addon** — full HA Supervisor addon (`ha-addon/`) supporting HAOS and Supervised installs. Configurable LLM provider, MQTT, HA token, Fuseki, Discord/Telegram integrations. Optional embedded Mosquitto (`mosquitto_embedded`) and Fuseki (`fuseki_embedded`) services bundle broker and triplestore inside the addon container — no external addons required. Data persisted to `/share/mosquitto` and `/share/fuseki`. Ingress-compatible with relative asset paths and `X-Ingress-Path` header support.
- **MCP server** — `wactorz/mcp_server.py` exposes the actor system as an MCP (Model Context Protocol) server. Tools: `send_message`, `list_actors`, `get_actor_status`, `spawn_agent`, `stop_agent`. Resources: `wactorz://actors`, `wactorz://topics`. Configurable via `WACTORZ_MCP_*` env vars. Documented in `docs/interfaces.md`.
- **Unified persistence layer** — `wactorz/core/persistence.py` introduces a 3-tier architecture replacing pickle-only storage: SQLite (`state/wactorz.db`) for durable structured data (spawn registry, pipeline rules, user facts, topic contracts, time-series), Redis for ephemeral fast-access data (falls back to in-memory), and Pickle for arbitrary Python objects (agent state dicts, ML models). `PersistenceAPI` provides backward-compatible `persist()`/`recall()` with automatic key-based routing. `migrate_from_pickle()` runs once on first startup to migrate existing state.
- **Time-series SQLite tables** — `sensor_readings`, `detections`, `ha_state_changes`, and `actuations` tables with full-text and time-range query helpers (`query_sensor`, `query_detections`, `query_ha_states`, `query_actuations`). Automatic retention pruning via `prune_old_data(days=30)`.
- **Fuseki Channel ontology and MetricsBridge** — `infra/fuseki/ontology/wactorz.ttl` extended with `af:Channel` class (`channelTopic`, `declaredSchema`, `observedSchema`, `triggersWhen`) and agent metrics properties. `FusekiClient.replace_agent_channels()` persists pub/sub topology to `urn:wactorz:channels`. `MetricsBridge` subscribes to `agents/+/metrics` MQTT and continuously updates agent metrics in the RDF graph via `upsert_agent_metrics()`.
- **Activity feed cap** — UI activity feed is capped at 500 entries; an overflow banner appears when the limit is reached.
- **Cost metrics persistence and final publish** — LLM cost and token metrics are persisted across restarts and published in the final heartbeat on actor stop.

### Fixed

- **Ollama system prompts** — `OllamaProvider` now sends `system_prompt` as the first `role=system` chat message for both blocking and streaming `/api/chat` calls, instead of relying on an undocumented top-level `system` payload field.
- **HA addon ingress** — corrected `X-Ingress-Path` header name; relative paths used for favicon and manifest so the base tag resolves correctly behind the HA proxy; SPARQL proxy URLs now prepend the ingress path.
- **HA addon embedded Fuseki startup** — `shiro.ini` is regenerated on every boot so credential changes apply immediately; correct dataset config and readiness wait added.
- **HA addon Docker layer cache** — `BUILD_VERSION` arg now busts the Docker cache on version bumps; deprecated `build.yaml` removed; base image fixed to `ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.20`.
- **Catalog agent persistence** — fixed catalog agent spawning and persistence after the persistence layer migration.
- **HA map agent `CancelledError`** — handled `asyncio.CancelledError` in `HomeAssistantMapAgent` to prevent noisy tracebacks on shutdown.
- **Resource cleanup on stop** — `Actor.on_stop()` now cancels background tasks and cleans up open resources more reliably.
- **Frontend URL resolution** — unified backend URL resolution across Tauri desktop, HA addon, and plain browser: checks `window.__WACTORZ_API_PORT`, then `window.__WACTORZ_API_BASE`, then falls back to `window.location`.
- **CI: Linux system deps** — added missing Linux system dependencies to the Rust test job.

### Changed

- **One-shot Home Assistant actuation timeouts** — intent classification now allows up to 60 seconds, while the ephemeral `OneOffActuatorAgent` resolver and main actuation wait allow up to 120 seconds for slower local models such as Ollama.
- **Versioning** — `fbc0ccd` improved version handling; `wactorz/_version.py` remains the single source of truth.

### Tests

- Added focused `OllamaProvider` payload tests covering non-streaming and streaming system-prompt delivery.
- Added MCP server contract tests (`tests/test_mcp_server.py`); contract tests skip gracefully when optional MCP dependency is absent.

---


## [0.3.0] — 2026-04-18

### Added

- **Telegram interface** — new `--interface telegram` mode using `python-telegram-bot`; users self-host their own bot via a BotFather token. Supports `TELEGRAM_ALLOWED_USER_ID` to restrict access to a single user. The `/start` command replies with the user's numeric Telegram ID for easy setup.
- **`TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_USER_ID`** env vars added to `config.py` and `.env.example`
- **One-shot Home Assistant actuation** — `MainActor` now classifies immediate device-control requests as `ACTUATE` and routes them to a new ephemeral `OneOffActuatorAgent` that resolves natural language to HA service calls, executes them, reports the result, tracks LLM cost, then unregisters, stops, and deletes its own persistence directory.
- **Prometheus monitoring for the Python runtime** — the REST interface now exposes `GET /metrics` with Prometheus-formatted HTTP, actor, process, and LLM usage metrics via a shared `PrometheusMonitor` collector in `wactorz/monitoring/prometheus.py`.
- **Prometheus Compose services** — `prometheus` and `blackbox-exporter` services added to `compose.yaml` and `compose.dev.yaml` for Python-stack monitoring. Optional Mosquitto and Fuseki availability probes are controlled via `PROMETHEUS_MONITOR_MOSQUITTO` and `PROMETHEUS_MONITOR_FUSEKI`.
- **Prometheus configuration assets** — added templated config generation in `infra/prometheus/` including `prometheus.yml`, `render-config.sh`, `blackbox.yml`, and starter alert rules in `alerts.yml`.
- **Prometheus docs and tests** — added `docs/prometheus.md`, linked it in the docs navigation, documented `GET /api/metrics`, and added focused tests for collector output, config generation, and REST content type handling.

### Changed

- **Discord interface** — bot now responds to `@mention` instead of the `!` prefix for a more natural UX. Long responses are automatically split into 2000-character chunks to avoid Discord's message length limit.
- **Documentation** — added README and agent reference coverage for `ACTUATE` intent routing and the new `OneOffActuatorAgent`.

---

## [0.2.0] — 2026-03-13

### Added

- **IOAgent** — MQTT gateway routing `io/chat` messages to the correct actor; replaces direct topic publishing
- **MQTT TCP bridge** in `monitor_server.py` — `/mqtt` WebSocket endpoint now falls back to raw TCP (port 1883) when Mosquitto's WS listener (port 9001) is unavailable
- **Web UI auto-start** — `wactorz` CLI spawns the monitor server as a quiet background asyncio task (`--no-monitor` to opt out, `--monitor-port` to override port 8888)
- **`/api/actors` REST endpoint** on Python monitor server — returns live agent state from MQTT-derived in-memory store
- **`wactorz[all]` wheel** now bundles `static/app/` and `monitor.html` via hatchling `force-include`; custom build hook rebuilds frontend when stale
- **`wactorz/_version.py`** — single source of version truth, imported by `__init__.py` and `pyproject.toml`
- **Rust WS bridge** — `/mqtt` proxy route added alongside `/ws`; `WsBridge` now tracks MonitorState and broadcasts `full_snapshot`/`patch`/`delete_agent` to `/ws` clients
- **`scripts/build.py`** — clean build script (hatchling + twine) with `--upload` flag for PyPI

### Fixed

- **`RangeError: invalid date`** — Python heartbeat uses epoch seconds (`timestamp`); TypeScript normaliser now converts to ms automatically for both Python (snake_case) and Rust (camelCase) payloads
- **MQTT disconnect on listener error** — `emit()` now wraps each listener call in try/catch; a throwing handler no longer crashes the MQTT connection
- **Chat infinite typing indicator** — fixed key mismatch between `showTyping("main-actor")` and `hideTyping("io-agent")`; `IOManager` tracks `_lastTypingKey` and clears it on any reply
- **`llm_agent._handle_task`** — `complete()` returns `(text, usage)` tuple; was incorrectly storing the whole tuple as message `content`, causing Anthropic 400 errors on the second conversation turn
- **CI test failures** — `wactorz/` package was accidentally gitignored; restored source tracking and fixed test import paths for the new package layout
- **`/api/actors` 404** — Python monitor server now serves actor list at this endpoint

### Changed

- `wactorz/__init__.py` — optional agent imports (LLM, HA, ML) now wrapped in `try/except ImportError` so importing any submodule works without all optional deps installed
- Python payload normalisers centralised in `MQTTClient.ts` — `normaliseHeartbeat`, `normaliseChat`, `normaliseStatus`
- Monitor server `_find_dir()` helper resolves `static/app` for both editable and installed-wheel layouts

---

## [0.1.0] — 2025-11-01

### Added

- Initial open-source release
- Python actor model core: `Actor`, `ActorSystem`, `Supervisor` with ONE_FOR_ONE / ONE_FOR_ALL / REST_FOR_ONE strategies
- Built-in agents: `MainActor`, `MonitorActor`, `CodeAgent`, `ManualAgent`, `IOAgent`, `InstallerAgent`, `AnomalyDetectorAgent`
- LLM providers: Anthropic Claude, OpenAI, Ollama, NVIDIA NIM
- MQTT pub/sub telemetry (heartbeat, metrics, status, alert, chat, spawn, logs, completed)
- Babylon.js 3D web dashboard (graph, galaxy, cards, social, fin themes)
- CLI interface (`wactorz --interface cli`)
- REST interface with API key auth
- Discord and WhatsApp interfaces
- Python monitor server (aiohttp) serving dashboard + WebSocket bridge
- Rust axum server with WebSocket bridge and REST API
- Home Assistant integration agents
- Docker Compose stacks (dev and production)
- `pyproject.toml` with optional dependency groups

[0.2.0]: https://github.com/waldiez/wactorz/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/waldiez/wactorz/releases/tag/v0.1.0
