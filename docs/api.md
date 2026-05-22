# API Reference

Wactorz exposes four integration surfaces: a REST API, a WebSocket bridge, MQTT pub/sub, and an optional MCP server.

---

## REST API  (`/api/`)

Base URL: `http://host/api/` (proxied by nginx from `:8080`)

### Actors

#### `GET /api/metrics`

Return Prometheus-formatted metrics for the Python Wactorz runtime.

**Response** `200 OK` with `Content-Type: text/plain; version=0.0.4; charset=utf-8`

This endpoint includes:

- HTTP request/response metrics for the Python REST interface
- actor runtime metrics from the Python registry
- LLM token and cost metrics
- process/runtime metrics from `prometheus_client`

---

#### `GET /api/actors`

List all registered actors.

**Response**
```json
[
  {
    "id":        "01JQND5X-a1b2c3d4",
    "name":      "main-actor",
    "state":     "running",
    "protected": true,
    "agentType": "orchestrator"
  }
]
```

---

#### `GET /api/actors/:id`

Get a single actor by ID.

**Response** — same shape as a single entry from `GET /api/actors`

---

#### `POST /api/actors/:id/pause`

Pause a running actor.

**Response** `200 OK` on success, `404` if not found, `403` if protected.

---

#### `POST /api/actors/:id/resume`

Resume a paused actor.

**Response** `200 OK` on success.

---

#### `DELETE /api/actors/:id`

Stop and remove an actor.

**Response** `200 OK` on success, `404` if not found, `403` if protected.

---

### Chat

#### `POST /api/chat`

Send a message to an actor.

**Request body**
```json
{
  "to":      "main-actor",
  "content": "What is the weather in Paris?"
}
```

**Response** `202 Accepted` — message queued.  The reply arrives asynchronously via MQTT `agents/{id}/chat`.

---

### Cost Management

#### `GET /api/cost`

Return current LLM spend, the active period, and the configured limit.

**Response** `200 OK`
```json
{
  "period":        "daily",
  "period_key":    "2026-05-12",
  "spend_usd":     0.0067,
  "limit_usd":     0.70,
  "pct_used":      0.96,
  "limit_reached": false,
  "warning":       false
}
```

`limit_usd` is `null` when no limit is set. `pct_used` is `null` when there is no limit.

---

#### `POST /api/cost/limit`

Set or update the spend limit at runtime (persists across restarts, overrides env var).

**Request body**
```json
{ "limit_usd": 0.70, "period": "daily" }
```

`period` must be `"daily"`, `"weekly"`, or `"monthly"`. Set `limit_usd` to `0` to disable enforcement.

**Response** `200 OK` with the updated cost info object (same shape as `GET /api/cost`).

---

#### `POST /api/cost/reset`

Clear accumulated spend for all periods (daily, weekly, monthly). Useful after changing the limit or correcting inflated counters.

**Response** `200 OK` with the reset cost info object.

---

### Home Assistant Map

#### `GET /ha-map`

Return the latest cached Home Assistant device map snapshot from `HomeAssistantMapAgent`.

**Response** `200 OK`
```json
{
  "type": "home_assistant_map_update",
  "event_type": "entity_registry_updated",
  "timestamp": 1234567890.0,
  "event": {},
  "devices": []
}
```

**Response** `404 Not Found`
```json
{
  "error": "Home Assistant map snapshot not available"
}
```

---

## WebSocket Bridge  (`/ws`)

Connect: `ws://host/ws`

After connection the server streams every MQTT message as a JSON object:

```json
{
  "topic":   "agents/01JQND5X-a1b2c3d4/heartbeat",
  "payload": {
    "agentId":   "01JQND5X-a1b2c3d4",
    "agentName": "main-actor",
    "state":     "running",
    "timestampMs": 1709500000000
  }
}
```

---

## MQTT

Broker: `mosquitto:1883` (TCP, internal) / `ws://host/mqtt` (WebSocket via nginx)

All payloads are **camelCase JSON**.

### Topic reference

#### `agents/{id}/spawn`

Published by each agent in `on_start()`.

```json
{
  "agentId":     "01JQND5X-a1b2c3d4",
  "agentName":   "main-actor",
  "agentType":   "orchestrator",
  "timestampMs": 1709500000000
}
```

