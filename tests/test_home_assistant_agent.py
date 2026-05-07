import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
sys.modules.setdefault("websockets", types.ModuleType("websockets"))

from wactorz.agents.home_assistant_agent import HomeAssistantAgent
from wactorz.agents.llm_agent import ToolCall, ToolCompletion


class _ClassifyingLLM:
    def __init__(self, response: str):
        self.response = response

    async def complete(self, *args, **kwargs):
        return self.response, {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}


class _ToolLLM:
    def __init__(self, completions):
        self.completions = list(completions)
        self.calls = []

    async def complete_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        if self.completions:
            return self.completions.pop(0)
        return ToolCompletion(content="done", usage={})


class _FailingToolLLM:
    async def complete_with_tools(self, **kwargs):
        raise RuntimeError("provider does not support tools")


class HomeAssistantAgentOtherFeatureTest(unittest.IsolatedAsyncioTestCase):
    def _agent(self, llm_provider=None) -> HomeAssistantAgent:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        agent = HomeAssistantAgent(
            llm_provider=llm_provider,
            name="home-assistant-agent-test",
            persistence_dir=tmpdir.name,
        )
        agent.ha_url = "ws://ha.local:8123/api/websocket"
        agent.ha_token = "token"
        return agent

    async def test_classify_action_accepts_other(self):
        """The HA action classifier must accept the new `other` class from the LLM."""
        agent = self._agent(_ClassifyingLLM("other"))

        self.assertEqual(await agent._classify_action("how is my home doing?"), "other")

    async def test_thermometer_existence_and_state_are_other(self):
        """Normal thermometer lookup/state questions route to the regular HA `other` flow."""
        agent = self._agent()

        self.assertEqual(agent._classify_action_heuristic("do I have any thermometers?"), "other")
        self.assertEqual(agent._classify_action_heuristic("what is the state of my thermometer?"), "other")

    async def test_classify_action_get_entities_state_is_literal_heuristic_only(self):
        """Only the literal trigger routes to the deterministic entity-state action."""
        agent = self._agent(_ClassifyingLLM("other"))

        self.assertEqual(
            await agent._classify_action("get_entities_state sensor.kitchen_temp"),
            "get_entities_state",
        )
        self.assertEqual(await agent._classify_action("state of sensor.kitchen_temp"), "other")

    async def test_entity_state_request_publishes_single_explicit_entity(self):
        """A single explicit entity state is returned and published to its entity ID topic."""
        agent = self._agent()
        agent._mqtt_publish = AsyncMock()

        with patch(
            "wactorz.agents.home_assistant_agent.get_states",
            new=AsyncMock(return_value=[
                {"entity_id": "sensor.kitchen_temp", "state": "21"},
                {"entity_id": "light.kitchen", "state": "off"},
            ]),
        ) as get_states:
            result = await agent._process("get_entities_state sensor.kitchen_temp")

        get_states.assert_awaited_once_with(agent.ha_url, agent.ha_token)
        agent._mqtt_publish.assert_awaited_once_with(
            "sensor.kitchen_temp",
            {"new_state": {"state": "21"}},
        )
        self.assertIn("sensor.kitchen_temp: 21", result["result"])
        self.assertEqual(result["data"]["missing"], [])

    async def test_entity_state_request_publishes_multiple_explicit_entities(self):
        """Multiple explicit entities publish one MQTT message per found state."""
        agent = self._agent()
        agent._mqtt_publish = AsyncMock()

        with patch(
            "wactorz.agents.home_assistant_agent.get_states",
            new=AsyncMock(return_value=[
                {"entity_id": "sensor.kitchen_temp", "state": "21"},
                {"entity_id": "light.kitchen", "state": "on"},
            ]),
        ):
            result = await agent._handle_entities_state_request(
                "get_entities_state sensor.kitchen_temp and light.kitchen"
            )

        self.assertEqual(agent._mqtt_publish.await_count, 2)
        agent._mqtt_publish.assert_any_await(
            "sensor.kitchen_temp",
            {"new_state": {"state": "21"}},
        )
        agent._mqtt_publish.assert_any_await(
            "light.kitchen",
            {"new_state": {"state": "on"}},
        )
        self.assertIn("sensor.kitchen_temp: 21", result["result"])
        self.assertIn("light.kitchen: on", result["result"])

    async def test_entity_state_request_reports_missing_without_publish(self):
        """Missing explicit entities are reported and not published."""
        agent = self._agent()
        agent._mqtt_publish = AsyncMock()

        with patch(
            "wactorz.agents.home_assistant_agent.get_states",
            new=AsyncMock(return_value=[{"entity_id": "sensor.kitchen_temp", "state": "21"}]),
        ):
            result = await agent._handle_entities_state_request(
                "get_entities_state sensor.kitchen_temp and light.missing"
            )

        agent._mqtt_publish.assert_awaited_once_with(
            "sensor.kitchen_temp",
            {"new_state": {"state": "21"}},
        )
        self.assertEqual(result["data"]["missing"], ["light.missing"])
        self.assertIn("Missing: light.missing", result["result"])

    async def test_entity_state_request_without_explicit_id_returns_error(self):
        """State requests without literal entity IDs do not query HA or publish MQTT."""
        agent = self._agent()
        agent._mqtt_publish = AsyncMock()

        with patch(
            "wactorz.agents.home_assistant_agent.get_states",
            new=AsyncMock(return_value=[]),
        ) as get_states:
            result = await agent._handle_entities_state_request("get_entities_state my thermometer")

        self.assertEqual(result["error"], "explicit_entity_id_required")
        self.assertIn("explicit Home Assistant entity IDs", result["result"])
        get_states.assert_not_awaited()
        agent._mqtt_publish.assert_not_awaited()

    async def test_entity_state_request_missing_ha_config_returns_config_error(self):
        """Explicit entity requests stop before querying or publishing when HA config is missing."""
        agent = self._agent()
        agent.ha_url = ""
        agent._mqtt_publish = AsyncMock()

        with patch(
            "wactorz.agents.home_assistant_agent.get_states",
            new=AsyncMock(return_value=[]),
        ) as get_states:
            result = await agent._handle_entities_state_request("get_entities_state sensor.kitchen_temp")

        self.assertEqual(result["error"], "HA_URL or HA_TOKEN not configured.")
        get_states.assert_not_awaited()
        agent._mqtt_publish.assert_not_awaited()

    async def test_classify_action_unknown_means_not_ha(self):
        """Non-HA requests remain `unknown` and must not fetch Home Assistant data."""
        agent = self._agent()

        self.assertEqual(agent._classify_action_heuristic("write me a Python script"), "unknown")
        with patch(
            "wactorz.agents.home_assistant_agent.get_simplified_ha_data",
            new=AsyncMock(return_value={}),
        ) as get_data:
            result = await agent._process("write me a Python script")

        self.assertIn("I can help with Home Assistant", result["result"])
        get_data.assert_not_awaited()

    async def test_other_routes_to_other_handler(self):
        """The dispatcher sends the new `other` action to the dedicated tool-loop handler."""
        agent = self._agent()
        agent._classify_action = AsyncMock(return_value="other")
        agent._handle_other_request = AsyncMock(return_value={"result": "handled"})

        result = await agent._process("what is going on in my home?")

        self.assertEqual(result, {"result": "handled"})
        agent._handle_other_request.assert_awaited_once_with("what is going on in my home?")

    async def test_other_missing_ha_config_returns_config_error(self):
        """The `other` flow stops early with a clear error when HA is not configured."""
        agent = self._agent(_ToolLLM([]))
        agent.ha_url = ""

        result = await agent._handle_other_request("what is the kitchen temperature?")

        self.assertEqual(result["error"], "HA_URL or HA_TOKEN not configured.")
        self.assertIn("HA_URL or HA_TOKEN not configured", result["result"])

    async def test_other_tool_loop_calls_simplified_ha_data(self):
        """A model tool request executes `get_simplified_ha_data` and returns the final answer."""
        llm = _ToolLLM(
            [
                ToolCompletion(
                    content="",
                    usage={"input_tokens": 2},
                    tool_calls=[ToolCall(id="call-1", name="get_simplified_ha_data")],
                    assistant_message={
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "get_simplified_ha_data", "arguments": "{}"},
                            }
                        ],
                    },
                ),
                ToolCompletion(content="Kitchen is 21 C.", usage={"output_tokens": 4}),
            ]
        )
        agent = self._agent(llm)

        with patch(
            "wactorz.agents.home_assistant_agent.get_simplified_ha_data",
            new=AsyncMock(return_value={"entities": [{"entity_id": "sensor.kitchen_temp", "state": "21"}]}),
        ) as get_data:
            result = await agent._handle_other_request("what is the kitchen temperature?")

        get_data.assert_awaited_once_with(agent.ha_url, agent.ha_token)
        self.assertEqual(result["result"], "Kitchen is 21 C.")

    async def test_other_tool_loop_reuses_duplicate_tool_result(self):
        """Repeated requests for the same HA data within one loop reuse the cached result."""
        llm = _ToolLLM(
            [
                ToolCompletion(
                    content="",
                    usage={},
                    tool_calls=[
                        ToolCall(id="call-1", name="get_simplified_ha_data"),
                        ToolCall(id="call-2", name="get_simplified_ha_data"),
                    ],
                    assistant_message={"role": "assistant", "content": "", "tool_calls": []},
                ),
                ToolCompletion(content="I checked it once.", usage={}),
            ]
        )
        agent = self._agent(llm)

        with patch(
            "wactorz.agents.home_assistant_agent.get_simplified_ha_data",
            new=AsyncMock(return_value={"entities": []}),
        ) as get_data:
            result = await agent._handle_other_request("summarize my home")

        self.assertEqual(result["result"], "I checked it once.")
        get_data.assert_awaited_once()

    async def test_other_tool_loop_stops_after_max_rounds(self):
        """The `other` tool loop has a hard round limit to avoid infinite LLM/tool cycles."""
        llm = _ToolLLM(
            [
                ToolCompletion(
                    content="",
                    usage={},
                    tool_calls=[ToolCall(id=f"call-{i}", name="get_simplified_ha_data")],
                    assistant_message={"role": "assistant", "content": "", "tool_calls": []},
                )
                for i in range(5)
            ]
        )
        agent = self._agent(llm)
        agent._other_tool_max_rounds = 3

        with patch(
            "wactorz.agents.home_assistant_agent.get_simplified_ha_data",
            new=AsyncMock(return_value={"entities": []}),
        ):
            result = await agent._handle_other_request("keep checking my home")

        self.assertEqual(result["error"], "tool_round_limit")
        self.assertIn("within 3 tool rounds", result["result"])

    async def test_other_tool_loop_provider_error_is_reported(self):
        """Provider tool-call failures are reported as user-visible HA tool errors."""
        agent = self._agent(_FailingToolLLM())

        result = await agent._handle_other_request("what is the kitchen temperature?")

        self.assertIn("Home Assistant tool request failed", result["result"])
        self.assertIn("provider does not support tools", result["error"])


if __name__ == "__main__":
    unittest.main()
