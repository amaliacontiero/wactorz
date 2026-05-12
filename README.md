# Wactorz

**Spawn, coordinate and monitor AI agents at runtime -- just by talking to them.**

Wactorz is an open-source, actor-model multi-agent framework built for the real world. You describe what you need. The LLM writes the code. A new agent appears -- persisted, self-healing, and connected to everything else via MQTT. No restart. No YAML. No hardcoded types.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![MQTT](https://img.shields.io/badge/transport-MQTT-purple.svg)](https://mosquitto.org)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-addon-41BDF5.svg)](ha-addon/DOCS.md)

---

## See it in action

```
You:       monitor my kitchen temperature and alert me on Discord if it goes above 28°C

Wactorz:   Understood. I'll create two agents for this.

           [spawning temp-monitor-agent  -- polls sensors/temperature every 30s]
           [spawning discord-notify-agent -- sends alert when threshold is crossed]

           Both agents are live. They'll survive a restart automatically.
```

That's it. No config files, no code changes, no service restart.

---

## Why Wactorz?

Frameworks like LangGraph, CrewAI, and AutoGen are designed for the cloud. Wactorz is designed for the physical world.

| | Wactorz | LangGraph / CrewAI / AutoGen |
|---|---|---|
| Spawn agents at runtime | Yes -- from natural language | No -- types defined at code time |
| MQTT / IoT native | Yes -- MQTT is the core bus | No |
| Runs on a Raspberry Pi | Yes | No |
| Works fully offline | Yes (Ollama) | Cloud-dependent |
| Home Assistant built-in | Yes -- native HA Supervisor addon | No |
| Actor model supervision | Yes -- Erlang-style OTP restarts | No |
| Multi-machine edge deployment | Yes -- SSH-bootstrap remote nodes | No |
| LLM cost tracking | Yes -- per-agent, across restarts | Varies |

---

## Quick start

```bash
git clone https://github.com/waldiez/wactorz
cd wactorz
pip install -e ".[all]"

# Mosquitto broker (required -- pick one)
docker run -d -p 1883:1883 eclipse-mosquitto   # Docker
# mosquitto -v                                 # or native install

# Set your LLM key
export ANTHROPIC_API_KEY=sk-ant-...

python -m wactorz
```

Open **http://localhost:8888** for the live dashboard.

**No API key? Use Ollama (free, local, offline):**

```bash
ollama pull llama3
python -m wactorz --llm ollama --ollama-model llama3
```

> Windows user? See [docs/windows.md](docs/windows.md) for a one-click setup script.

---

## What it does

### Reactive pipelines -- describe a rule, agents wire themselves

```
if the front door opens, send me a Telegram message
when a person is detected on my webcam, turn on the hallway light
whenever the living room temperature drops below 18°C, turn on the heater
```

Wactorz classifies the intent, queries your Home Assistant for real entity IDs, generates the agent code, spawns the actors, and registers the rule -- so it restores automatically on the next restart.

### Home Assistant -- natural language device control

```
turn off all the lights in the bedroom
set the thermostat to 22 degrees
create an automation: when the sun sets, dim the living room to 40%
what sensors do I have in the kitchen?
```

Install as a **Home Assistant Supervisor addon** for zero-config integration. No external server needed.

### Remote nodes -- spawn agents on any machine

```
/deploy rpi-kitchen
spawn a temperature sensor on rpi-kitchen that reads from a DHT22 every 30 seconds
```

One Python file, one pip package. The node self-bootstraps over SSH and appears in the dashboard within seconds. Agents on remote nodes have the same API as local agents.

### Actor model -- built to survive

Every agent runs in its own async actor with its own mailbox, heartbeat, and persisted state. An Erlang-style supervisor watches every actor and restarts failed ones automatically, with configurable backoff and restart caps. Crashes are events -- not catastrophes.

### LLM cost tracking -- know what you're spending

Every LLM call across every agent is tracked: input tokens, output tokens, cost in USD. Visible per-agent in the dashboard, in the CLI via `/cost`, and queryable via the REST API. Cost data survives restarts.

---

## LLM providers

| Provider | Env var | Notes |
|---|---|---|
| Anthropic Claude | `ANTHROPIC_API_KEY` | Default |
| OpenAI | `OPENAI_API_KEY` | |
| Google Gemini | `GEMINI_API_KEY` | Free tier -- [aistudio.google.com](https://aistudio.google.com) |
| NVIDIA NIM | `NIM_API_KEY` | Free tier (1000 req/month) -- [build.nvidia.com](https://build.nvidia.com) |
| Ollama | _(none)_ | Local models, fully offline |

---

## Interfaces

| Interface | How |
|---|---|
| CLI (streaming) | `python -m wactorz` |
| Live dashboard | `http://localhost:8888` -- agent cards, logs, cost meters, spawn controls |
| REST API | `python -m wactorz --interface rest` |
| Discord | `--interface discord` -- bot responds to @mention |
| Telegram | `--interface telegram` -- self-hosted bot, no public server needed |
| MCP server | `wactorz-mcp` -- expose Wactorz as tools to any MCP-compatible client |
| Flutter app | iOS/Android companion app -- agents, chat, activity feed |
| Home Assistant addon | One-click install, runs inside the HA Supervisor |

---

## Architecture

```
You  (chat / REST / Discord / Telegram / HA)
 |
[MainActor]  -- classifies intent in one LLM call
  |
  +-- ACTUATE  --> OneOffActuatorAgent  --> HA service call
  |
  +-- PIPELINE --> PlannerAgent  --> spawns agents --> MQTT wiring
  |
  +-- HA       --> HomeAssistantAgent  --> HA REST / WebSocket
  |
  +-- OTHER    --> streaming LLM reply

All agents <--> [Mosquitto MQTT broker] <--> Dashboard / Remote nodes / Home Assistant
```

Each agent publishes a heartbeat every 10 seconds. The `MonitorAgent` watches for stale heartbeats and escalates failures through warning, restart, and user notification stages. All state is written to SQLite on every change -- not just on graceful shutdown.

---

## Documentation

| | |
|---|---|
| [Quickstart](docs/quickstart.md) | Windows setup script and first run |
| [Architecture](docs/architecture.md) | Actor model, TopicBus, intent routing |
| [Agents](docs/agents.md) | All built-in agents and their APIs |
| [Pipelines](docs/pipelines.md) | Reactive pipeline patterns and wiring |
| [Remote nodes](docs/remote-nodes.md) | Edge deployment over SSH |
| [Interfaces](docs/interfaces.md) | CLI, REST, Discord, Telegram, MCP |
| [API reference](docs/api.md) | REST endpoints |
| [Deployment](docs/deployment.md) | Docker, native binary, systemd, HA addon |
| [HA Addon](ha-addon/DOCS.md) | Home Assistant Supervisor addon |
| [Technical reference](docs/reference.md) | Deep-dive agent internals and APIs |

---

## Contributing

Contributions are welcome -- new agents, bug fixes, new LLM providers, docs, translations.

See [CONTRIBUTING.md](CONTRIBUTING.md) to get started. For questions and ideas, open an issue or start a GitHub Discussion.

---

## License

[Apache 2.0](LICENSE) -- free to use, modify, and distribute.
