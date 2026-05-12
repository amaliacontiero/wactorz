# Changelog

All notable changes to Wactorz are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versioning follows [SemVer](https://semver.org/).

---

## [Unreleased]

### Added

- **Dynamic LLM pricing** -- `LLMAgent` now fetches live model prices from the [LiteLLM model catalogue](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) on startup and caches them for 24 hours. Falls back to a hardcoded table if the fetch fails or the model is not found. `pricing_info(model)` helper added for debugging (reports source, rates, and cache age).
- **`HomeAssistantAgent` -- `other` action** -- A new `other` action handles open-ended HA questions ("Do I have any thermometers?", "What is the state of my thermostat?") that do not map cleanly to `list_*` or `call_service`. The agent runs a short LLM tool-call loop (up to 3 rounds) using `get_simplified_ha_data` to answer the question without over-classifying inventory requests or listing every entity. A `ha_context_terms` heuristic ensures common HA-related questions are routed here instead of falling through to `unknown`.
- **`HomeAssistantAgent` -- `get_entities_state` action** -- Accepts one or more explicit entity IDs, fetches their current states from HA, and re-publishes each state to `homeassistant/state_changes/{entity_id}` over MQTT. This lets callers query live state and simultaneously bootstrap any MQTT subscriber that is waiting for a change event.
- **`ha_helper.get_full_ha_data()`** -- New async helper that returns raw registry dumps for floors, areas, devices, entities, and states in a single WebSocket session, without transforming or filtering any field.
- **`ha_helper.get_simplified_ha_data()`** -- New async helper that returns a compact, null-stripped snapshot suitable for LLM prompts. Resolves entity display names from live states, excludes `hassio` platform entities, and drops icon/picture fields. Used by `HomeAssistantAgent` to replace the older `fetch_devices_entities_with_location` call, significantly reducing token usage in device-discovery prompts.
- **`PlannerAgent` -- HA entity state bootstrap** -- After spawning a pipeline, the planner now calls `_bootstrap_ha_entity_states()` as a background task. It extracts entity IDs from the plan's generated code, `ha_actuator` actions, MQTT topics, and the enriched task string, then sends a `get_entities_state` request to `home-assistant-agent`. This re-publishes current HA state to `homeassistant/state_changes/{entity_id}` so freshly-spawned agents that subscribe to that topic fire immediately, instead of waiting for the next real HA state change to arrive.
- **Remote runner self-bootstrap** -- `RemoteRunnerAgent` nodes now self-install `aiomqtt` / `paho-mqtt` on first start without requiring pre-installed dependencies. Heartbeat begins immediately; dependency installation runs in the background so the node appears on the overview before pip finishes.
- **Live remote node tracking** -- the overview panel tracks remote runner nodes in real time; deleted-agent ghost entries no longer re-appear after removal.
- **OpenTelemetry Collector** -- `otelcol` service added to Docker Compose with a Prometheus remote-write scrape target; healthcheck included and a commented debug exporter option for local tracing.

### Changed

- **`HomeAssistantAgent` -- device-discovery schema** -- The prompt schema for hardware-recommendation requests now uses the flattened `get_simplified_ha_data` structure (separate `floors`, `areas`, `devices`, `entities` lists) instead of the deeply nested `fetch_devices_entities_with_location` format. This cuts the context size and matches the real HA registry field names (`id`, `area_id`, `domain`, etc.).
- **`HomeAssistantAgent` -- `list_*` classification tightened** -- The `list_automations`, `list_areas`, `list_devices`, and `list_entities` actions now only fire on explicit inventory requests ("list all automations"). Existence, count, lookup, and state questions ("do I have a thermostat?", "what is the state of X?") are correctly routed to the new `other` action.
- **`HomeAssistantAgent` -- MQTT state-change payload** -- `get_entities_state` now publishes the canonical state-change payload (`event_type`, `entity_id`, `new_state`, `old_state`) to `homeassistant/state_changes/{entity_id}`, matching the format emitted by `HomeAssistantStateBridgeAgent` on real HA state changes.

### Fixed

- **LLM cost persistence** -- Five places where token usage was accumulated in memory but never written to SQLite, causing cost data to be lost on restart or crash: `LLMAgent._handle_task` silently discarded all usage from TASK-type messages; `LLMAgent._maybe_summarize` did not persist summarization tokens; `HomeAssistantAgent` never persisted lifetime spend (entirely lost on restart); `MainActor._classify_intent` dropped tokens for PIPELINE/ACTUATE/HA routes where no `chat()` follows; `MainActor._extract_durable_facts` left facts-extraction tokens unpersisted until the next turn.
- **Gemini API key mapping** -- `LLM_API_KEY` now correctly mapped to `GEMINI_API_KEY` in the HA addon `run.sh`.
- **NIM documentation** -- `LLM_API_KEY` is always required for NVIDIA NIM calls; docs corrected.
- **HA addon optional fields** -- `discord_bot_token`, `telegram_bot_token`, `ha_token`, and `api_key` declared as `str?` in `config.yaml` schema so the addon validates when these fields are left blank.
- **Agent delete blink** -- deleted agents are marked immediately on delete command, preventing ghost re-appearance in the UI.
- **NIM fallback pricing** -- deprecated NVIDIA NIM model entries removed from the hardcoded fallback price table.

### Tests

- Added `tests/test_home_assistant_agent.py` -- covers `other` tool-call loop, `get_entities_state` action, MQTT publish payloads, and bootstrap entity ID extraction.
- Added `tests/test_llm_provider_tools.py` -- covers `complete_with_tools` for all LLM providers.

---

## [0.4.1] -- 2026-05-06

### Added

- **Flutter companion app** -- iOS/Android mobile app with agents list, chat interface, and activity feed. Connects to the Wactorz REST + WebSocket API.
- **PWA / service worker** -- installable progressive web app with `sw.js`; `icon.png` added; bottom tab bar for mobile browsers.
- **Persistent chat log** -- conversation history persisted to SQLite on every message; optionally mirrored to InfluxDB 2.x. Chat panel restores full history on page load.
- **InfluxDB 2.x integration** -- optional `influx_url`, `influx_token`, `influx_org`, `influx_bucket` config added to the HA addon and `.env.template`; `wactorz[influx]` bundled in the `[all]` extras group.
- **Server-side TTS via `edge-tts`** -- text-to-speech synthesised server-side with browser speech-synthesis fallback. Voice selector populated from server or browser voices; audio delivered via `AudioContext`.
- **Procedural ambient soundscapes** -- rain / forest / beach / cafe audio modes; `🔊` button popover replaces inline header controls.
- **Scheduled agents** -- new `ScheduledAgent` for cron-style recurring tasks. Planner and `MainActor` prompts updated to support scheduling intents.
- **User approval before spawning** -- planner generates a dry-run plan and requests explicit user confirmation before spawning agents. `approved` flag added to the plan payload.
- **Activity feed: HA state changes** -- real-time Home Assistant device state changes now appear in the activity feed, routed through `HomeAssistantStateBridgeAgent`, with domain-based filtering and WebSocket + MQTT deduplication.
- **REST: `/api/actors/{id}/history`** -- actor message history endpoint.
- **REST: `/api/chats`** -- chat log endpoint (all persisted messages, paginated).
- **Rust: `/api/feed`, `/feed`, `/config`** -- feed and config alias endpoints added to the Rust server; `MonitorState` wired to REST for consistent snapshots.
- **Desktop SQLite persistence** -- Rust backend now persists actor and message state to SQLite with auto-resume on restart.
- **OpenTelemetry metrics** -- OTel metrics integration; Fuseki triplestore bloat fixed alongside.
- **Docker Hub + GHCR CI image workflow** -- automated multi-registry image publishing on tag push.
- **Frontend test suite** -- comprehensive test suite with 95%+ coverage.
- **SPARQL planner integration** -- planner agent can query the Fuseki triplestore for context via `sparql_context.py` helper.
- **Staging Docker Compose** -- `compose.staging.yaml` for VM staging deployments.
- **Activity feed hover popover** -- styled hover popover for feed messages replaces native `title` tooltip.
- **Overview: message count persistence** -- message and cost stats survive restarts; seeded from SQLite on startup; backend totals shown before the first MQTT heartbeat.
- **Help menu** -- `/migrate` and `/nodes` commands now listed in `/help` output.

### Changed

- **Erlang-style supervision overhaul** -- full rewrite of the `Supervisor` with per-actor restart policies, configurable backoff, and max-restart caps across ONE_FOR_ONE / ONE_FOR_ALL / REST_FOR_ONE strategies.
- **Sound / TTS / voice controls** -- moved from the HUD (unreachable on small screens) to the header bar.

### Fixed

- **LLM API key provider mapping** -- `LLM_API_KEY` now mapped to the correct provider-specific env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `NIM_API_KEY`) in the HA addon `run.sh` and CLI.
- **NIM fallback** -- CLI and `MainActor` now fall back to `LLM_API_KEY` when the provider-specific variable is unset.
- **Compose port mapping** -- `MONITOR_PORT` used consistently on both sides of the port mapping.
- **Cost persistence** -- LLM cost written durably to SQLite; deleted agents included in the lifetime total; partial streaming responses persisted on interruption; user message persisted before the LLM call to avoid data loss on crash.
- **Activity feed** -- real persisted timestamps used for `/api/feed`; `log_feed` flood on WebSocket connect fixed; feed truncation removed from `IOManager`; spawn/alert timestamp normalisation prevents "Invalid Date" in the UI.
- **Deleted agents re-appearing** after delete action due to stale registry state.
- **Camera agents restart** and double-notification issues resolved.
- **HA amnesia** -- agent no longer forgets Home Assistant context across restarts.
- **Catalog timeout and null safety** -- catalog agent spawning timeout fixed; null guards added throughout `CardDashboard`.
- **Persistence layer** -- SQLite data no longer overwritten by stale pickle on restart.
- **`actor.stop()` cancellation** -- shielded from `asyncio.CancelledError` so shutdown completes cleanly.
- **MQTT paho `__del__` `RuntimeError`** -- suppressed on event loop close.
- **TTS voice cache** -- warmed at startup to avoid an executor-shutdown race.
- **Frontend** -- undefined `agentName` / `message` guard in alert handler; feed label hover; various null-safety fixes.
- **Chat history timestamps** -- chat panel now uses real persisted timestamps from the `chat_log` SQLite table.

