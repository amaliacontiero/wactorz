"""
Wactorz Monitor — WebSocket dashboard + optional MQTT bridge.

Chat routing modes (set via registry wiring in cli.py):
  direct_ws  — registry is set; chat goes straight to actors over WebSocket.
               No IOAgent, no MQTT round-trip for user messages.
  mqtt       — registry is None; chat goes through IOAgent via MQTT (legacy).

The mode is advertised to the browser on connect via a {"type":"config"} frame
so the frontend knows whether to send chat over /ws or publish to io/chat.
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import logging
import socket
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

MQTT_BROKER  = "localhost"
MQTT_PORT    = 1883
MQTT_WS_PORT = 9001
WS_PORT      = 8888
MQTT_TOPICS  = ["agents/#", "system/#", "nodes/#", "io/chat"]

# Injected by cli.py after the actor system is built.
# None  → legacy MQTT/IOAgent mode
# <registry> → direct mode (Option B)
registry = None

# Injected by cli.py — used to query historical cost data for deleted agents.
db = None

IO_GATEWAY_ID = "io-gateway"

state = {
    "agents":        {},
    "nodes":         {},
    "alerts":        [],
    "system_health": {},
    "log_feed":      [],
}

ws_clients: set = set()
mqtt_client_ref = None


# ── helpers ────────────────────────────────────────────────────────────────

def _chat_mode() -> str:
    return "direct_ws" if registry is not None else "mqtt"


def _find_main():
    return registry.find_by_name("main") if registry else None


def _parse_mention(content: str) -> tuple[str, str]:
    if content.startswith("@"):
        parts = content[1:].split(None, 1)
        return parts[0], (parts[1].strip() if len(parts) > 1 else "")
    return "main", content


def update_agent(agent_id: str, key: str, data):
    if agent_id not in state["agents"]:
        state["agents"][agent_id] = {
            "agent_id":   agent_id,
            "name":       agent_id[:8],
            "first_seen": time.time(),
        }
    state["agents"][agent_id][key] = data
    state["agents"][agent_id]["last_update"] = time.time()


def add_log(entry: dict):
    state["log_feed"].insert(0, entry)
    if len(state["log_feed"]) > 100:
        state["log_feed"].pop()


async def broadcast(msg: dict):
    if not ws_clients:
        return
    payload = json.dumps(msg)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_str(payload)
        except Exception as e:
            logger.warning(f"[broadcast] WS send failed: {e}")
            dead.add(ws)
    ws_clients.difference_update(dead)


# ── slash commands ─────────────────────────────────────────────────────────
# Every handler receives a `reply_fn` coroutine — callers supply either an
# MQTT publisher or a WebSocket sender.  No global state, no monkey-patching.

async def _slash_deploy(node: str, host: str, user: str, pw: str, broker: str,
                        reply_fn):
    if not host:
        await reply_fn(f"[discover] Searching for '{node}' on the network...")
        discovered = None
        for candidate in [f"{node}.local", "raspberrypi.local",
                          f"{node.replace('-', '')}.local"]:
            try:
                ip = await asyncio.get_event_loop().run_in_executor(
                    None, socket.gethostbyname, candidate
                )
                discovered = ip
                await reply_fn(f"[discover] Found via mDNS: {candidate} → {ip}")
                break
            except socket.gaierror:
                pass

        if not discovered:
            try:
                local_ip = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: socket.gethostbyname(socket.gethostname())
                )
                subnet = ".".join(local_ip.split(".")[:3])
            except Exception:
                subnet = "192.168.1"
            await reply_fn(f"[discover] mDNS not found. Scanning {subnet}.1-254 for SSH...")
            found = await _scan_subnet_ssh(subnet)
            if found:
                hosts = "\n".join(f"  {ip}" for ip in found)
                await reply_fn(
                    f"[discover] Found {len(found)} host(s):\n{hosts}\n\n"
                    f"Re-run with:\n  /deploy {node} <host> <user> <password> [broker]"
                )
            else:
                await reply_fn(
                    f"[discover] No SSH hosts found.\n"
                    f"  /deploy {node} <host> <user> <password> [broker]"
                )
        else:
            await reply_fn(
                f"[discover] Host: {discovered}\n"
                f"Re-run with credentials:\n"
                f"  /deploy {node} {discovered} <user> <password> [broker]"
            )
        return

    if not user or not pw:
        await reply_fn(
            f"[deploy] Need SSH credentials:\n"
            f"  /deploy {node} {host} <user> <password> [broker]"
        )
        return

    main = _find_main()
    if main is None or not hasattr(main, "delegate_to_installer"):
        await reply_fn("[error] Installer agent not available.")
        return

    broker = broker or "localhost"
    await reply_fn(f"[deploy] Deploying to {user}@{host} as '{node}'... (20-60s)")
    result = await main.delegate_to_installer({
        "action": "node_deploy", "host": host, "user": user,
        "password": pw, "node_name": node, "broker": broker,
    }, timeout=120.0)

    if result.get("success"):
        await reply_fn(
            f"[OK] Node '{node}' is live!\n"
            f"  \"spawn a CPU monitor agent on {node}\""
        )
    else:
        await reply_fn(f"[FAIL] {result.get('error', result)}")


async def _scan_subnet_ssh(subnet: str) -> list:
    found = []
    sem   = asyncio.Semaphore(60)

    async def probe(ip):
        async with sem:
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection(ip, 22), timeout=0.4)
                w.close()
                try:
                    await w.wait_closed()
                except Exception:
                    pass
                found.append(ip)
            except Exception:
                pass

    await asyncio.gather(*[probe(f"{subnet}.{i}") for i in range(1, 255)])
    return sorted(found, key=lambda x: int(x.split(".")[-1]))


async def handle_slash(text: str, reply_fn) -> bool:
    """
    Dispatch a slash command. Returns True if recognised.
    `reply_fn` is an async callable that sends a string back to the user.
    """
    parts = text.split()
    cmd   = parts[0].lower()

    if cmd in ("/help", "/h"):
        await reply_fn(
            "Commands:\n"
            "  /agents                        list all active agents\n"
            "  /nodes                         list remote nodes\n"
            "  /migrate <agent> <node>        move an agent to a different node\n"
            "  /deploy <node> [host [user [pw [broker]]]]\n"
            "                                 deploy a remote Wactorz node\n"
            "  /clear-plans                   clear the plan cache\n\n"
            "Everything else goes to the main orchestrator."
        )
        return True

    if cmd == "/clear-plans":
        main = _find_main()
        if main and hasattr(main, "persist"):
            main.persist("_plan_cache", {})
        await reply_fn("[System: Plan cache cleared.]")
        return True

    if cmd == "/agents":
        if registry is None:
            await reply_fn("[agents] Registry not available.")
            return True
        lines = []
        for actor in registry.all_actors():
            status    = actor.get_status() if hasattr(actor, "get_status") else {}
            st        = status.get("state", "?")
            protected = " [protected]" if getattr(actor, "protected", False) else ""
            node      = f" [{status['node']}]" if status.get("node") else ""
            lines.append(f"  [{st:8s}] @{actor.name:<22s} {actor.actor_id[:8]}{protected}{node}")
        await reply_fn("Agents:\n" + "\n".join(lines) if lines else "No agents running.")
        return True

    if cmd == "/nodes":
        main         = _find_main()
        remote_nodes = main.list_nodes() if (main and hasattr(main, "list_nodes")) else []
        local        = [a.name for a in registry.all_actors()] if registry else []
        lines = [f"  {'local':20s} online   {', '.join('@'+n for n in local) or '(none)'}"]
        for nd in sorted(remote_nodes, key=lambda x: x["node"]):
            st    = "online" if nd["online"] else "OFFLINE"
            names = ", ".join("@" + n for n in nd["agents"]) or "(no agents)"
            lines.append(f"  {nd['node']:20s} {st:6s}   {names}")
        if not remote_nodes:
            lines.append("  (no remote nodes — /deploy <node-name>)")
        await reply_fn("Nodes:\n" + "\n".join(lines))
        return True

    if cmd == "/migrate":
        if len(parts) < 3:
            await reply_fn("[usage] /migrate <agent-name> <target-node>")
            return True
        main = _find_main()
        if main is None or not hasattr(main, "migrate_agent"):
            await reply_fn("[error] migrate_agent not available.")
            return True
        await reply_fn(f"[migrating] @{parts[1]} → {parts[2]}...")
        result = await main.migrate_agent(parts[1], parts[2])
        sym = "OK" if result.get("success") else "FAIL"
        await reply_fn(f"[{sym}] {result.get('message', str(result))}")
        return True

    if cmd == "/deploy":
        if len(parts) < 2:
            await reply_fn("[usage] /deploy <node-name> [host [user [password [broker]]]]")
            return True
        await _slash_deploy(
            node   = parts[1],
            host   = parts[2] if len(parts) > 2 else "",
            user   = parts[3] if len(parts) > 3 else "",
            pw     = parts[4] if len(parts) > 4 else "",
            broker = parts[5] if len(parts) > 5 else "",
            reply_fn = reply_fn,
        )
        return True

    return False


async def _route_chat(content: str, reply_fn, stream_fn=None, stream_end_fn=None):
    """Core chat routing — slash commands, @mentions, or main-actor stream.

    reply_fn(text)        — send a complete message (slash commands, errors)
    stream_fn(chunk)      — send one streaming chunk (optional; falls back to reply_fn)
    stream_end_fn()       — signal that streaming is done (optional)
    """
    _chunk_fn = stream_fn or reply_fn
    _end_fn   = stream_end_fn or (lambda: None)

    if content.startswith("/"):
        handled = await handle_slash(content, reply_fn)
        if not handled:
            await reply_fn("Unknown command. Type /help for available commands.")
        return

    target_name, text = _parse_mention(content)
    target = registry.find_by_name(target_name) if registry else None
    if target is None:
        await reply_fn(f"Agent @{target_name} not found.")
        return

    logger.info(f"[io-gateway] → {target.name}: {text[:60]!r}")

    gen_fn = (
        getattr(target, "process_user_input_stream", None)
        or getattr(target, "chat_stream", None)
    )
    if gen_fn:
        try:
            async for chunk in gen_fn(text):
                if isinstance(chunk, dict):
                    continue
                await _chunk_fn(str(chunk))
        finally:
            await _end_fn()
    elif hasattr(target, "process_user_input"):
        result = await target.process_user_input(text)
        await reply_fn(str(result))
        await _end_fn()


# ── MQTT chat handler (legacy / IOAgent-less fallback) ─────────────────────

async def handle_chat_mqtt(data: dict):
    """Called when io/chat arrives via MQTT and registry is wired in."""
    if registry is None:
        return  # IOAgent handles it
    content = (data.get("content") or "").strip()
    if not content:
        return

    async def mqtt_reply(text: str):
        global mqtt_client_ref
        if mqtt_client_ref:
            await mqtt_client_ref.publish(
                f"agents/{IO_GATEWAY_ID}/chat",
                json.dumps({
                    "from":      IO_GATEWAY_ID,
                    "to":        "user",
                    "content":   text,
                    "timestamp": time.time(),
                }),
            )

    await _route_chat(content, mqtt_reply)  # MQTT path: no streaming, reply_fn used for all output


# ── WebSocket handler ──────────────────────────────────────────────────────

async def ws_handler(request):
    from aiohttp import web, WSMsgType
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    logger.info(f"WebSocket client connected. Total: {len(ws_clients)}")

    # Send initial state
    await ws.send_str(json.dumps({"type": "full_snapshot", "state": _snapshot()}))

    # Advertise chat mode so the frontend knows where to send messages
    await ws.send_str(json.dumps({"type": "config", "chat_mode": _chat_mode()}))

    # Per-connection accumulator for streamed assistant replies.
    # We only persist once at stream_end so chat_log gets one row per turn
    # with the full content, not a row per chunk.
    _stream_buffer: list[str] = []

    def _persist_chat(role: str, content: str, agent_name: str = "main") -> None:
        """Best-effort write to chat_log. Never raises into the WS path."""
        if db is None or not content:
            return
        try:
            db.write_chat_log(
                ts=time.time(),
                agent_name=agent_name,
                role=role,
                content=content,
            )
        except Exception as exc:
            logger.warning(f"[ws] chat_log write failed: {exc}")

    async def ws_reply(text: str):
        try:
            await ws.send_str(json.dumps({
                "type":      "chat",
                "from":      IO_GATEWAY_ID,
                "content":   text,
                "timestamp": time.time(),
            }))
            # Non-streamed replies (slash command output, errors, system
            # messages) — persist immediately.
            _persist_chat("assistant", text)
        except Exception:
            pass

    async def ws_stream_chunk(chunk: str):
        try:
            await ws.send_str(json.dumps({
                "type":      "stream_chunk",
                "from":      IO_GATEWAY_ID,
                "content":   chunk,
                "timestamp": time.time(),
            }))
            # Buffer for end-of-stream persistence; do NOT write per chunk.
            if chunk:
                _stream_buffer.append(chunk)
        except Exception:
            pass

    async def ws_stream_end():
        try:
            await ws.send_str(json.dumps({
                "type":      "stream_end",
                "from":      IO_GATEWAY_ID,
                "timestamp": time.time(),
            }))
            # Now persist the full assembled assistant turn — once.
            if _stream_buffer:
                full = "".join(_stream_buffer)
                _stream_buffer.clear()
                _persist_chat("assistant", full)
        except Exception:
            # Even if the send_str failed, flush anything we accumulated
            # so the user's session isn't lost on a transient ws hiccup.
            if _stream_buffer:
                full = "".join(_stream_buffer)
                _stream_buffer.clear()
                _persist_chat("assistant", full)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data     = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "command":
                        await handle_command(data)

                    elif msg_type == "chat":
                        content = (data.get("content") or "").strip()
                        if content and registry is not None:
                            # Persist the user's turn first so chat_log has the
                            # request even if the assistant reply errors out.
                            _persist_chat("user", content)
                            async def _safe_route(c=content):
                                try:
                                    await _route_chat(c, ws_reply,
                                                      stream_fn=ws_stream_chunk,
                                                      stream_end_fn=ws_stream_end)
                                except Exception as exc:
                                    logger.error(f"[ws] chat error: {exc}", exc_info=True)
                                    try:
                                        await ws_reply(f"[error] {exc}")
                                        await ws_stream_end()
                                    except Exception:
                                        pass
                            asyncio.create_task(_safe_route())
                        elif content:
                            # No registry — tell the browser to use MQTT
                            await ws_reply("[system] Chat not available over WebSocket in this mode.")

                except Exception as e:
                    logger.warning(f"[ws] Bad message: {e}")
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        ws_clients.discard(ws)
        logger.info(f"WebSocket client disconnected. Total: {len(ws_clients)}")
    return ws


# ── MQTT infrastructure ────────────────────────────────────────────────────

async def handle_command(cmd: dict):
    global mqtt_client_ref
    command  = cmd.get("command")
    agent_id = cmd.get("agent_id")
    if not command or not agent_id:
        return
    if command not in {"pause", "stop", "resume", "delete"}:
        return

    logger.info(f"[cmd] {command.upper()} -> {agent_id[:8]}")
    if not mqtt_client_ref:
        logger.warning("[cmd] No MQTT client available")
        return

    payload = json.dumps({"command": command, "sender": "monitor-dashboard", "timestamp": time.time()})
    try:
        await mqtt_client_ref.publish(f"agents/{agent_id}/commands", payload)
        add_log({"type": "command", "agent_id": agent_id, "command": command, "timestamp": time.time()})
        if command in ("stop", "pause", "resume"):
            state["agents"].get(agent_id, {})["state"] = (
                "stopped" if command == "stop" else
                "paused"  if command == "pause" else "running"
            )
            await broadcast({"type": "patch", "state": _snapshot()})
        elif command == "delete":
            state["agents"].pop(agent_id, None)
            await broadcast({"type": "delete_agent", "agent_id": agent_id, "state": _snapshot()})
    except Exception as e:
        logger.error(f"[cmd] Publish failed: {e}")


def parse_topic(topic: str, payload_str: str):
    try:
        data = json.loads(payload_str)
    except Exception:
        data = payload_str

    parts = topic.split("/")

    if parts[0] == "system" and len(parts) >= 2:
        if parts[1] == "health":
            state["system_health"] = data
        elif parts[1] == "alerts":
            state["alerts"].insert(0, data)
            if len(state["alerts"]) > 50:
                state["alerts"].pop()
        return {"type": "system", "subtype": parts[1], "data": data}

    if parts[0] == "agents" and len(parts) >= 3:
        agent_id = parts[1]
        metric   = parts[2]

        if metric == "status":
            update_agent(agent_id, "status", data)
            if isinstance(data, dict):
                if "name"      in data: state["agents"][agent_id]["name"]      = data["name"]
                if "state"     in data: state["agents"][agent_id]["state"]     = data["state"]
                if "protected" in data: state["agents"][agent_id]["protected"] = data["protected"]
            add_log({"type": "status", "agent_id": agent_id, "status": data, "timestamp": time.time()})

        elif metric == "heartbeat":
            update_agent(agent_id, "heartbeat", data)
            if isinstance(data, dict):
                ag = state["agents"][agent_id]
                ag["name"]  = data.get("name",      agent_id[:8])
                ag["cpu"]   = data.get("cpu",        0)
                ag["mem"]   = data.get("memory_mb",  0)
                ag["task"]  = data.get("task",       "idle")
                ag["state"] = data.get("state",      "unknown")
            logger.info(f"[MQTT] Heartbeat: {state['agents'][agent_id].get('name', agent_id[:8])}")

        elif metric == "metrics":
            update_agent(agent_id, "metrics", data)
            if isinstance(data, dict):
                state["agents"][agent_id]["messages_processed"] = data.get("messages_processed", 0)
                if "cost_usd" in data:
                    state["agents"][agent_id]["cost_usd"]      = data.get("cost_usd", 0.0)
                    state["agents"][agent_id]["input_tokens"]  = data.get("input_tokens", 0)
                    state["agents"][agent_id]["output_tokens"] = data.get("output_tokens", 0)

        elif metric == "logs":
            add_log({"type": "log", "agent_id": agent_id, "timestamp": time.time(),
                     **(data if isinstance(data, dict) else {})})
        elif metric == "spawned":
            add_log({"type": "spawned", "agent_id": agent_id, "timestamp": time.time(),
                     **(data if isinstance(data, dict) else {})})
        elif metric == "completed":
            update_agent(agent_id, "last_completed", data)
            add_log({"type": "completed", "agent_id": agent_id, "timestamp": time.time()})
        elif metric == "alert":
            if isinstance(data, dict):
                data["agent_id"] = agent_id
                data.setdefault("name", state["agents"].get(agent_id, {}).get("name", agent_id[:8]))
            state["alerts"].insert(0, data if isinstance(data, dict) else {"agent_id": agent_id})
            if len(state["alerts"]) > 50:
                state["alerts"].pop()
            name     = state["agents"].get(agent_id, {}).get("name", agent_id[:8])
            severity = data.get("severity", "warning") if isinstance(data, dict) else "warning"
            add_log({"type": "alert", "agent_id": agent_id, "name": name,
                     "message": f"{name} unresponsive ({severity})", "timestamp": time.time()})

        return {"type": "agent", "agent_id": agent_id, "metric": metric, "data": data}

    if parts[0] == "nodes" and len(parts) >= 3 and parts[2] == "heartbeat":
        node_name = parts[1]
        if isinstance(data, dict):
            state["nodes"][node_name] = {
                "node":      node_name,
                "agents":    data.get("agents", []),
                "last_seen": time.time(),
                "online":    True,
                "node_id":   data.get("node_id", ""),
            }
            logger.info(f"[MQTT] Node heartbeat: {node_name} | agents: {data.get('agents', [])}")
            return {"type": "node", "node_name": node_name, "data": data}

    return None


def _node_online(last_seen: float) -> bool:
    return (time.time() - last_seen) < 45


def _historical_cost_usd(live_names: set) -> float:
    """Sum _final_cost for agents not in live_names."""
    if db is None:
        return 0.0
    try:
        import json as _json
        rows = db.conn.execute(
            "SELECT value FROM kv_store WHERE key = '_final_cost'"
        ).fetchall()
        total = 0.0
        for row in rows:
            try:
                entry = _json.loads(row[0])
                if entry.get("name") not in live_names:
                    total += entry.get("cost_usd", 0.0)
            except Exception:
                pass
        return total
    except Exception:
        return 0.0


def _historical_messages(live_names: set) -> int:
    """Sum _messages_processed for agents not in live_names."""
    if db is None:
        return 0
    try:
        import json as _json
        rows = db.conn.execute(
            "SELECT agent, value FROM kv_store WHERE key = '_messages_processed'"
        ).fetchall()
        total = 0
        for agent_name, value in rows:
            if agent_name not in live_names:
                try:
                    entry = _json.loads(value)
                    total += entry.get("count", 0)
                except Exception:
                    pass
        return total
    except Exception:
        return 0


def _snapshot() -> dict:
    for nd in state["nodes"].values():
        nd["online"] = _node_online(nd.get("last_seen", 0))

    # Prefer MQTT-derived data from state["agents"]; fall back to live actor
    # objects for the window between restart and first MQTT heartbeat (0.5s).
    if registry is not None:
        live_names = {a.name for a in registry.all_actors()}
        live_cost = sum(
            state["agents"].get(a.actor_id, {}).get("cost_usd")
            or getattr(a, "total_cost_usd", 0.0)
            for a in registry.all_actors()
        )
        live_msgs = sum(
            state["agents"].get(a.actor_id, {}).get("messages_processed")
            or getattr(getattr(a, "metrics", None), "messages_processed", 0)
            for a in registry.all_actors()
        )
    else:
        live_names = {a.get("name", "") for a in state["agents"].values()}
        live_cost = sum(a.get("cost_usd", 0.0) for a in state["agents"].values())
        live_msgs = sum(a.get("messages_processed", 0) for a in state["agents"].values())

    total_cost = live_cost + _historical_cost_usd(live_names)
    total_msgs = live_msgs + _historical_messages(live_names)
    return {
        "agents":           list(state["agents"].values()),
        "nodes":            list(state["nodes"].values()),
        "alerts":           state["alerts"][:10],
        "log_feed":         state["log_feed"][:20],
        "system_health":    state["system_health"],
        "total_cost_usd":   round(total_cost, 6),
        "total_messages":   total_msgs,
    }


async def mqtt_listener():
    global mqtt_client_ref
    try:
        import aiomqtt
    except ImportError:
        logger.error("aiomqtt not installed: pip install aiomqtt")
        return

    logger.info(f"Connecting to MQTT {MQTT_BROKER}:{MQTT_PORT}...")
    try:
        while True:
            try:
                async with aiomqtt.Client(MQTT_BROKER, MQTT_PORT) as client:
                    mqtt_client_ref = client
                    logger.info("MQTT connected.")

                    if registry is not None:
                        await client.publish(
                            f"agents/{IO_GATEWAY_ID}/spawn",
                            json.dumps({
                                "agentId":   IO_GATEWAY_ID,
                                "agentName": IO_GATEWAY_ID,
                                "agentType": "gateway",
                                "timestamp": time.time(),
                            }),
                        )

                    for topic in MQTT_TOPICS:
                        await client.subscribe(topic)

                    async for message in client.messages:
                        topic   = str(message.topic)
                        payload = message.payload.decode(errors="replace")

                        if topic == "io/chat":
                            if registry is not None:
                                try:
                                    asyncio.create_task(handle_chat_mqtt(json.loads(payload)))
                                except Exception as exc:
                                    logger.error(f"[io/chat] error: {exc}")
                            continue

                        event = parse_topic(topic, payload)
                        if event:
                            metric    = event.get("metric", "")
                            log_event = None if metric == "heartbeat" else event
                            await broadcast({"type": "patch", "event": log_event, "state": _snapshot()})

            except Exception as e:
                mqtt_client_ref = None
                logger.warning(f"MQTT error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
    finally:
        # Drop ref and force GC while loop is still open so paho's __del__
        # doesn't fire after the event loop closes (avoids RuntimeError noise).
        import gc
        mqtt_client_ref = None
        gc.collect()


# ── Startup checks ─────────────────────────────────────────────────────────

async def _check_mqtt() -> bool:
    """Return True if MQTT broker is reachable."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(MQTT_BROKER, MQTT_PORT), timeout=3
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception as exc:
        logger.error(f"[startup] MQTT broker {MQTT_BROKER}:{MQTT_PORT} unreachable — {exc}")
        return False


