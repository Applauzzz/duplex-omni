"""MiMo tool-call loop bridged to an external OpenAI Agents SDK session."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
import uuid

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
TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*<function=(?P<name>[A-Za-z0-9_]+)>"
    r"(?P<body>.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
TOOL_PARAMETER_PATTERN = re.compile(
    r"<parameter=(?P<name>[A-Za-z0-9_]+)>"
    r"(?P<value>.*?)</parameter>",
    re.DOTALL,
)


class AgenticMiMoChatProvider:
    """Pause MiMo tool calls while the Agents SDK executes tools and handoffs."""

    def __init__(self, client, mimo_url: str, *, model: str = "mimo-v2.6-flash",
                 max_tool_rounds: int = 8, native_tool_calls: bool = False) -> None:
        self.client = client
        self.mimo_url = mimo_url.rstrip("/")
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.native_tool_calls = native_tool_calls

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
        if len(tools) > 1:
            selected_name = await self._route_tool(
                messages,
                tools,
                f"{request_id}-route",
            )
            tools = [
                item for item in tools
                if item.get("function", {}).get("name") == selected_name
            ]
            LOG.info(
                "MiMo agent tool route request_id=%s selected=%s",
                request_id,
                selected_name or "none",
            )
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
            elif self.native_tool_calls:
                text, tool_calls = await self._native_completion(
                    messages, list(tools), f"{request_id}-agent-{round_index}")
            else:
                text, tool_calls = await self._prompt_completion(
                    messages, list(tools), f"{request_id}-agent-{round_index}")
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
                output = await tool_handler(call)
                if not isinstance(output, str):
                    raise RuntimeError("Agent tool output must be a string")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                })
            # One external action per user turn. The result is enough context for
            # the next round, which must produce the final response directly.
            tools = []
            refreshed = context.get("agent_config")
            if isinstance(refreshed, Mapping):
                instructions = refreshed.get("instructions", instructions)
        raise RuntimeError("MiMo agent exceeded max_tool_rounds")

    async def _route_tool(self, messages, tools, request_id):
        names = [
            item.get("function", {}).get("name")
            for item in tools if isinstance(item, Mapping)
        ]
        names = [name for name in names if isinstance(name, str) and name]
        if not names:
            return None
        descriptions = [
            {
                "name": item.get("function", {}).get("name"),
                "description": item.get("function", {}).get("description", ""),
            }
            for item in tools if isinstance(item, Mapping)
        ]
        route_messages = [
            {
                "role": "system",
                "content": (
                    "Select at most one tool for the current user turn. "
                    "Use only the current user audio/video, not previous tool calls. "
                    "Choose none when the current request can be answered without a tool. "
                    "Date/time questions select get_current_datetime only. "
                    "News, weather, latest or changing public information selects "
                    "search_web only. Available tools: "
                    + json.dumps(descriptions, ensure_ascii=False)
                ),
            },
            messages[-1],
        ]
        payload = {
            "model": self.model,
            "messages": route_messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "duplex_tool_route",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "enum": ["none", *names],
                            },
                        },
                        "required": ["tool"],
                        "additionalProperties": False,
                    },
                },
            },
            "max_tokens": 32,
            "temperature": 0.0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        async with self.client.post(
            self.mimo_url + "/v1/chat/completions", json=payload,
            headers={"X-Request-Id": request_id},
        ) as response:
            if response.status != 200:
                body = await response.read()
                raise RuntimeError(
                    f"MiMo Agent Route HTTP {response.status}: {body[:200]!r}")
            event = await response.json()
        try:
            content = event["choices"][0]["message"]["content"]
            selected = json.loads(content)["tool"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"MiMo Agent returned an invalid tool route: {str(locals().get('content'))[:300]!r}"
            ) from error
        if selected == "none":
            return None
        if selected not in names:
            raise RuntimeError(f"MiMo Agent routed to unknown tool: {selected!r}")
        return selected

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
                    return text, [calls[index] for index in sorted(calls)]
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
            raise RuntimeError("MiMo Agent disconnected before DONE")

    async def _prompt_completion(self, messages, tools, request_id):
        allowed_kinds = ["tool_call", "final"] if tools else ["final"]
        protocol = {
            "available_tools": tools,
            "rules": [
                (
                    "Highest priority: if the user is not intentionally interacting "
                    "with the assistant, do not call a tool and return final content "
                    "exactly listening."
                ),
                "Return kind=tool_call when a tool or handoff is needed.",
                "For tool_call, name must exactly match an available function name.",
                "For tool_call, arguments must be a JSON object encoded as a string.",
                "Return kind=final only when no tool call is needed.",
                "Put the user-facing answer only in content.",
            ],
        }
        request_messages = [dict(item) for item in messages]
        request_messages[0] = {
            "role": "system",
            "content": (
                str(request_messages[0]["content"])
                + "\n\nAgent tool protocol:\n"
                + json.dumps(protocol, ensure_ascii=False)
            ),
        }
        payload = {
            "model": self.model,
            "messages": request_messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "duplex_agent_turn",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": allowed_kinds,
                            },
                            "name": {"type": "string"},
                            "arguments": {"type": "string"},
                            "content": {"type": "string", "minLength": 1},
                        },
                        "required": ["kind", "name", "arguments", "content"],
                        "additionalProperties": False,
                    },
                },
            },
            "max_tokens": 512,
            "temperature": 0.0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        async with self.client.post(
            self.mimo_url + "/v1/chat/completions", json=payload,
            headers={"X-Request-Id": request_id},
        ) as response:
            if response.status != 200:
                body = await response.read()
                raise RuntimeError(
                    f"MiMo Agent Envelope HTTP {response.status}: {body[:200]!r}")
            event = await response.json()
        try:
            content = event["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raw = locals().get("content")
            result = self._recover_tool_envelope(str(raw), tools)
            if result is None:
                raise RuntimeError(
                    f"MiMo Agent returned an invalid tool envelope: {str(raw)[:500]!r}"
                ) from error
            LOG.warning(
                "Recovered malformed MiMo tool envelope request_id=%s tool=%s",
                request_id,
                result.get("name"),
            )
        if result.get("kind") == "final":
            final = result.get("content")
            if not isinstance(final, str):
                raise RuntimeError("MiMo Agent final content must be a string")
            return final, []
        if result.get("kind") != "tool_call":
            raise RuntimeError("MiMo Agent envelope kind is invalid")
        name = result.get("name")
        arguments = result.get("arguments")
        allowed = {
            item.get("function", {}).get("name")
            for item in tools if isinstance(item, Mapping)
        }
        if not isinstance(name, str) or name not in allowed:
            raise RuntimeError(f"MiMo Agent requested unknown tool: {name!r}")
        if not isinstance(arguments, str):
            raise RuntimeError("MiMo Agent tool arguments must be a JSON string")
        try:
            parsed_arguments = json.loads(
                arguments.strip().rstrip("。；;，,"))
        except json.JSONDecodeError as error:
            raise RuntimeError("MiMo Agent tool arguments are invalid JSON") from error
        if not isinstance(parsed_arguments, dict):
            raise RuntimeError("MiMo Agent tool arguments must encode an object")
        call = {
            "id": "call-" + uuid.uuid4().hex[:16],
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(parsed_arguments, ensure_ascii=False),
            },
        }
        return "", [call]

    @staticmethod
    def _recover_tool_envelope(content, tools):
        allowed = {
            item.get("function", {}).get("name")
            for item in tools if isinstance(item, Mapping)
        }
        match = TOOL_CALL_PATTERN.search(content)
        if match is not None and match.group("name") in allowed:
            arguments = {}
            for parameter in TOOL_PARAMETER_PATTERN.finditer(match.group("body")):
                name = parameter.group("name")
                value = parameter.group("value").strip()
                if name == "num":
                    try:
                        arguments[name] = int(value)
                        continue
                    except ValueError:
                        pass
                arguments[name] = value
            return {
                "kind": "tool_call",
                "name": match.group("name"),
                "arguments": json.dumps(arguments, ensure_ascii=False),
                "content": "",
            }
        return AgenticMiMoChatProvider._recover_json_prefix_tool(
            content, allowed)

    @staticmethod
    def _recover_json_prefix_tool(content, allowed):
        name_match = re.search(
            r'"name"\s*:\s*"(?P<name>[A-Za-z0-9_]+)"',
            content,
        )
        if name_match is None or name_match.group("name") not in allowed:
            return None
        marker = re.search(r'"arguments"\s*:\s*"', content)
        if marker is None:
            return None
        source = content[marker.end():]
        decoded = []
        depth = 0
        started = False
        in_string = False
        escaped = False
        index = 0
        escape_map = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        while index < len(source):
            char = source[index]
            if char == "\\" and index + 1 < len(source):
                next_char = source[index + 1]
                if next_char == "u" and index + 5 < len(source):
                    try:
                        char = chr(int(source[index + 2:index + 6], 16))
                        index += 6
                    except ValueError:
                        return None
                elif next_char in escape_map:
                    char = escape_map[next_char]
                    index += 2
                else:
                    return None
            else:
                index += 1
            if not started:
                if char.isspace():
                    continue
                if char != "{":
                    return None
                started = True
                depth = 1
                decoded.append(char)
                continue
            decoded.append(char)
            if escaped:
                escaped = False
                continue
            if in_string and char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
            elif not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        break
        if not started or depth != 0:
            return None
        candidate = "".join(decoded)
        try:
            arguments = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(arguments, dict):
            return None
        return {
            "kind": "tool_call",
            "name": name_match.group("name"),
            "arguments": json.dumps(arguments, ensure_ascii=False),
            "content": "",
        }

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
