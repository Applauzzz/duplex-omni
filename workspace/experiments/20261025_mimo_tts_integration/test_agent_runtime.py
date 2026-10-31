"""Focused tests for the duplex MiMo bridge to the OpenAI Agents SDK."""

import base64
import json
import unittest

from agent_runtime import AgenticMiMoChatProvider


class Response:
    status = 200

    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    @property
    def content(self):
        async def stream():
            for event in self.events:
                if event == "[DONE]":
                    yield b"data: [DONE]\n"
                else:
                    yield ("data: " + json.dumps(event) + "\n").encode()
                yield b"\n"
        return stream()

    async def json(self):
        return self.events


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def post(self, _url, *, json, headers):
        self.payloads.append((json, headers))
        return Response(self.responses.pop(0))


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def audio():
        return {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(b"\0\0" * 160).decode(),
            "format": "pcm16",
            "sample_rate_hz": 16000,
        }

    async def test_tool_call_waits_for_sdk_output_then_returns_final_text(self):
        tool_call = {"choices": [{"delta": {"tool_calls": [{
            "index": 0,
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup_weather", "arguments": "{\"city\":\"北京\"}"},
        }]}, "finish_reason": "tool_calls"}]}
        answer = {"choices": [{"delta": {"content": "北京晴。"},
                               "finish_reason": "stop"}]}
        client = Client([[tool_call, "[DONE]"], [answer, "[DONE]"]])
        seen = []

        async def tool_handler(call):
            seen.append(call)
            return '{"condition":"sunny"}'

        context = {
            "request_id": "tool",
            "agent_config": {
                "instructions": "Use tools for current weather.",
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "lookup_weather",
                        "description": "Look up weather",
                        "parameters": {"type": "object"},
                    },
                }],
            },
            "agent_tool_handler": tool_handler,
        }
        provider = AgenticMiMoChatProvider(
            client, "http://mimo", native_tool_calls=True)
        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["北京晴。"])
        self.assertEqual(seen[0]["id"], "call_1")
        tool_message = client.payloads[1][0]["messages"][-1]
        self.assertEqual(tool_message, {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"condition":"sunny"}',
        })

    async def test_handoff_config_update_applies_to_follow_up_round(self):
        handoff = {"choices": [{"delta": {"tool_calls": [{
            "index": 0,
            "id": "call_handoff",
            "type": "function",
            "function": {"name": "transfer_to_poet", "arguments": "{}"},
        }]}, "finish_reason": "tool_calls"}]}
        answer = {"choices": [{"delta": {"content": "春风拂柳。"},
                               "finish_reason": "stop"}]}
        client = Client([[handoff, "[DONE]"], [answer, "[DONE]"]])
        context = {
            "request_id": "handoff",
            "agent_config": {
                "instructions": "Handle greetings.",
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "transfer_to_poet",
                        "description": "Transfer to poet",
                        "parameters": {"type": "object"},
                    },
                }],
            },
        }

        async def tool_handler(_call):
            context["agent_config"] = {
                "instructions": "Write concise poems.",
                "tools": [],
            }
            return '{"assistant":"poet"}'

        context["agent_tool_handler"] = tool_handler
        provider = AgenticMiMoChatProvider(
            client, "http://mimo", native_tool_calls=True)
        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["春风拂柳。"])
        self.assertIn(
            "Write concise poems.",
            client.payloads[1][0]["messages"][0]["content"],
        )
        self.assertNotIn("tools", client.payloads[1][0])

    async def test_prompt_envelope_uses_json_string_arguments(self):
        client = Client([
            {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "kind": "tool_call",
                            "name": "transfer_to_poet",
                            "arguments": "{}",
                            "content": "",
                        }),
                    },
                }],
            },
            [
                {"choices": [{"delta": {"content": "春风拂柳。"},
                              "finish_reason": "stop"}]},
                "[DONE]",
            ],
        ])
        seen = []
        context = {
            "request_id": "prompt-handoff",
            "agent_config": {
                "instructions": "Transfer to poet.",
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "transfer_to_poet",
                        "description": "Transfer to poet",
                        "parameters": {"type": "object"},
                    },
                }],
            },
        }

        async def tool_handler(call):
            seen.append(call)
            context["agent_config"] = {
                "instructions": "Write concise poems.",
                "tools": [],
            }
            return '{"assistant":"poet"}'

        context["agent_tool_handler"] = tool_handler
        provider = AgenticMiMoChatProvider(client, "http://mimo")
        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["春风拂柳。"])
        self.assertEqual(seen[0]["function"]["arguments"], "{}")
        schema = client.payloads[0][0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["arguments"]["type"], "string")
        self.assertNotIn("response_format", client.payloads[1][0])

    async def test_empty_final_retries_once_with_nonempty_correction(self):
        client = Client([
            {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "kind": "final",
                            "name": "",
                            "arguments": "{}",
                            "content": "",
                        }),
                    },
                }],
            },
            {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "kind": "final",
                            "name": "",
                            "arguments": "{}",
                            "content": "这是重试后的回答。",
                        }),
                    },
                }],
            },
        ])
        provider = AgenticMiMoChatProvider(client, "http://mimo")
        context = {
            "request_id": "empty-final",
            "agent_config": {
                "instructions": "Answer directly.",
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "optional_lookup",
                        "description": "Optional lookup",
                        "parameters": {"type": "object"},
                    },
                }],
            },
            "agent_tool_handler": lambda _call: None,
        }

        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["这是重试后的回答。"])
        correction = client.payloads[1][0]["messages"][-1]
        self.assertEqual(correction["role"], "system")
        self.assertIn("previous final response was empty", correction["content"])
        schema = client.payloads[0][0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["content"]["minLength"], 1)

    async def test_no_tools_uses_direct_multimodal_stream(self):
        client = Client([[
            {"choices": [{"delta": {"content": "看到了红绿蓝。"},
                          "finish_reason": "stop"}]},
            "[DONE]",
        ]])
        provider = AgenticMiMoChatProvider(client, "http://mimo")
        context = {
            "request_id": "direct-vision",
            "video_frames": "jpeg-sequence",
            "agent_config": {
                "instructions": "Answer from the video.",
                "tools": [],
            },
            "agent_tool_handler": lambda _call: None,
        }

        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["看到了红绿蓝。"])
        payload = client.payloads[0][0]
        self.assertNotIn("tools", payload)
        self.assertNotIn("response_format", payload)
        self.assertEqual(
            [part["type"] for part in payload["messages"][-1]["content"]],
            ["video_url", "input_audio", "text"],
        )

    async def test_recovers_first_allowed_xml_tool_from_mixed_envelope(self):
        mixed = (
            '{"kind":"tool_call","name":"search_web","arguments":'
            '"{\\"query\\":\\"今天是几号\\",\\"num\\":3}。}"}'
            '<tool_call><function=search_web>'
            '<parameter=query>今天是几号</parameter>'
            '<parameter=num>3</parameter>'
            '</function></tool_call>'
            '<tool_call><function=search_web>'
            '<parameter=query>重复调用</parameter>'
            '</function></tool_call>'
        )
        client = Client([
            {"choices": [{"message": {"content": mixed}}]},
            [[
                {"choices": [{"delta": {"content": "今天是星期六。"},
                              "finish_reason": "stop"}]},
                "[DONE]",
            ]][0],
        ])
        calls = []
        context = {
            "request_id": "recover-xml",
            "agent_config": {
                "instructions": "Use tools.",
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "description": "Search",
                        "parameters": {"type": "object"},
                    },
                }],
            },
        }

        async def handler(call):
            calls.append(call)
            context["agent_config"] = {
                "instructions": "Answer.",
                "tools": [],
            }
            return '{"results":[]}'

        context["agent_tool_handler"] = handler
        provider = AgenticMiMoChatProvider(client, "http://mimo")
        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["今天是星期六。"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "search_web")
        self.assertEqual(
            json.loads(calls[0]["function"]["arguments"]),
            {"query": "今天是几号", "num": 3},
        )

    def test_recovery_rejects_unknown_xml_tool(self):
        recovered = AgenticMiMoChatProvider._recover_tool_envelope(
            (
                "<tool_call><function=delete_everything>"
                "<parameter=confirm>true</parameter>"
                "</function></tool_call>"
            ),
            [{
                "type": "function",
                "function": {"name": "search_web"},
            }],
        )
        self.assertIsNone(recovered)

    def test_recovers_allowed_tool_from_malformed_json_prefix(self):
        content = (
            '{"kind": "tool_call", "name": "search_web", '
            '"arguments": "{\\"query\\": \\"北京后天天气预报\\", '
            '\\"num\\": 5}\'}'
            '</think>抱歉，我无法回答这个问题。'
        )
        recovered = AgenticMiMoChatProvider._recover_tool_envelope(
            content,
            [{
                "type": "function",
                "function": {"name": "search_web"},
            }],
        )

        self.assertEqual(recovered["name"], "search_web")
        self.assertEqual(
            json.loads(recovered["arguments"]),
            {"query": "北京后天天气预报", "num": 5},
        )

    def test_malformed_json_prefix_rejects_unknown_or_incomplete_tool(self):
        tools = [{
            "type": "function",
            "function": {"name": "search_web"},
        }]
        unknown = AgenticMiMoChatProvider._recover_tool_envelope(
            (
                '{"kind":"tool_call","name":"delete_everything",'
                '"arguments":"{\\"confirm\\":true}"}'
            ),
            tools,
        )
        incomplete = AgenticMiMoChatProvider._recover_tool_envelope(
            (
                '{"kind":"tool_call","name":"search_web",'
                '"arguments":"{\\"query\\":\\"weather\\""'
            ),
            tools,
        )
        self.assertIsNone(unknown)
        self.assertIsNone(incomplete)

    async def test_interaction_policy_is_appended_after_agent_instructions(self):
        client = Client([[
            {"choices": [{"delta": {"content": "listening"},
                          "finish_reason": "stop"}]},
            "[DONE]",
        ]])
        provider = AgenticMiMoChatProvider(client, "http://mimo")
        context = {
            "request_id": "interaction-policy",
            "agent_config": {
                "instructions": "Always search for current facts.",
                "tools": [],
            },
            "agent_tool_handler": lambda _call: None,
        }

        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base listening policy", context=context)]

        self.assertEqual(deltas, ["listening"])
        system = client.payloads[0][0]["messages"][0]["content"]
        self.assertLess(
            system.index("Always search for current facts."),
            system.index("Highest-priority interaction policy:"),
        )
        self.assertIn("do not call any tool or handoff", system)

    async def test_multi_tool_route_none_uses_direct_answer(self):
        client = Client([
            {
                "choices": [{
                    "message": {"content": '{"tool":"none"}'},
                }],
            },
            [
                {"choices": [{"delta": {"content": "普通回答。"},
                              "finish_reason": "stop"}]},
                "[DONE]",
            ],
        ])
        calls = []
        provider = AgenticMiMoChatProvider(client, "http://mimo")
        context = {
            "request_id": "route-none",
            "agent_config": {
                "instructions": "Use tools only when needed.",
                "tools": self._search_and_time_tools(),
            },
            "agent_tool_handler": lambda call: calls.append(call),
        }

        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["普通回答。"])
        self.assertEqual(calls, [])
        self.assertNotIn("response_format", client.payloads[1][0])

    async def test_multi_tool_route_exposes_only_selected_search(self):
        client = Client([
            {"choices": [{"message": {"content": '{"tool":"search_web"}'}}]},
            {"choices": [{"message": {"content": json.dumps({
                "kind": "tool_call",
                "name": "search_web",
                "arguments": '{"query":"AI news","num":3}',
                "content": "",
            })}}]},
            [
                {"choices": [{"delta": {"content": "搜索回答。"},
                              "finish_reason": "stop"}]},
                "[DONE]",
            ],
        ])
        calls = []

        async def handler(call):
            calls.append(call)
            return '{"results":[]}'

        provider = AgenticMiMoChatProvider(client, "http://mimo")
        context = {
            "request_id": "route-search",
            "agent_config": {
                "instructions": "Route tools.",
                "tools": self._search_and_time_tools(),
            },
            "agent_tool_handler": handler,
        }

        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["搜索回答。"])
        self.assertEqual([call["function"]["name"] for call in calls], ["search_web"])
        envelope = client.payloads[1][0]
        self.assertEqual(
            [tool["function"]["name"] for tool in
             json.loads(envelope["messages"][0]["content"].split(
                 "Agent tool protocol:\n", 1)[1])["available_tools"]],
            ["search_web"],
        )
        self.assertNotIn("response_format", client.payloads[2][0])

    async def test_multi_tool_route_exposes_only_selected_datetime(self):
        client = Client([
            {
                "choices": [{
                    "message": {"content": '{"tool":"get_current_datetime"}'},
                }],
            },
            {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "kind": "tool_call",
                            "name": "get_current_datetime",
                            "arguments": "{}",
                            "content": "",
                        }),
                    },
                }],
            },
            [
                {"choices": [{"delta": {"content": "北京时间回答。"},
                              "finish_reason": "stop"}]},
                "[DONE]",
            ],
        ])
        calls = []

        async def handler(call):
            calls.append(call)
            return '{"timeZone":"Asia/Shanghai"}'

        provider = AgenticMiMoChatProvider(client, "http://mimo")
        context = {
            "request_id": "route-time",
            "agent_config": {
                "instructions": "Route tools.",
                "tools": self._search_and_time_tools(),
            },
            "agent_tool_handler": handler,
        }

        deltas = [item async for item in provider.stream_reply(
            [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(deltas, ["北京时间回答。"])
        self.assertEqual(
            [call["function"]["name"] for call in calls],
            ["get_current_datetime"],
        )

    @staticmethod
    def _search_and_time_tools():
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search current information.",
                    "parameters": {"type": "object"},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_datetime",
                    "description": "Get Beijing date and time.",
                    "parameters": {"type": "object"},
                },
            },
        ]


if __name__ == "__main__":
    unittest.main(verbosity=2)