### Tests

- Added `tests/test_cost_persistence.py` -- cost persistence and chat history API coverage.

---

## [0.4.0] -- 2026-04-25

### Added

- **Home Assistant addon** -- full HA Supervisor addon (`ha-addon/`) supporting HAOS and Supervised installs. Configurable LLM provider, MQTT, HA token, Fuseki, Discord/Telegram integrations. Optional embedded Mosquitto (`mosquitto_embedded`) and Fuseki (`fuseki_embedded`) services bundle broker and triplestore inside the addon container -- no external addons required. Data persisted to `/share/mosquitto` and `/share/fuseki`. Ingress-compatible with relative asset paths and `X-Ingress-Path` header support.
- **MCP server** -- `wactorz/mcp_server.py` exposes the actor system as an MCP (Model Context Protocol) server. Tools: `send_message`, `list_actors`, `get_actor_status`, `spawn_agent`, `stop_agent`. Resources: `wactorz://actors`, `wactorz://topics`. Configurable via `WACTORZ_MCP_*` env vars. Documented in `docs/interfaces.md`.
- **Unified persistence layer** -- `wactorz/core/persistence.py` introduces a 3-tier architecture replacing pickle-only storage: SQLite (`state/wactorz.db`) for durable structured data (spawn registry, pipeline rules, user facts, topic contracts, time-series), Redis for ephemeral fast-access data (falls back to in-memory), and Pickle for arbitrary Python objects (agent state dicts, ML models). `PersistenceAPI` provides backward-compatible `persist()`/`recall()` with automatic key-based routing. `migrate_from_pickle()` runs once on first startup to migrate existing state.
- **Time-series SQLite tables** -- `sensor_readings`, `detections`, `ha_state_changes`, and `actuations` tables with full-text and time-range query helpers (`query_sensor`, `query_detections`, `query_ha_states`, `query_actuations`). Automatic retention pruning via `prune_old_data(days=30)`.
- **Fuseki Channel ontology and MetricsBridge** -- `infra/fuseki/ontology/wactorz.ttl` extended with `af:Channel` class (`channelTopic`, `declaredSchema`, `observedSchema`, `triggersWhen`) and agent metrics properties. `FusekiClient.replace_agent_channels()` persists pub/sub topology to `urn:wactorz:channels`. `MetricsBridge` subscribes to `agents/+/metrics` MQTT and continuously updates agent metrics in the RDF graph via `upsert_agent_metrics()`.
- **Activity feed cap** -- UI activity feed is capped at 500 entries; an overflow banner appears when the limit is reached.
- **Cost metrics persistence and final publish** -- LLM cost and token metrics are persisted across restarts and published in the final heartbeat on actor stop.