async def _check_ws_port() -> bool:
    """Return True if WS_PORT is free to bind."""
    try:
        server = await asyncio.start_server(lambda r, w: None, "0.0.0.0", WS_PORT)
        server.close()
        await server.wait_closed()
        return True
    except OSError as exc:
        logger.error(f"[startup] Port {WS_PORT} already in use — {exc}")
        return False


# ── Static file serving ────────────────────────────────────────────────────

_pkg  = Path(__file__).parent
_root = _pkg.parent

def _find_dir(*rel: str) -> Path:
    for base in (_pkg, _root):
        p = base.joinpath(*rel)
        if p.is_dir():
            return p
    return _pkg.joinpath(*rel)

FRONTEND_DIST   = _find_dir("static", "app")
FRONTEND_PUBLIC = _find_dir("frontend", "public")
DOCS_SITE       = _find_dir("static", "docs")


def _with_no_cache(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


async def index_handler(request):
    from aiohttp import web
    from .config import CONFIG

    if request.path.endswith("favicon.svg"):
        for candidate in [FRONTEND_PUBLIC / "favicon.svg", FRONTEND_DIST / "favicon.svg"]:
            if candidate.exists():
                return _with_no_cache(web.FileResponse(candidate))

    for candidate in [
        FRONTEND_DIST / "index.html",
        _find_dir("frontend") / "index.html",
        _pkg / "monitor.html",
        _root / "monitor.html",
    ]:
        if candidate.exists():
            ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
            # Inject the ingress path so the frontend can prefix all fetch/WS URLs.
            # When not behind ingress, ingress_path is "" and all URLs stay relative.
            inject = f"<script>window.__WACTORZ_INGRESS_PATH='{ingress_path}';</script>"
            if ingress_path:
                inject = f'<base href="{ingress_path}/">{inject}'

            content = candidate.read_text(encoding="utf-8")
            content = content.replace("<head>", f"<head>{inject}", 1)
            return _with_no_cache(web.Response(text=content, content_type="text/html"))
    raise web.HTTPNotFound()


async def static_handler(request):
    from aiohttp import web
    rel = request.match_info["path"]
    
    # Special case for favicon if it's requested at root
    if rel == "favicon.svg":
        for candidate in [FRONTEND_PUBLIC / "favicon.svg", FRONTEND_DIST / "favicon.svg"]:
            if candidate.exists():
                return _with_no_cache(web.FileResponse(candidate))

    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")

    for base in [FRONTEND_DIST, FRONTEND_PUBLIC]:
        candidate = base / rel
        try:
            candidate = candidate.resolve()
            if candidate.is_file() and str(candidate).startswith(str(base.resolve())):
                # If it's a JS file and we're behind Ingress, we must rewrite hardcoded absolute paths
                if candidate.suffix == ".js" and ingress_path:
                    content = candidate.read_text(encoding="utf-8")
                    # Rewrite hardcoded paths from "/api/..." to "api/..." or prepending ingress_path
                    # The frontend seems to use "/api/actors", "/api/config", etc.
                    content = content.replace('"/api/', f'"{ingress_path}/api/')
                    content = content.replace('"/config"', f'"{ingress_path}/config"')
                    content = content.replace('"/actors"', f'"{ingress_path}/actors"')
                    # FORCE the WebSocket to use port 8888 instead of HA's 8123
                    content = content.replace('"ws://localhost:9001"', f'"ws://{request.host.split(":")[0]}:8888/mqtt"')
                    content = content.replace('`ws://${location.host}/ws`', f'`ws://${{location.hostname}}:8888/ws`')
                    content = content.replace('`ws://${location.host}/mqtt`', f'`ws://${{location.hostname}}:8888/mqtt`')
                    
                    return _with_no_cache(web.Response(text=content, content_type="application/javascript"))
                
                return _with_no_cache(web.FileResponse(candidate))
        except Exception:
            pass
    raise web.HTTPNotFound()


async def docs_handler(request):
    from aiohttp import web
    if not DOCS_SITE.is_dir():
        raise web.HTTPNotFound(reason="Docs not built — run: python3 scripts/build_docs.py  (or: make docs-build)")
    rel = request.match_info.get("path", "") or "index.html"
    if not rel or rel.endswith("/"):
        rel += "index.html"
    root      = DOCS_SITE.resolve()
    candidate = (DOCS_SITE / rel).resolve()
    try:
        if candidate.is_file() and str(candidate).startswith(str(root)):
            return web.FileResponse(candidate)
        if rel.endswith("index.html") and not candidate.exists():
            parent = candidate.parent
            if parent.is_dir():
                for sub in sorted(parent.iterdir()):
                    if sub.is_dir() and (sub / "index.html").exists():
                        raise web.HTTPFound(request.path.rstrip("/") + f"/{sub.name}/index.html")
    except web.HTTPFound:
        raise
    except Exception:
        pass
    raise web.HTTPNotFound()


async def _bridge_mqtt_tcp(client_ws, broker: str, port: int) -> None:
    from aiohttp import WSMsgType
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(broker, port), timeout=3)
    except Exception as exc:
        logger.warning("MQTT TCP bridge: cannot connect to %s:%s — %s", broker, port, exc)
        return

    async def ws_to_tcp():
        try:
            async for msg in client_ws:
                if msg.type == WSMsgType.BINARY:
                    writer.write(msg.data)
                    await writer.drain()
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        finally:
            writer.close()

    async def tcp_to_ws():
        try:
            while not reader.at_eof():
                data = await reader.read(4096)
                if not data:
                    break
                await client_ws.send_bytes(data)
        finally:
            await client_ws.close()

    await asyncio.gather(ws_to_tcp(), tcp_to_ws(), return_exceptions=True)


