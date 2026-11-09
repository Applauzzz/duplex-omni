"""Focused tests for native vLLM tool calls in the duplex MiMo bridge."""

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


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def post(self, _url, *, json, headers):
        self.payloads.append((json, headers))
        return Response(self.responses.pop(0))


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_call_returns_placeholder_without_waiting(self):
        call = {"index": 0, "id": "reason-1", "type": "function",
                "function": {"name": "consult_reasoning_model",
                             "arguments": '{"task":"question","context":null}'}}
        client = Client([
            [{"choices": [{"delta": {"tool_calls": [call]}, "finish_reason": "tool_calls"}]}],
            [{"choices": [{"delta": {"content": "我正在分析，稍后告诉你。"}, "finish_reason": "stop"}]}],
        ])
        calls = []
        async def start(value):
            calls.append(value)
            return '{"status":"background_pending"}'
        context = {
            "agent_config": {"instructions": "test", "tools": [
                {"type": "function", "function": {"name": "consult_reasoning_model"}}]},
            "agent_tool_handler": lambda _call: None,
            "background_reasoning_handler": start,
            "background_reasoning_prompt": "background policy",
        }
        output = [part async for part in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply([self.audio()], history=[], prompt="test", context=context)]
        self.assertEqual(output, ["我正在分析，稍后告诉你。"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("tools", client.payloads[1][0])

    async def test_ready_result_only_has_no_rejected_audio_or_tools(self):
        client = Client([[{"choices": [{"delta": {"content": "之前问题的结果。"},
                                       "finish_reason": "stop"}]}]])
        context = {
            "agent_config": {"instructions": "test", "tools": self.tools()},
            "agent_tool_handler": lambda _call: None,
            "background_result_only": True,
            "background_reasoning_result": {"task_id": "id", "question": "old", "result": "answer"},
        }
        output = [part async for part in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply([], history=[], prompt="test", context=context)]
        self.assertEqual(output, ["之前问题的结果。"])
        payload = client.payloads[0][0]
        self.assertNotIn("tools", payload)
        self.assertEqual(len(payload["messages"]), 2)
        self.assertIn('"question": "old"', payload["messages"][-1]["content"])

    async def test_ready_result_combines_current_audio_and_old_question(self):
        call = {"index": 0, "id": "weather", "type": "function",
                "function": {"name": "weather_get", "arguments": "{}"}}
        client = Client([
            [{"choices": [{"delta": {"tool_calls": [call]}, "finish_reason": "tool_calls"}]}],
            [{"choices": [{"delta": {"content": "当前回答，加先前分析。"},
                                       "finish_reason": "stop"}]}]])
        tools = [{"type": "function", "function": {"name": name}}
                 for name in ("weather_get", "consult_reasoning_model")]
        async def execute(_call):
            context["agent_config"]["tools"] = tools
            return "weather result"
        context = {
            "agent_config": {"instructions": "test", "tools": tools},
            "agent_tool_handler": execute,
            "background_reasoning_result": {"task_id": "id", "question": "old", "result": "answer"},
        }
        output = [part async for part in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply([self.audio()], history=[], prompt="test", context=context)]
        self.assertEqual(output, ["当前回答，加先前分析。"])
        messages = client.payloads[0][0]["messages"]
        self.assertEqual(messages[1]["content"][0]["type"], "input_audio")
        self.assertIn('"question": "old"', messages[2]["content"])
        for payload, _headers in client.payloads:
            self.assertEqual([tool["function"]["name"] for tool in payload["tools"]],
                             ["weather_get"])
            self.assertIn("不得只宣布", payload["messages"][0]["content"])
            self.assertIn("不需要额外确认", payload["messages"][0]["content"])

    async def test_followup_reuses_historical_background_result(self):
        client = Client([[{"choices": [{"delta": {"content": "已有分析的详细讲解。"},
                                       "finish_reason": "stop"}]}]])
        async def execute(_call):
            self.fail("followup should reuse supplied result")
        result = {"task_id": "id", "question": "article", "result": "actual analysis"}
        context = {"agent_config": {"instructions": "test", "tools": self.tools()},
                   "agent_tool_handler": execute}
        output = [part async for part in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply(
                [self.audio()], history=[{"assistant": "要不要听？",
                                         "background_reasoning_result": result}],
                prompt="test", context=context)]
        self.assertEqual(output, ["已有分析的详细讲解。"])
        messages = client.payloads[0][0]["messages"]
        self.assertIn("不重新提交同一个分析任务", messages[0]["content"])
        self.assertIn("actual analysis", messages[1]["content"])
        self.assertEqual(messages[2]["role"], "assistant")

    async def test_mixed_background_tool_calls_rejected_before_execution(self):
        calls = [{"index": index, "id": f"call-{index}", "type": "function",
                  "function": {"name": name, "arguments": "{}"}}
                 for index, name in enumerate(("consult_reasoning_model", "search_web"))]
        client = Client([[{"choices": [{"delta": {"tool_calls": calls},
                                       "finish_reason": "tool_calls"}]}]])
        async def start(_call):
            self.fail("must not dispatch mixed calls")
        context = {
            "agent_config": {"instructions": "test", "tools": []},
            "agent_tool_handler": lambda _call: None,
            "background_reasoning_handler": start,
        }
        context["agent_config"]["tools"] = [
            {"type": "function", "function": {"name": name}}
            for name in ("consult_reasoning_model", "search_web")]
        with self.assertRaisesRegex(RuntimeError, "only tool call"):
            _ = [part async for part in AgenticMiMoChatProvider(
                client, "http://mimo").stream_reply([self.audio()], history=[], prompt="test", context=context)]

    @staticmethod
    def audio():
        return {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(b"\0\0" * 160).decode(),
            "format": "pcm16",
            "sample_rate_hz": 16000,
        }

    @staticmethod
    def tools():
        return [
            {"type": "function", "function": {
                "name": "search_web", "description": "Search current information.",
                "parameters": {"type": "object"},
            }},
            {"type": "function", "function": {
                "name": "get_current_datetime", "description": "Get Beijing time.",
                "parameters": {"type": "object"},
            }},
        ]

    async def test_native_request_exposes_all_tools_without_router(self):
        answer = {"choices": [{"delta": {"content": "普通回答。"},
                                "finish_reason": "stop"}]}
        # vLLM has already completed the response when finish_reason arrives;
        # the provider must not depend on a trailing [DONE] sentinel.
        client = Client([[answer]])
        context = {
            "request_id": "all-tools",
            "agent_config": {"instructions": "Use tools only when needed.",
                             "tools": self.tools()},
            "agent_tool_handler": lambda _call: None,
            "agent_tool_prompt": "Configured tool policy.",
            "agent_forced_prompt": "Configured forced policy.",
        }
        result = [item async for item in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply(
                [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(result, ["普通回答。"])
        self.assertEqual(len(client.payloads), 1)
        payload = client.payloads[0][0]
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertFalse(payload["parallel_tool_calls"])
        self.assertEqual([item["function"]["name"] for item in payload["tools"]],
                         ["search_web", "get_current_datetime"])
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["messages"][0]["content"],
                         "Base prompt\n\nAgent instructions:\nConfigured tool policy."
                         "\n\nConfigured forced policy.")

    async def test_fragmented_native_call_executes_and_continues(self):
        fragments = [
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "call_", "type": "function",
                "function": {"name": "search_", "arguments": "{\"query\":"},
            }]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "1",
                "function": {"name": "web", "arguments": "\"AI news\"}"},
            }]}, "finish_reason": "tool_calls"}]},
        ]
        answer = {"choices": [{"delta": {"content": "搜索回答。"},
                                "finish_reason": "stop"}]}
        client = Client([[*fragments, "[DONE]"], [answer, "[DONE]"]])
        calls = []

        async def handler(call):
            calls.append(call)
            return '{"results":[]}'

        context = {
            "request_id": "fragmented",
            "agent_config": {"instructions": "Search current facts.",
                             "tools": self.tools()},
            "agent_tool_handler": handler,
        }
        result = [item async for item in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply(
                [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(result, ["搜索回答。"])
        self.assertEqual(calls[0]["id"], "call_1")
        self.assertEqual(calls[0]["function"], {
            "name": "search_web", "arguments": '{"query":"AI news"}',
        })
        self.assertEqual(client.payloads[1][0]["messages"][-1], {
            "role": "tool", "tool_call_id": "call_1",
            "content": '{"results":[]}',
        })

    async def test_handoff_refreshes_instructions_and_tools(self):
        call = {"choices": [{"delta": {"tool_calls": [{
            "index": 0, "id": "call_handoff", "type": "function",
            "function": {"name": "transfer_to_poet", "arguments": "{}"},
        }]}, "finish_reason": "tool_calls"}]}
        answer = {"choices": [{"delta": {"content": "春风拂柳。"},
                                "finish_reason": "stop"}]}
        client = Client([[call, "[DONE]"], [answer, "[DONE]"]])
        context = {
            "request_id": "handoff",
            "agent_config": {"instructions": "Handle greetings.", "tools": [{
                "type": "function", "function": {
                    "name": "transfer_to_poet", "description": "Transfer",
                    "parameters": {},
                },
            }]},
        }

        async def handler(_call):
            context["agent_config"] = {
                "instructions": "Write concise poems.", "tools": [],
            }
            return '{"assistant":"poet"}'

        context["agent_tool_handler"] = handler
        result = [item async for item in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply(
                [self.audio()], history=[], prompt="Base prompt", context=context)]

        self.assertEqual(result, ["春风拂柳。"])
        follow_up = client.payloads[1][0]
        self.assertIn("Write concise poems.", follow_up["messages"][0]["content"])
        self.assertNotIn("tools", follow_up)

    async def test_no_tools_keeps_direct_multimodal_completion(self):
        answer = {"choices": [{"delta": {"content": "看到了红绿蓝。"},
                                "finish_reason": "stop"}]}
        client = Client([[answer, "[DONE]"]])
        context = {
            "request_id": "vision", "video_frames": "jpeg-sequence",
            "agent_config": {"instructions": "Answer from video.", "tools": []},
            "agent_tool_handler": lambda _call: None,
        }
        result = [item async for item in AgenticMiMoChatProvider(
            client, "http://mimo").stream_reply(
                [self.audio()], history=[], prompt="Base", context=context)]

        self.assertEqual(result, ["看到了红绿蓝。"])
        payload = client.payloads[0][0]
        self.assertNotIn("tools", payload)
        self.assertEqual([part["type"] for part in payload["messages"][-1]["content"]],
                         ["video_url", "input_audio", "text"])

    async def test_unknown_native_tool_is_rejected_before_execution(self):
        call = {"choices": [{"delta": {"tool_calls": [{
            "index": 0, "id": "call_bad", "type": "function",
            "function": {"name": "delete_everything", "arguments": "{}"},
        }]}, "finish_reason": "tool_calls"}]}
        client = Client([[call, "[DONE]"]])
        context = {
            "request_id": "unknown",
            "agent_config": {"instructions": "Use tools.", "tools": self.tools()},
            "agent_tool_handler": lambda _call: None,
        }
        with self.assertRaisesRegex(RuntimeError, "unknown tool"):
            _ = [item async for item in AgenticMiMoChatProvider(
                client, "http://mimo").stream_reply(
                    [self.audio()], history=[], prompt="Base", context=context)]


if __name__ == "__main__":
    unittest.main(verbosity=2)