### Changed

- **One-shot Home Assistant actuation timeouts** -- intent classification now allows up to 60 seconds, while the ephemeral `OneOffActuatorAgent` resolver and main actuation wait allow up to 120 seconds for slower local models such as Ollama.
- **Versioning** -- `wactorz/_version.py` remains the single source of truth; version handling unified across CLI, pyproject.toml, and the HA addon.

### Fixed

- **Ollama system prompts** -- `OllamaProvider` now sends `system_prompt` as the first `role=system` chat message for both blocking and streaming `/api/chat` calls, instead of relying on an undocumented top-level `system` payload field.
- **HA addon ingress** -- corrected `X-Ingress-Path` header name; relative paths used for favicon and manifest so the base tag resolves correctly behind the HA proxy; SPARQL proxy URLs now prepend the ingress path.
- **HA addon embedded Fuseki startup** -- `shiro.ini` is regenerated on every boot so credential changes apply immediately; correct dataset config and readiness wait added.
- **HA addon Docker layer cache** -- `BUILD_VERSION` arg now busts the Docker cache on version bumps; deprecated `build.yaml` removed; base image fixed to `ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.20`.
- **Catalog agent persistence** -- fixed catalog agent spawning and persistence after the persistence layer migration.
- **HA map agent `CancelledError`** -- handled `asyncio.CancelledError` in `HomeAssistantMapAgent` to prevent noisy tracebacks on shutdown.
- **Resource cleanup on stop** -- `Actor.on_stop()` now cancels background tasks and cleans up open resources more reliably.
- **Frontend URL resolution** -- unified backend URL resolution across Tauri desktop, HA addon, and plain browser: checks `window.__WACTORZ_API_PORT`, then `window.__WACTORZ_API_BASE`, then falls back to `window.location`.
- **CI: Linux system deps** -- added missing Linux system dependencies to the Rust test job.

