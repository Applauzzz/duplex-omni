"""MiMo tool-call loop bridged to an external OpenAI Agents SDK session."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence

from semantic_vad import _sse_data, build_chat_messages


ToolCallHandler = Callable[[dict[str, object]], Awaitable[str]]
LOG = logging.getLogger("mimo_tts.agent_runtime")
AGENT_INTERACTION_POLICY = """Highest-priority interaction policy:
First determine whether the user is intentionally interacting with the assistant.
If the audio is self-talk, background conversation, speech directed at another person,
or otherwise has no active request for the assistant, do not call any tool or handoff
and return exactly listening as the final content.
Only after confirming active assistant-directed intent may you apply Agent instructions,
use visual context, call tools, hand off, or answer the request."""
class AgenticMiMoChatProvider:
    """Pause MiMo tool calls while the Agents SDK executes tools and handoffs."""

    def __init__(self, client, mimo_url: str, *, model: str = "mimo-v2.6-flash",
                 max_tool_rounds: int = 8, native_tool_calls: bool = True) -> None:
        if not native_tool_calls:
            raise ValueError("Agentic MiMo requires native vLLM tool calls")
        self.client = client
        self.mimo_url = mimo_url.rstrip("/")
        self.model = model
        self.max_tool_rounds = max_tool_rounds

    async def stream_reply(self, audio_chunks, *, history, prompt, context):
        agent_config = context.get("agent_config")
        tool_handler = context.get("agent_tool_handler")
        if not isinstance(agent_config, Mapping):
            raise RuntimeError("Agent session config is not initialized")
        if not callable(tool_handler):
            raise RuntimeError("Agent tool handler is not initialized")
        instructions = agent_config.get("instructions")
        tools = agent_config.get("tools", [])
        if not isinstance(instructions, str) or not instructions.strip():
            raise RuntimeError("Agent session requires non-empty instructions")
        if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
            raise RuntimeError("Agent session tools must be an array")
        messages = build_chat_messages(
            audio_chunks, history=history, prompt=prompt, context=context)
        request_id = str(context.get("request_id") or "agent-chat")
        tools = list(tools)
        empty_final_retried = False
        for round_index in range(self.max_tool_rounds):
            messages[0] = {
                "role": "system",
                "content": (
                    prompt
                    + "\n\nAgent instructions:\n"
                    + instructions.strip()
                    + "\n\n"
                    + AGENT_INTERACTION_POLICY
                ),
            }
            if not tools:
                text = await self._direct_completion(
                    messages, f"{request_id}-agent-{round_index}")
                tool_calls = []
            else:
                text, tool_calls, finish_reason = await self._native_completion(
                    messages, list(tools), f"{request_id}-agent-{round_index}")
                LOG.info(
                    "MiMo agent round completed request_id=%s round=%s finish=%s "
                    "text_chars=%s tools=%s",
                    request_id,
                    round_index,
                    finish_reason,
                    len(text),
                    [call.get("function", {}).get("name") for call in tool_calls],
                )
            if not tool_calls:
                if not text.strip():
                    if empty_final_retried:
                        raise RuntimeError(
                            "MiMo agent returned no reply text after one retry")
                    empty_final_retried = True
                    LOG.warning(
                        "MiMo agent returned empty final; retrying request_id=%s round=%s",
                        request_id,
                        round_index,
                    )
                    messages.append({
                        "role": "system",
                        "content": (
                            "The previous final response was empty. Return a non-empty "
                            "user-facing answer in content, or call an available tool."
                        ),
                    })
                    continue
                yield text
                return
            messages.append({"role": "assistant", "content": text or None,
                             "tool_calls": tool_calls})
            for call in tool_calls:
                self._validate_tool_call(call, tools)
                LOG.info(
                    "MiMo agent waiting for tool request_id=%s call_id=%s name=%s",
                    request_id,
                    call["id"],
                    call["function"]["name"],
                )
                try:
                    output = await asyncio.wait_for(tool_handler(call), timeout=120)
                except TimeoutError as error:
                    raise RuntimeError(
                        f"Agent tool timed out: {call['function']['name']}") from error
                if not isinstance(output, str):
                    raise RuntimeError("Agent tool output must be a string")
                LOG.info(
                    "MiMo agent tool completed request_id=%s call_id=%s name=%s",
                    request_id,
                    call["id"],
                    call["function"]["name"],
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                })
            refreshed = context.get("agent_config")
            if isinstance(refreshed, Mapping):
                instructions = refreshed.get("instructions", instructions)
                refreshed_tools = refreshed.get("tools", tools)
                if (isinstance(refreshed_tools, Sequence)
                        and not isinstance(refreshed_tools, (str, bytes))):
                    tools = list(refreshed_tools)
        raise RuntimeError("MiMo agent exceeded max_tool_rounds")

    async def _direct_completion(self, messages, request_id):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.0,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        text = ""
        finish_reason = None
        async with self.client.post(
            self.mimo_url + "/v1/chat/completions", json=payload,
            headers={"X-Request-Id": request_id},
        ) as response:
            if response.status != 200:
                body = await response.read()
                raise RuntimeError(
                    f"MiMo Agent Direct HTTP {response.status}: {body[:200]!r}")
            async for data in _sse_data(response.content):
                if data == "[DONE]":
                    if finish_reason is None:
                        raise RuntimeError(
                            "MiMo Agent Direct ended without finish_reason")
                    return text
                event = json.loads(data)
                if not isinstance(event, dict) or event.get("error"):
                    raise RuntimeError("MiMo Agent Direct returned an error event")
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {})
                    content = delta.get("content")
                    if isinstance(content, str):
                        text += content
                    if delta.get("tool_calls") or delta.get("function_call"):
                        raise RuntimeError(
                            "MiMo Agent Direct returned an unexpected tool call")
                    reason = choice.get("finish_reason")
                    if reason is not None:
                        finish_reason = reason
                        return text
            raise RuntimeError("MiMo Agent Direct disconnected before DONE")

    async def _native_completion(self, messages, tools, request_id):
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": 1024,
            "temperature": 0.0,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        text = ""
        calls: dict[int, dict[str, object]] = {}
        finish_reason = None
        async with self.client.post(
            self.mimo_url + "/v1/chat/completions", json=payload,
            headers={"X-Request-Id": request_id},
        ) as response:
            if response.status != 200:
                body = await response.read()
                raise RuntimeError(f"MiMo Agent HTTP {response.status}: {body[:200]!r}")
            async for data in _sse_data(response.content):
                if data == "[DONE]":
                    if finish_reason is None:
                        raise RuntimeError("MiMo Agent ended without finish_reason")
                    return text, [calls[index] for index in sorted(calls)], finish_reason
                event = json.loads(data)
                if not isinstance(event, dict) or event.get("error"):
                    raise RuntimeError("MiMo Agent returned an error event")
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {})
                    content = delta.get("content")
                    if isinstance(content, str):
                        text += content
                    for item in delta.get("tool_calls") or []:
                        self._merge_tool_call(calls, item)
                    reason = choice.get("finish_reason")
                    if reason is not None:
                        finish_reason = reason
                        return (
                            text,
                            [calls[index] for index in sorted(calls)],
                            finish_reason,
                        )
            raise RuntimeError("MiMo Agent disconnected before DONE")


    @staticmethod
    def _validate_tool_call(call, tools):
        allowed = {
            item.get("function", {}).get("name")
            for item in tools if isinstance(item, Mapping)
        }
        function = call.get("function") if isinstance(call, Mapping) else None
        name = function.get("name") if isinstance(function, Mapping) else None
        arguments = function.get("arguments") if isinstance(function, Mapping) else None
        if not isinstance(call.get("id"), str) or not call["id"]:
            raise RuntimeError("MiMo Agent tool call is missing an id")
        if not isinstance(name, str) or name not in allowed:
            raise RuntimeError(f"MiMo Agent requested unknown tool: {name!r}")
        if not isinstance(arguments, str):
            raise RuntimeError("MiMo Agent tool arguments must be a JSON string")
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise RuntimeError("MiMo Agent tool arguments are invalid JSON") from error
        if not isinstance(parsed, dict):
            raise RuntimeError("MiMo Agent tool arguments must encode an object")

    @staticmethod
    def _merge_tool_call(calls, item):
        index = item.get("index", 0)
        call = calls.setdefault(index, {
            "id": "", "type": "function",
            "function": {"name": "", "arguments": ""},
        })
        if isinstance(item.get("id"), str):
            call["id"] += item["id"]
        function = item.get("function") or {}
        if isinstance(function.get("name"), str):
            call["function"]["name"] += function["name"]
        if isinstance(function.get("arguments"), str):
            call["function"]["arguments"] += function["arguments"]