---

#### `agents/{id}/heartbeat`

Published every `heartbeat_interval_secs` (default 10 s).

```json
{
  "agentId":     "01JQND5X-a1b2c3d4",
  "agentName":   "main-actor",
  "state":       "running",
  "timestampMs": 1709500000000
}
```

---

#### `agents/{id}/status`

Published on state changes.

```json
{
  "agentId":     "01JQND5X-a1b2c3d4",
  "state":       "paused",
  "timestampMs": 1709500000000
}
```

---

#### `agents/{id}/alert`

Published by MonitorAgent (stale actor) or QAAgent (policy violation).

```json
{
  "agentId":     "01JQND5X-a1b2c3d4",
  "severity":    "error",
  "message":     "Agent has not sent a heartbeat in 60s",
  "timestampMs": 1709500000000
}
```

`severity` values: `info` | `warning` | `error` | `critical`

---

#### `agents/{id}/chat`

Chat message to or from an agent.

```json
{
  "id":          "WID-abc123",
  "from":        "main-actor",
  "to":          "user",
  "content":     "Here is the weather forecast…",
  "timestampMs": 1709500000000
}
```

---

#### `system/health`

Published by MonitorAgent on every heartbeat tick.

```json
{
  "agentCount":  6,
  "staleAgents": [],
  "timestampMs": 1709500000000
}
```

---

#### `system/spawn`

Published when a DynamicAgent is created (alias for `agents/{id}/spawn` on the `system/` prefix).

---

#### `io/chat`  ← inbound from browser

The fixed topic the frontend IO bar publishes to.

```json
{
  "from":        "user",
  "content":     "@nautilus-agent ping deploy@myserver.com",
  "timestampMs": 1709500000000
}
```

The MQTT event loop routes this to IOAgent's mailbox, which parses the `@mention` and forwards the message body to the target actor.

---

## Error handling

| HTTP status | Meaning |
|---|---|
| `200` | Success |
| `202` | Accepted (async, e.g. chat) |
| `404` | Actor not found |
| `403` | Actor is protected |
| `500` | Internal server error |

MQTT errors are published as `agents/{id}/alert` with `severity: error`.

---

## MCP Server

The optional MCP server lives at `wactorz.interfaces.mcp_server` and is exposed by the `wactorz-mcp` console script when `wactorz[mcp]` is installed. It uses stdio transport and calls the Wactorz REST API configured by `WACTORZ_URL`.

```bash
wactorz --interface rest --port 8000
WACTORZ_URL=http://localhost:8000 wactorz-mcp
```

If the script is unavailable in an editable checkout:

```bash
python -m wactorz.interfaces.mcp_server
```

### Environment

| Variable | Description |
|---|---|
| `WACTORZ_URL` | Base URL for the Wactorz REST API. Defaults to `http://localhost:8000`. |
| `WACTORZ_API_KEY` | Optional API key sent to Wactorz REST as `X-API-Key`. |
| `HA_URL` | Optional Home Assistant base URL for direct HA tools. |
| `HA_TOKEN` | Optional Home Assistant long-lived access token. |

### Tools

| Tool | Backend |
|---|---|
| `ask_wactorz` | `POST /chat` |
| `ask_agent` | `POST /chat` with `agent_name` |
| `list_agents` | `GET /agents` |
| `list_capabilities` | `POST /chat` with `/capabilities` |
| `stop_agent` | `DELETE /actors/{agent_id}` |
| `pause_agent` | `POST /actors/{agent_id}/pause` |
| `resume_agent` | `POST /actors/{agent_id}/resume` |
| `ha_list_entities` | Home Assistant `GET /api/states` |
| `ha_get_state` | Home Assistant `GET /api/states/{entity_id}` |
| `ha_call_service` | Home Assistant `POST /api/services/{domain}/{service}` |

### Resources

| Resource | Backend |
|---|---|
| `wactorz://agents` | `GET /agents` |
| `wactorz://capabilities` | `POST /chat` with `/capabilities` |
| `wactorz://ha-map` | `GET /ha-map` |
| `wactorz://config` | local sanitized config |