### Tests

- Added focused `OllamaProvider` payload tests covering non-streaming and streaming system-prompt delivery.
- Added MCP server contract tests (`tests/test_mcp_server.py`); contract tests skip gracefully when optional MCP dependency is absent.

---

## [0.3.0] -- 2026-04-18

### Added

- **Telegram interface** -- new `--interface telegram` mode using `python-telegram-bot`; users self-host their own bot via a BotFather token. Supports `TELEGRAM_ALLOWED_USER_ID` to restrict access to a single user. The `/start` command replies with the user's numeric Telegram ID for easy setup.
- **`TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_USER_ID`** env vars added to `config.py` and `.env.example`
- **One-shot Home Assistant actuation** -- `MainActor` now classifies immediate device-control requests as `ACTUATE` and routes them to a new ephemeral `OneOffActuatorAgent` that resolves natural language to HA service calls, executes them, reports the result, tracks LLM cost, then unregisters, stops, and deletes its own persistence directory.
- **Prometheus monitoring for the Python runtime** -- the REST interface now exposes `GET /metrics` with Prometheus-formatted HTTP, actor, process, and LLM usage metrics via a shared `PrometheusMonitor` collector in `wactorz/monitoring/prometheus.py`.
- **Prometheus Compose services** -- `prometheus` and `blackbox-exporter` services added to `compose.yaml` and `compose.dev.yaml` for Python-stack monitoring. Optional Mosquitto and Fuseki availability probes are controlled via `PROMETHEUS_MONITOR_MOSQUITTO` and `PROMETHEUS_MONITOR_FUSEKI`.
- **Prometheus configuration assets** -- added templated config generation in `infra/prometheus/` including `prometheus.yml`, `render-config.sh`, `blackbox.yml`, and starter alert rules in `alerts.yml`.
- **Prometheus docs and tests** -- added `docs/prometheus.md`, linked it in the docs navigation, documented `GET /api/metrics`, and added focused tests for collector output, config generation, and REST content type handling.