async def mqtt_proxy_handler(request):
    import aiohttp
    from aiohttp import web, WSMsgType

    raw_proto = request.headers.get("Sec-WebSocket-Protocol", "")
    protocols = [p.strip() for p in raw_proto.split(",") if p.strip()]
    client_ws = web.WebSocketResponse(protocols=protocols)
    await client_ws.prepare(request)

    upstream_url = f"ws://{MQTT_BROKER}:{MQTT_WS_PORT}/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                upstream_url,
                protocols=protocols,
                headers={"Sec-WebSocket-Protocol": ",".join(protocols)} if protocols else {},
                timeout=aiohttp.ClientTimeout(connect=2),
            ) as upstream_ws:
                async def forward(src, dst):
                    async for msg in src:
                        if msg.type == WSMsgType.BINARY:
                            await dst.send_bytes(msg.data)
                        elif msg.type == WSMsgType.TEXT:
                            await dst.send_str(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break
                await asyncio.gather(forward(client_ws, upstream_ws), forward(upstream_ws, client_ws))
        return client_ws
    except Exception as exc:
        logger.info("MQTT WS proxy unavailable (%s), falling back to TCP bridge", exc)

    await _bridge_mqtt_tcp(client_ws, MQTT_BROKER, MQTT_PORT)
    return client_ws


def _actor_payload(ag: dict) -> dict:
    return {
        "id":                ag.get("agent_id", ""),
        "name":              ag.get("name", ""),
        "state":             ag.get("state", "unknown"),
        "protected":         ag.get("protected", False),
        "cpu":               ag.get("cpu"),
        "mem":               ag.get("mem"),
        "task":              ag.get("task"),
        "messagesProcessed": ag.get("messages_processed"),
        "costUsd":           ag.get("cost_usd"),
    }


def _actor_cost(actor, ag: dict):
    """Return the most accurate cost available: MQTT-derived first, then live object, then SQLite."""
    mqtt_cost = ag.get("cost_usd")
    if mqtt_cost is not None:
        return mqtt_cost
    live_cost = getattr(actor, "total_cost_usd", None)
    if live_cost:
        return round(live_cost, 6)
    if db is not None:
        try:
            import json as _json
            row = db.conn.execute(
                "SELECT value FROM kv_store WHERE agent=? AND key='_final_cost'",
                (actor.name,),
            ).fetchone()
            if row:
                entry = _json.loads(row[0])
                return entry.get("cost_usd")
        except Exception:
            pass
    return None


async def health_handler(request):
    from aiohttp import web
    return web.json_response({"status": "ok"})


async def send_message_handler(request):
    from aiohttp import web
    actor_id = request.match_info["actor_id"]
    if registry is None:
        return web.json_response({"error": "registry not available"}, status=503)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    content = data.get("content", "").strip()
    if not content:
        return web.json_response({"error": "content required"}, status=400)
    actor = registry.get(actor_id) or registry.find_by_name(actor_id)
    if actor is None:
        return web.json_response({"error": "actor not found"}, status=404)
    asyncio.create_task(_route_chat(content, lambda t: None))
    return web.json_response({"status": "sent"})


async def delete_actor_handler(request):
    from aiohttp import web
    actor_id = request.match_info["actor_id"]
    if registry is None:
        return web.json_response({"error": "registry not available"}, status=503)
    actor = registry.get(actor_id) or registry.find_by_name(actor_id)
    if actor is None:
        return web.json_response({"error": "actor not found"}, status=404)
    if getattr(actor, "protected", False):
        return web.json_response({"error": "actor is protected"}, status=403)
    if mqtt_client_ref:
        await mqtt_client_ref.publish(
            f"agents/{actor_id}/commands",
            json.dumps({"command": "stop", "sender": "api", "timestamp": time.time()}),
        )
    return web.Response(status=200, text="stopping")


async def pause_actor_handler(request):
    from aiohttp import web
    actor_id = request.match_info["actor_id"]
    if registry is None:
        return web.json_response({"error": "registry not available"}, status=503)
    actor = registry.get(actor_id) or registry.find_by_name(actor_id)
    if actor is None:
        return web.json_response({"error": "actor not found"}, status=404)
    if getattr(actor, "protected", False):
        return web.json_response({"error": "actor is protected"}, status=403)
    if mqtt_client_ref:
        await mqtt_client_ref.publish(
            f"agents/{actor_id}/commands",
            json.dumps({"command": "pause", "sender": "api", "timestamp": time.time()}),
        )
    return web.json_response({"status": "pausing"})


async def resume_actor_handler(request):
    from aiohttp import web
    actor_id = request.match_info["actor_id"]
    if registry is None:
        return web.json_response({"error": "registry not available"}, status=503)
    actor = registry.get(actor_id) or registry.find_by_name(actor_id)
    if actor is None:
        return web.json_response({"error": "actor not found"}, status=404)
    if getattr(actor, "protected", False):
        return web.json_response({"error": "actor is protected"}, status=403)
    if mqtt_client_ref:
        await mqtt_client_ref.publish(
            f"agents/{actor_id}/commands",
            json.dumps({"command": "resume", "sender": "api", "timestamp": time.time()}),
        )
    return web.json_response({"status": "resuming"})


async def actor_metrics_handler(request):
    from aiohttp import web
    actor_id = request.match_info["actor_id"]
    ag = state["agents"].get(actor_id)
    actor = None
    if registry is not None:
        actor = registry.get(actor_id) or registry.find_by_name(actor_id)
    if actor is None and ag is None:
        return web.json_response({"error": "actor not found"}, status=404)
    metrics_obj = getattr(actor, "metrics", None) if actor else None
    return web.json_response({
        "messages_processed": (
            getattr(metrics_obj, "messages_processed", None)
            or (ag.get("messages_processed") if ag else None)
            or 0
        ),
        "cpu":      ag.get("cpu")       if ag else None,
        "mem":      ag.get("mem")       if ag else None,
        "task":     ag.get("task")      if ag else None,
        "cost_usd": (
            getattr(actor, "total_cost_usd", None)
            or (ag.get("cost_usd") if ag else None)
        ),
    })


async def rest_chat_handler(request):
    """POST /chat — fire-and-forget a message to a named agent."""
    from aiohttp import web
    if registry is None:
        return web.json_response({"error": "registry not available"}, status=503)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    message    = data.get("message", "").strip()
    agent_name = data.get("agent_name", "main-actor")
    if not message:
        return web.json_response({"error": "message required"}, status=400)
    target = registry.find_by_name(agent_name)
    if target is None:
        return web.json_response({"error": f"agent '{agent_name}' not found"}, status=404)
    asyncio.create_task(_route_chat(message, lambda t: None))
    return web.json_response({"status": "sent", "agent": agent_name})


async def actors_handler(request):
    from aiohttp import web
    # Prefer the live registry (injected by cli.py) — actor objects carry the
    # authoritative protected flag.  Fall back to MQTT-derived state dict when
    # the registry is unavailable (standalone monitor_server mode).
    if registry is not None:
        result = []
        for actor in registry.all_actors():
            ag = state["agents"].get(actor.actor_id, {})
            result.append({
                "id":                actor.actor_id,
                "name":              actor.name,
                "state":             ag.get("state", "unknown"),
                "protected":         bool(getattr(actor, "protected", False)),
                "cpu":               ag.get("cpu"),
                "mem":               ag.get("mem"),
                "task":              ag.get("task"),
                "messagesProcessed": ag.get("messages_processed") if ag.get("messages_processed") is not None
                                     else getattr(getattr(actor, "metrics", None), "messages_processed", None),
                "costUsd":           _actor_cost(actor, ag),
            })
        return web.json_response(result)
    return web.json_response([_actor_payload(ag) for ag in state["agents"].values()])


async def actor_handler(request):
    from aiohttp import web
    actor_id = request.match_info["actor_id"]
    ag = state["agents"].get(actor_id)
    if ag is None:
        return web.json_response({"error": "actor not found"}, status=404)
    return web.json_response(_actor_payload(ag))


async def actor_history_handler(request):
    from aiohttp import web
    actor_id = request.match_info["actor_id"]

    # Resolve actor: the frontend sends the agent NAME (not UUID), so try
    # direct UUID lookup first, then fall back to name-based lookup.
    actor = None
    if registry is not None:
        actor = registry.get(actor_id) or registry.find_by_name(actor_id)

    if actor is not None and hasattr(actor, "recall"):
        history = actor.recall("conversation_history", [])
    elif db is not None:
        # Actor not in registry (deleted or name-only lookup) — read from SQLite.
        # actor_id might be a display name (e.g. "main") — try it directly.
        try:
            import json as _json
            row = db.conn.execute(
                "SELECT value FROM kv_store WHERE agent=? AND key='conversation_history'",
                (actor_id,),
            ).fetchone()
            history = _json.loads(row[0]) if row else []
        except Exception:
            history = []
    else:
        history = []

    visible = [m for m in history if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    return web.json_response(visible)


async def chat_log_handler(request):
    """GET /api/chats — query the persistent chat_log table.

    Query params:
      agent   — filter by agent name
      role    — filter by role (user | assistant)
      since   — Unix timestamp float, only return rows newer than this
      limit   — max rows to return (default 200, max 1000)
    """
    from aiohttp import web
    if db is None:
        return web.json_response([], status=200)
    try:
        agent  = request.rel_url.query.get("agent")
        role   = request.rel_url.query.get("role")
        since  = float(request.rel_url.query["since"]) if "since" in request.rel_url.query else None
        limit  = min(int(request.rel_url.query.get("limit", 200)), 1000)
        rows   = db.query_chat_log(agent_name=agent, role=role, since=since, limit=limit)
        return web.json_response(rows)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


_tts_voices_cache: list | None = None


async def _warm_tts_voices(_app=None) -> None:
    """Load edge-tts voice list once at startup and cache it."""
    global _tts_voices_cache
    try:
        import edge_tts
        voices = await edge_tts.list_voices()
        _tts_voices_cache = [
            {"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]}
            for v in sorted(voices, key=lambda v: v["ShortName"])
        ]
    except Exception:
        _tts_voices_cache = []


async def tts_voices_handler(request):
    """GET /api/tts/voices — list available edge-tts voices."""
    from aiohttp import web
    try:
        import edge_tts as _  # noqa: F401 — check installed
    except ImportError:
        return web.json_response([])
    if _tts_voices_cache is None:
        await _warm_tts_voices()
    return web.json_response(_tts_voices_cache or [])


async def tts_handler(request):
    """GET /api/tts?text=...&voice=... — synthesize speech via edge-tts.

    Returns audio/mpeg. Falls back 503 if edge-tts is not installed so the
    frontend can transparently fall back to the Web Speech API.
    """
    from aiohttp import web
    import os
    try:
        import edge_tts
    except ImportError:
        return web.Response(status=503, text="edge-tts not installed — pip install 'wactorz[tts]'")

    text = request.rel_url.query.get("text", "").strip()
    if not text:
        return web.Response(status=400, text="text param required")

    # Mirror TTSManager: strip code blocks, cap at 300 chars
    import re
    text = re.sub(r"```[\s\S]*?```", "code block", text)[:300]

    default_voice = os.environ.get("TTS_VOICE", "en-US-JennyNeural")
    voice = request.rel_url.query.get("voice", default_voice) or default_voice

    try:
        communicate = edge_tts.Communicate(text, voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        audio = b"".join(chunks)
        return web.Response(
            body=audio,
            content_type="audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return web.Response(status=500, text=str(exc))


async def config_handler(request):
    """Expose non-secret runtime config so the frontend can seed its defaults."""
    from aiohttp import web
    from .config import CONFIG

    # Ingress support: HA sets X-Ingress-Path
    ingress_path = request.headers.get("X-Ingress-Path", "")
    
    # Force the host to use port 8888 for WebSockets
    raw_host = request.host.split(":")[0]
    ws_host = f"{raw_host}:8888"
    protocol = "wss" if request.secure else "ws"
    
    # WebSocket URLs go direct to 8888
    mqtt_url = f"{protocol}://{ws_host}/mqtt"
    ws_url   = f"{protocol}://{ws_host}/ws"

    return web.json_response({
        "ha": {
            "url":   CONFIG.ha_url,
            "token": CONFIG.ha_token,
        },
        "fuseki": {
            "url":     CONFIG.fuseki_url,
            "dataset": CONFIG.fuseki_dataset,
        },
        "mqtt": {
            "host": MQTT_BROKER,
            "port": MQTT_PORT,
            "url":  mqtt_url,
        },
        "llm": {
            "provider": CONFIG.llm_provider,
            "model":    CONFIG.llm_model,
        },
        "weather": {
            "defaultLocation": CONFIG.weather_default_location,
        },
        "ws_url": ws_url,
    })


async def feed_handler(request):
    """
    Return recent chat events for the UI feed, with REAL persisted timestamps.

    Previously this read from kv_store.conversation_history, which is just a
    JSON list with no timestamps — so each entry got `i` (the loop index) as
    its timestamp and the frontend re-dated them to "now - i*delta", causing
    timestamps to reset on every page reload / restart.

    Now we read from the chat_log table, which has a real `ts REAL` column
    written at the moment each turn happens. Falls back to the legacy
    kv_store path only if chat_log is empty (e.g. a freshly upgraded DB
    where nothing has been written yet) so existing users still see their
    pre-upgrade history on first launch.
    """
    from aiohttp import web
    if db is None:
        return web.json_response([])
    try:
        # Primary path — persistent chat_log with real timestamps.
        try:
            rows = db.query_chat_log(limit=50)
        except Exception as exc:
            logger.warning(f"[feed] chat_log query failed: {exc}")
            rows = []

        if rows:
            # query_chat_log returns newest-first; the frontend expects
            # chronological (oldest-first) so the latest message ends up
            # at the bottom of the feed.
            rows = list(reversed(rows))
            items = [{
                "type":      "chat",
                "label":     str(r.get("content", "")),
                "agentName": r.get("agent_name", ""),
                "role":      r.get("role", ""),
                "timestamp": float(r.get("ts", 0.0)),  # REAL Unix time, not an index
                "_seq":      i,
                "_agent":    r.get("agent_name", ""),
            } for i, r in enumerate(rows)]
            return web.json_response(items)

        # Fallback — legacy kv_store path. Keeps old DBs displaying *something*
        # until new chat turns start populating chat_log. Synthesises a
        # timestamp by anchoring the last entry to "now" and walking backwards
        # in 1-second steps, so at least entries are ordered consistently.
        import json as _json
        kv_rows = db.conn.execute(
            "SELECT agent, value FROM kv_store WHERE key='conversation_history'"
        ).fetchall()
        items = []
        now = time.time()
        for agent_name, value in kv_rows:
            try:
                history = _json.loads(value)
                visible = [m for m in history
                           if isinstance(m, dict)
                           and m.get("role") in ("user", "assistant")]
                n = len(visible)
                for i, msg in enumerate(visible):
                    items.append({
                        "type":      "chat",
                        "label":     str(msg.get("content", "")),
                        "agentName": agent_name,
                        "role":      msg.get("role", ""),
                        # Synthesised but at least monotonic and anchored
                        # to a real wall-clock value, not a bare index.
                        "timestamp": now - (n - 1 - i),
                        "_seq":      i,
                        "_agent":    agent_name,
                    })
            except Exception:
                pass
        return web.json_response(items[-50:])
    except Exception as exc:
        logger.warning(f"[feed] handler failed: {exc}")
        return web.json_response([])


# ── Entry point ────────────────────────────────────────────────────────────

async def main(exit_on_failure: bool = False):
    from aiohttp import web

    # ... (startup checks remain same) ...
    mqtt_ok = await _check_mqtt()
    port_ok = await _check_ws_port()

    if not mqtt_ok or not port_ok:
        msg = []
        if not mqtt_ok: msg.append(f"MQTT broker unreachable ({MQTT_BROKER}:{MQTT_PORT})")
        if not port_ok: msg.append(f"Port {WS_PORT} already in use")
        logger.error(f"[startup] Cannot start: {'; '.join(msg)}")
        if exit_on_failure:
            raise SystemExit(1)
        return

    app = web.Application()
    app.router.add_get("/",                      index_handler)
    app.router.add_get("/health",                health_handler)
    app.router.add_get("/ws",                    ws_handler)
    app.router.add_get("/mqtt",                  mqtt_proxy_handler)

    # Actor collection
    app.router.add_get("/api/actors",            actors_handler)
    app.router.add_get("/actors",                actors_handler)

    # Actor control — sub-routes must be registered before /{actor_id} catch-all
    app.router.add_post("/api/actors/{actor_id}/message", send_message_handler)
    app.router.add_post("/actors/{actor_id}/message",     send_message_handler)
    app.router.add_post("/api/actors/{actor_id}/pause",   pause_actor_handler)
    app.router.add_post("/actors/{actor_id}/pause",       pause_actor_handler)
    app.router.add_post("/api/actors/{actor_id}/resume",  resume_actor_handler)
    app.router.add_post("/actors/{actor_id}/resume",      resume_actor_handler)
    app.router.add_get("/api/actors/{actor_id}/metrics",  actor_metrics_handler)
    app.router.add_get("/actors/{actor_id}/metrics",      actor_metrics_handler)
    app.router.add_get("/api/actors/{actor_id}/history",  actor_history_handler)
    app.router.add_get("/actors/{actor_id}/history",      actor_history_handler)

    # Actor CRUD
    app.router.add_get("/api/actors/{actor_id}",          actor_handler)
    app.router.add_get("/actors/{actor_id}",              actor_handler)
    app.router.add_delete("/api/actors/{actor_id}",       delete_actor_handler)
    app.router.add_delete("/actors/{actor_id}",           delete_actor_handler)

    # Chat (REST fire-and-forget)
    app.router.add_post("/api/chat",             rest_chat_handler)
    app.router.add_post("/chat",                 rest_chat_handler)

    app.router.add_get("/api/chats",             chat_log_handler)
    app.router.add_get("/chats",                 chat_log_handler)
    app.router.add_get("/api/tts/voices",        tts_voices_handler)
    app.router.add_get("/api/tts",               tts_handler)
    app.on_startup.append(_warm_tts_voices)

    app.router.add_get("/api/config",            config_handler)
    app.router.add_get("/config",                config_handler)
    app.router.add_get("/api/feed",              feed_handler)
    app.router.add_get("/feed",                  feed_handler)
    app.router.add_get("/favicon.svg",           index_handler)
    from .fuseki_proxy import fuseki_proxy_handler
    app.router.add_post("/api/fuseki/{dataset}/sparql",  fuseki_proxy_handler)
    app.router.add_post("/api/fuseki/{dataset}/update",  fuseki_proxy_handler)
    app.router.add_get("/docs",  lambda r: web.HTTPFound("/docs/"))
    app.router.add_get("/docs/",             docs_handler)
    app.router.add_get("/docs/{path:.+}",    docs_handler)
    app.router.add_get("/{path:.+}",         static_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WS_PORT)
    await site.start()
    logger.info(f"Monitor  → http://localhost:{WS_PORT}/  [chat: {_chat_mode()}]")
    if DOCS_SITE.is_dir():
        logger.info(f"Docs     → http://localhost:{WS_PORT}/docs/")

    await mqtt_listener()


def cli_main() -> None:
    asyncio.run(main(exit_on_failure=True))


if __name__ == "__main__":
    import argparse, os
    parser = argparse.ArgumentParser(description="Wactorz Monitor Server")
    parser.add_argument("--broker",       default=os.getenv("WACTORZ_BROKER", "localhost"))
    parser.add_argument("--mqtt-port",    type=int, default=1883)
    parser.add_argument("--mqtt-ws-port", type=int, default=int(os.getenv("MQTT_WS_PORT", "9001")))
    parser.add_argument("--ws-port",      type=int, default=int(os.getenv("MONITOR_PORT", "8888")))
    args = parser.parse_args()

    thismodule = sys.modules[__name__]
    thismodule.MQTT_BROKER  = args.broker
    thismodule.MQTT_PORT    = args.mqtt_port
    thismodule.MQTT_WS_PORT = args.mqtt_ws_port
    thismodule.WS_PORT      = args.ws_port

    cli_main()