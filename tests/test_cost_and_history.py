"""
Tests for cost persistence, cost restoration on startup, and chat history API.

Covers three recent features:
  - LLM cost written to SQLite (_final_cost key) and restored on agent restart
  - Historical (deleted agent) cost included in _snapshot() total
  - GET /api/actors/{id}/history endpoint filters and returns conversation history
"""
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Minimal stubs so heavy optional deps don't need to be installed ──────────
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
sys.modules.setdefault("websockets", types.ModuleType("websockets"))
sys.modules.setdefault("openai", types.ModuleType("openai"))
sys.modules.setdefault("aiomqtt", types.ModuleType("aiomqtt"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Persistence routing
# ─────────────────────────────────────────────────────────────────────────────

class FinalCostRoutingTest(unittest.TestCase):
    def test_final_cost_key_is_in_sqlite_keys(self):
        from wactorz.core.persistence import _SQLITE_KEYS
        self.assertIn("_final_cost", _SQLITE_KEYS,
                      "_final_cost must route to SQLite so it survives restarts "
                      "and is queryable for deleted-agent cost accounting")


# ─────────────────────────────────────────────────────────────────────────────
# 2. LLMAgent cost restore on startup
# ─────────────────────────────────────────────────────────────────────────────

class LLMAgentCostRestoreTest(unittest.IsolatedAsyncioTestCase):
    """
    LLMAgent.on_start() should seed total_* from the persisted _final_cost so
    that heartbeats carry accurate lifetime totals after a restart.
    """

    def _make_agent(self, saved_cost: dict):
        from wactorz.agents.llm_agent import LLMAgent

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            agent = LLMAgent(name="test-llm", persistence_dir=tmp)

        def _recall(key, default=None):
            if key == "_final_cost":
                return saved_cost
            if key == "conversation_history":
                return []
            if key == "history_summary":
                return ""
            return default

        agent.recall = _recall
        agent.persist = MagicMock()
        agent.publish_manifest = AsyncMock()
        return agent

    async def test_cost_seeded_from_persisted_final_cost(self):
        saved = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.0042}
        agent = self._make_agent(saved)

        await agent.on_start()

        self.assertEqual(agent.total_input_tokens, 100)
        self.assertEqual(agent.total_output_tokens, 50)
        self.assertAlmostEqual(agent.total_cost_usd, 0.0042, places=6)

    async def test_zero_cost_when_no_saved_cost(self):
        agent = self._make_agent({})

        await agent.on_start()

        self.assertEqual(agent.total_input_tokens, 0)
        self.assertEqual(agent.total_cost_usd, 0.0)

    async def test_cost_accumulates_on_top_of_restored_baseline(self):
        """After restoring from persistence, new exchanges add to the running total."""
        saved = {"input_tokens": 200, "output_tokens": 80, "cost_usd": 0.01}
        agent = self._make_agent(saved)
        await agent.on_start()

        agent.total_input_tokens  += 10
        agent.total_output_tokens += 5
        agent.total_cost_usd      += 0.001

        self.assertEqual(agent.total_input_tokens, 210)
        self.assertAlmostEqual(agent.total_cost_usd, 0.011, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# 3. _persist_cost() writes correct structure
# ─────────────────────────────────────────────────────────────────────────────

class PersistCostTest(unittest.TestCase):
    def _make_agent(self):
        from wactorz.agents.llm_agent import LLMAgent

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            agent = LLMAgent(name="cost-agent", persistence_dir=tmp)

        agent.persist = MagicMock()
        agent.total_input_tokens  = 300
        agent.total_output_tokens = 120
        agent.total_cost_usd      = 0.0315
        return agent

    def test_persist_cost_writes_all_fields(self):
        agent = self._make_agent()
        agent._persist_cost()

        agent.persist.assert_called_once()
        key, payload = agent.persist.call_args[0]
        self.assertEqual(key, "_final_cost")
        self.assertEqual(payload["input_tokens"], 300)
        self.assertEqual(payload["output_tokens"], 120)
        self.assertAlmostEqual(payload["cost_usd"], 0.0315, places=6)
        self.assertEqual(payload["name"], "cost-agent")

    def test_persist_cost_rounds_to_six_decimals(self):
        agent = self._make_agent()
        agent.total_cost_usd = 1 / 3
        agent._persist_cost()

        _, payload = agent.persist.call_args[0]
        # round() to 6 places: 0.333333
        self.assertEqual(payload["cost_usd"], round(1 / 3, 6))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Historical cost accounting in monitor_server
# ─────────────────────────────────────────────────────────────────────────────

def _make_kv_db(entries: list[dict]) -> object:
    """Return a minimal db stub backed by in-memory SQLite with kv_store rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE kv_store (agent TEXT, key TEXT, value TEXT)"
    )
    for e in entries:
        conn.execute(
            "INSERT INTO kv_store (agent, key, value) VALUES (?, ?, ?)",
            (e["agent"], e["key"], json.dumps(e["value"])),
        )
    conn.commit()
    return types.SimpleNamespace(conn=conn)


class HistoricalCostTest(unittest.TestCase):
    def setUp(self):
        import wactorz.monitor_server as ms
        self._ms = ms
        # Reset module state between tests
        self._orig_db    = ms.db
        self._orig_state = dict(ms.state["agents"])

    def tearDown(self):
        self._ms.db = self._orig_db
        self._ms.state["agents"] = self._orig_state

    def _live_names(self):
        """Derive live_names from state["agents"] as _snapshot() does when no registry."""
        return {a.get("name", "") for a in self._ms.state["agents"].values()}

    def test_returns_zero_when_db_is_none(self):
        self._ms.db = None
        self.assertEqual(self._ms._historical_cost_usd(self._live_names()), 0.0)

    def test_returns_zero_when_no_final_cost_rows(self):
        self._ms.db = _make_kv_db([])
        self._ms.state["agents"] = {}
        self.assertEqual(self._ms._historical_cost_usd(self._live_names()), 0.0)

    def test_sums_costs_for_deleted_agents(self):
        self._ms.db = _make_kv_db([
            {"agent": "old-agent", "key": "_final_cost",
             "value": {"name": "old-agent", "cost_usd": 0.05}},
            {"agent": "gone-agent", "key": "_final_cost",
             "value": {"name": "gone-agent", "cost_usd": 0.03}},
        ])
        self._ms.state["agents"] = {}  # no live agents

        total = self._ms._historical_cost_usd(self._live_names())
        self.assertAlmostEqual(total, 0.08, places=6)

    def test_excludes_live_agent_costs(self):
        """Live agents report cost via MQTT heartbeats — don't double-count."""
        self._ms.db = _make_kv_db([
            {"agent": "live-agent", "key": "_final_cost",
             "value": {"name": "live-agent", "cost_usd": 0.10}},
            {"agent": "dead-agent", "key": "_final_cost",
             "value": {"name": "dead-agent", "cost_usd": 0.04}},
        ])
        self._ms.state["agents"] = {
            "live-agent": {"name": "live-agent", "cost_usd": 0.10},
        }

        total = self._ms._historical_cost_usd(self._live_names())
        self.assertAlmostEqual(total, 0.04, places=6)

    def test_ignores_malformed_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE kv_store (agent TEXT, key TEXT, value TEXT)")
        conn.execute("INSERT INTO kv_store VALUES (?, ?, ?)",
                     ("broken", "_final_cost", "not-valid-json{{{"))
        conn.execute("INSERT INTO kv_store VALUES (?, ?, ?)",
                     ("ok", "_final_cost", json.dumps({"name": "ok", "cost_usd": 0.02})))
        conn.commit()
        self._ms.db = types.SimpleNamespace(conn=conn)
        self._ms.state["agents"] = {}

        total = self._ms._historical_cost_usd(self._live_names())
        self.assertAlmostEqual(total, 0.02, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# 5. actor_history_handler
# ─────────────────────────────────────────────────────────────────────────────

def _make_web_stub():
    """Minimal aiohttp.web stub for handler tests."""
    class _JsonResponse:
        def __init__(self, data, status=200):
            self.data   = data
            self.status = status

    web = types.SimpleNamespace(
        json_response=lambda data, **kw: _JsonResponse(data, **kw),
    )
    return web


class ActorHistoryHandlerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import wactorz.monitor_server as ms
        self._ms = ms
        self._orig_registry = ms.registry

    def tearDown(self):
        self._ms.registry = self._orig_registry

    def _make_request(self, actor_id: str):
        return types.SimpleNamespace(match_info={"actor_id": actor_id})

    async def test_returns_empty_list_when_registry_none(self):
        self._ms.registry = None

        with patch("aiohttp.web", _make_web_stub(), create=True):
            resp = await self._ms.actor_history_handler(self._make_request("any"))

        self.assertEqual(resp.data, [])
        self.assertEqual(resp.status, 200)

    async def test_returns_empty_list_when_actor_not_found(self):
        registry = MagicMock()
        registry.get.return_value = None
        self._ms.registry = registry

        with patch("aiohttp.web", _make_web_stub(), create=True):
            resp = await self._ms.actor_history_handler(self._make_request("ghost"))

        self.assertEqual(resp.data, [])

    async def test_returns_only_user_and_assistant_turns(self):
        history = [
            {"role": "user",      "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "tool",      "content": "tool output"},   # should be filtered
            {"role": "system",    "content": "system prompt"}, # should be filtered
        ]
        actor = MagicMock()
        actor.recall.return_value = history
        registry = MagicMock()
        registry.get.return_value = actor
        self._ms.registry = registry

        with patch("aiohttp.web", _make_web_stub(), create=True):
            resp = await self._ms.actor_history_handler(self._make_request("test-agent"))

        self.assertEqual(len(resp.data), 2)
        self.assertEqual(resp.data[0]["role"], "user")
        self.assertEqual(resp.data[1]["role"], "assistant")

    async def test_returns_empty_list_when_history_empty(self):
        actor = MagicMock()
        actor.recall.return_value = []
        registry = MagicMock()
        registry.get.return_value = actor
        self._ms.registry = registry

        with patch("aiohttp.web", _make_web_stub(), create=True):
            resp = await self._ms.actor_history_handler(self._make_request("quiet-agent"))

        self.assertEqual(resp.data, [])

    async def test_handles_actor_without_recall(self):
        """Actors without a recall() method (non-LLM) return empty history."""
        actor = object()  # plain object, no recall method
        registry = MagicMock()
        registry.get.return_value = actor
        self._ms.registry = registry

        with patch("aiohttp.web", _make_web_stub(), create=True):
            resp = await self._ms.actor_history_handler(self._make_request("dumb-agent"))

        self.assertEqual(resp.data, [])


if __name__ == "__main__":
    unittest.main()