### Changed

- **Discord interface** -- bot now responds to `@mention` instead of the `!` prefix for a more natural UX. Long responses are automatically split into 2000-character chunks to avoid Discord's message length limit.
- **Documentation** -- added README and agent reference coverage for `ACTUATE` intent routing and the new `OneOffActuatorAgent`.

---

## [0.2.0] -- 2026-03-13

### Added

- **IOAgent** -- MQTT gateway routing `io/chat` messages to the correct actor; replaces direct topic publishing
- **MQTT TCP bridge** in `monitor_server.py` -- `/mqtt` WebSocket endpoint now falls back to raw TCP (port 1883) when Mosquitto's WS listener (port 9001) is unavailable
- **Web UI auto-start** -- `wactorz` CLI spawns the monitor server as a quiet background asyncio task (`--no-monitor` to opt out, `--monitor-port` to override port 8888)
- **`/api/actors` REST endpoint** on Python monitor server -- returns live agent state from MQTT-derived in-memory store
- **`wactorz[all]` wheel** now bundles `static/app/` and `monitor.html` via hatchling `force-include`; custom build hook rebuilds frontend when stale
- **`wactorz/_version.py`** -- single source of version truth, imported by `__init__.py` and `pyproject.toml`
- **Rust WS bridge** -- `/mqtt` proxy route added alongside `/ws`; `WsBridge` now tracks MonitorState and broadcasts `full_snapshot`/`patch`/`delete_agent` to `/ws` clients
- **`scripts/build.py`** -- clean build script (hatchling + twine) with `--upload` flag for PyPI

### Fixed

- **`RangeError: invalid date`** -- Python heartbeat uses epoch seconds (`timestamp`); TypeScript normaliser now converts to ms automatically for both Python (snake_case) and Rust (camelCase) payloads
- **MQTT disconnect on listener error** -- `emit()` now wraps each listener call in try/catch; a throwing handler no longer crashes the MQTT connection
- **Chat infinite typing indicator** -- fixed key mismatch between `showTyping("main-actor")` and `hideTyping("io-agent")`; `IOManager` tracks `_lastTypingKey` and clears it on any reply
- **`llm_agent._handle_task`** -- `complete()` returns `(text, usage)` tuple; was incorrectly storing the whole tuple as message `content`, causing Anthropic 400 errors on the second conversation turn
- **CI test failures** -- `wactorz/` package was accidentally gitignored; restored source tracking and fixed test import paths for the new package layout
- **`/api/actors` 404** -- Python monitor server now serves actor list at this endpoint

### Changed

- `wactorz/__init__.py` -- optional agent imports (LLM, HA, ML) now wrapped in `try/except ImportError` so importing any submodule works without all optional deps installed
- Python payload normalisers centralised in `MQTTClient.ts` -- `normaliseHeartbeat`, `normaliseChat`, `normaliseStatus`
- Monitor server `_find_dir()` helper resolves `static/app` for both editable and installed-wheel layouts

---

## [0.1.0] -- 2025-11-01

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

[Unreleased]: https://github.com/waldiez/wactorz/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/waldiez/wactorz/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/waldiez/wactorz/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/waldiez/wactorz/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/waldiez/wactorz/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/waldiez/wactorz/releases/tag/v0.1.0
