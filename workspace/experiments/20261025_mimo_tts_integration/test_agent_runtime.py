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
