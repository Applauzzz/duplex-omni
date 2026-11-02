"""Session-fenced native Mac echo bridge; no local executor or model imports.

Wire contract follows h20_duplex_fc_dev/webapp/fc_protocol.py (v1).
Remembered browser grants are managed independently by browser_trust.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import WSMsgType, web

PROTOCOL = "duplex-mac-tools/v1"
CORRELATION = ("device_id", "session_id", "generation_id", "call_id", "invocation_id")
PARAMETERS = {
    "type": "object", "properties": {"text": {"type": "string", "maxLength": 200}},
    "required": ["text"], "additionalProperties": False,
}
TOOL = {"type": "function", "function": {
    "name": "demo_echo",
    "description": "Use the paired Mac echo tool only when the user requests an echo.",
    "parameters": PARAMETERS,
}}


class MacToolError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              MacToolError("invalid_json_number")))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise MacToolError("invalid_json") from None


def require(condition, code):
    if not condition:
        raise MacToolError(code)


def valid_id(value):
    return (isinstance(value, str) and 1 <= len(value) <= 256
            and all("!" <= c <= "~" for c in value))


def outcome(status, code=None, text=None):
    return {
        "status": status,
        "summary": "Mac echo completed" if status == "succeeded" else code or status,
        "data": {"text": text} if status == "succeeded" else None,
        "error": None if status == "succeeded" else {
            "code": code or status, "message": code or status, "retryable": False,
        },
    }


@dataclass
class Binding:
    session_id: str
    send: object
    generation: int = 0
    device_id: str | None = None
    digest: str | None = None
    revision: str = field(default_factory=lambda: uuid.uuid4().hex + ".0")
    peer: object = None
    calls: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    executing: set = field(default_factory=set)
    closed: bool = False


class EchoBridge:
    def __init__(self, auth_file=None, audit_file=None, *, timeout=5.0):
        require((auth_file is None) == (audit_file is None), "mac_bridge_config_incomplete")
        self.auth_file = Path(auth_file) if auth_file else None
        self.audit_file = Path(audit_file) if audit_file else None
        self.timeout = timeout
        self.bindings = {}
        self.pairings = {}
        self.polls = {}
        self.epoch = uuid.uuid4().hex + ".0"
        self.db_lock = asyncio.Lock()
        self.lock = asyncio.Lock()

    @property
    def enabled(self):
        return self.auth_file is not None

    async def authenticate(self, authorization=None, *, expected=None):
        require(self.enabled, "service_disabled")

        def read():
            try:
                require(not self.auth_file.is_symlink()
                        and not self.auth_file.stat().st_mode & 0o077
                        and self.auth_file.stat().st_size <= 16384,
                        "unsafe_device_auth_permissions")
                value = strict_json(self.auth_file.read_text())
                require(isinstance(value, dict) and value.get("version") == 1
                        and isinstance(value.get("devices"), list)
                        and 1 <= len(value["devices"]) <= 16, "invalid_device_auth_file")
                seen = set()
                for device in value["devices"]:
                    require(isinstance(device, dict)
                            and set(device) == {"device_id", "token_sha256", "scope"}
                            and valid_id(device["device_id"])
                            and device["device_id"] not in seen
                            and isinstance(device["token_sha256"], str)
                            and len(device["token_sha256"]) == 64
                            and all(c in "0123456789abcdef" for c in device["token_sha256"])
                            and device["scope"] == ["demo_echo"], "invalid_device_auth_file")
                    seen.add(device["device_id"])
                if expected is None:
                    require(isinstance(authorization, str) and authorization.startswith("Bearer "),
                            "device_auth_rejected")
                    token = authorization[7:]
                    require(token.isascii() and 32 <= len(token) <= 256, "device_auth_rejected")
                    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
                else:
                    digest = expected[1]
                for device in value["devices"]:
                    if (hmac.compare_digest(device["token_sha256"], digest)
                            and (expected is None or device["device_id"] == expected[0])):
                        return device["device_id"], digest
                raise MacToolError("device_auth_rejected")
            except (OSError, KeyError, TypeError, AttributeError):
                raise MacToolError("device_auth_unavailable") from None

        return await asyncio.to_thread(read)

    async def persist(self, request, result=None):
        # Serial worker-thread transactions avoid blocking media reception.
        async with self.db_lock:
            def write():
                self.audit_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                require(not self.audit_file.is_symlink(), "unsafe_audit_path")
                if self.audit_file.exists():
                    require(not self.audit_file.stat().st_mode & 0o077, "unsafe_audit_permissions")
                else:
                    self.audit_file.touch(mode=0o600, exist_ok=False)
                with sqlite3.connect(self.audit_file) as db:
                    db.execute("PRAGMA synchronous=FULL")
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS mac_echo_calls "
                        "(invocation_id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT)")
                    if result is None:
                        db.execute("INSERT INTO mac_echo_calls VALUES (?, ?, NULL)",
                                   (request["invocation_id"], encoded(request)))
                    else:
                        db.execute("UPDATE mac_echo_calls SET result=? WHERE invocation_id=?",
                                   (encoded(result), request["invocation_id"]))
            await asyncio.to_thread(write)

    def open_session(self, session_id, send):
        binding = Binding(session_id, send)
        self.bindings[session_id] = binding
        return binding

    def ready(self, binding):
        return bool(self.enabled and not binding.closed and binding.device_id
                    and binding.peer is not None and not binding.peer.closed)

    async def notify(self, binding):
        if not binding.closed:
            try:
                await binding.send({
                    "type": "agent.mac.status", "enabled": self.enabled,
                    "device_id": binding.device_id, "connected": self.ready(binding),
                    "session_id": binding.session_id,
                    "available_tools": ["demo_echo"] if self.ready(binding) else [],
                })
            except (OSError, RuntimeError):
                pass

    async def bind(self, binding, code, confirmed):
        require(self.enabled and confirmed is True, "mac_explicit_consent_required")
        require(isinstance(code, str) and 20 <= len(code) <= 128, "pairing_rejected")
        async with self.lock:
            require(not binding.closed, "voice_session_closed")
            pairing = self.pairings.get(hashlib.sha256(code.encode()).hexdigest())
            require(pairing and pairing["expires"] > time.monotonic(), "pairing_rejected")
            device, digest = await self.authenticate(
                expected=(pairing["device"], pairing["digest"]))
            require(binding.device_id is None and not any(
                b.device_id == device and not b.closed for b in self.bindings.values()),
                "binding_conflict")
            binding.device_id, binding.digest = device, digest
            self.pairings.pop(hashlib.sha256(code.encode()).hexdigest())
        await self.notify(binding)

    async def revoke(self, binding):
        await self.advance(binding)
        peer = binding.peer
        binding.peer = None
        binding.device_id = binding.digest = None
        binding.revision = uuid.uuid4().hex + ".0"
        if peer is not None:
            await peer.close(
                code=1000 if binding.closed else 4411,
                message=b"voice_session_closed" if binding.closed else b"binding_authorization_revoked")
        await self.notify(binding)

    async def close_session(self, binding):
        binding.closed = True
        await self.revoke(binding)
        self.bindings.pop(binding.session_id, None)

    async def advance(self, binding):
        binding.generation += 1
        for record in binding.calls.values():
            future = record.get("future")
            if future is not None and not future.done():
                future.cancel()
                await self.send_cancel(binding, record["request"])
        if self.ready(binding):
            await self.send_peer(binding, {
                "protocol": PROTOCOL, "type": "session.update",
                "device_id": binding.device_id, "session_id": binding.session_id,
                "generation_id": binding.generation,
            })

    async def send_cancel(self, binding, request):
        await self.send_peer(binding, {
            "protocol": PROTOCOL, "type": "tool.cancel",
            **{k: request[k] for k in CORRELATION},
        })

    async def send_peer(self, binding, message):
        if binding.peer is not None and not binding.peer.closed:
            try:
                await asyncio.wait_for(binding.peer.send_json(message), timeout=2)
            except (OSError, RuntimeError, asyncio.TimeoutError):
                pass

    async def invoke(self, binding, call_id, arguments):
        require(valid_id(call_id) and call_id not in binding.executing
                and call_id not in binding.outputs and call_id not in binding.calls,
                "mac_call_id_conflict")
        require(len(binding.outputs) + len(binding.executing) < 128, "mac_session_call_budget")
        generation = binding.generation
        binding.executing.add(call_id)
        try:
            try:
                value = await self._invoke(binding, call_id, arguments, generation)
            except MacToolError as error:
                value = outcome("failed", str(error))
            except (OSError, sqlite3.Error, RuntimeError, asyncio.TimeoutError):
                value = outcome("unknown", "mac_bridge_unavailable")
            require(not binding.closed and binding.generation == generation, "mac_old_generation")
            output = encoded(value)
            binding.outputs[call_id] = (generation, output)
            return output
        finally:
            binding.executing.discard(call_id)

    async def _invoke(self, binding, call_id, arguments, generation):
        require(self.ready(binding), "mac_device_not_ready")
        require(isinstance(arguments, dict) and set(arguments) == {"text"}
                and isinstance(arguments["text"], str) and len(arguments["text"]) <= 200,
                "invalid_echo_arguments")
        require(valid_id(call_id) and call_id not in binding.calls, "mac_call_id_conflict")
        require(len(binding.calls) < 128, "mac_session_call_budget")
        device, digest = await self.authenticate(
            expected=(binding.device_id, binding.digest))
        require((device, digest) == (binding.device_id, binding.digest), "device_revoked")
        peer = binding.peer
        request = {
            "protocol": PROTOCOL, "type": "tool.call", "device_id": device,
            "session_id": binding.session_id, "generation_id": generation,
            "call_id": call_id, "invocation_id": uuid.uuid4().hex,
            "tool_name": "demo_echo", "arguments": arguments, "timeout_ms": 5000,
        }
        await self.persist(request)
        require(self.ready(binding) and binding.generation == generation
                and binding.peer is peer, "mac_old_generation")
        future = asyncio.get_running_loop().create_future()
        record = {"request": request, "future": future, "receipt": None, "output": None}
        binding.calls[call_id] = record
        try:
            await asyncio.wait_for(peer.send_json(request), timeout=2)
            value = await asyncio.wait_for(asyncio.shield(future), self.timeout)
        except asyncio.TimeoutError:
            await self.send_cancel(binding, request)
            value = outcome("timed_out", "mac_timeout_unknown")
            record["expired"] = True
            await self.persist(request, value)
        except asyncio.CancelledError:
            await self.send_cancel(binding, request)
            raise
        finally:
            if not future.done():
                future.cancel()
        return value

    def verified_output(self, binding, call_id, output):
        return (not binding.closed
                and binding.outputs.get(call_id) == (binding.generation, output))

    async def receive_result(self, binding, result):
        require(isinstance(result, dict) and set(result) == {
            "protocol", "type", *CORRELATION, "status", "summary", "data", "error", "stale",
        }, "invalid_result_shape")
        require(valid_id(result.get("call_id")), "invalid_result_shape")
        record = binding.calls.get(result["call_id"])
        require(record is not None, "result_binding_mismatch")
        request = record["request"]
        require(result["protocol"] == PROTOCOL and result["type"] == "tool.result"
                and all(result[k] == request[k] and type(result[k]) is type(request[k])
                        for k in CORRELATION), "result_binding_mismatch")
        require(type(result["stale"]) is bool and isinstance(result["summary"], str)
                and len(result["summary"]) <= 2048, "invalid_result_shape")
        require(isinstance(result["status"], str)
                and result["status"] in {"succeeded", "failed", "cancelled", "timed_out", "unknown"},
                "invalid_result_outcome")
        if result["status"] == "succeeded":
            require(result["data"] == request["arguments"] and result["error"] is None,
                    "invalid_echo_result")
        else:
            error = result["error"]
            require(result["data"] is None and isinstance(error, dict)
                    and set(error) == {"code", "message", "retryable"}
                    and isinstance(error["code"], str) and 1 <= len(error["code"]) <= 128
                    and isinstance(error["message"], str) and len(error["message"]) <= 2048
                    and type(error["retryable"]) is bool, "invalid_result_outcome")
        fingerprint = encoded(result)
        if record["receipt"] is not None:
            require(record["receipt"] == fingerprint, "result_replay_conflict")
            return "duplicate"
        await self.persist(request, result)
        record["receipt"] = fingerprint
        future = record["future"]
        if (result["stale"] or binding.closed or binding.generation != request["generation_id"]
                or future.done() or record.get("expired")):
            if not future.done():
                future.set_result(outcome("unknown", "mac_stale_result"))
            return "archived"
        future.set_result({k: result[k] for k in ("status", "summary", "data", "error")})
        return "accepted"

    async def native(self, request):
        require("Origin" not in request.headers, "native_client_required")
        return await self.authenticate(request.headers.get("Authorization"))

    async def capabilities(self, _request):
        return web.json_response({
            "protocol": PROTOCOL, "enabled": self.enabled, "scope": ["demo_echo"] if self.enabled else [],
            "mode": "h20", "profile": "demo_echo", "mcp_protocol": "2025-11-25",
            "pairing_required": True, "compatibility_api_function_calling": False,
            "browser_remember": {"enabled": self.enabled,
                                 "path": "/api/tools/browser", "ttl_seconds": 2592000},
            "device_binding": {"enabled": self.enabled, "version": 1,
                               "path": "/api/tools/device/binding", "transport": "poll",
                               "poll_after_ms": 2000, "client_opt_in_required": True,
                               "guarded_bridge_query": ["binding_session_id", "binding_revision"]},
        }, headers={"Cache-Control": "no-store"})

    async def pairing(self, request):
        device, digest = await self.native(request)
        require(not request.query and request.content_type == "application/json", "invalid_pairing_request")
        require(strict_json(await request.text()) == {}, "invalid_pairing_request")
        now = time.monotonic()
        self.pairings = {k: v for k, v in self.pairings.items() if v["expires"] > now}
        require(len(self.pairings) < 80 and sum(
            p["device"] == device for p in self.pairings.values()) < 5, "pairing_rate_limit")
        code = secrets.token_urlsafe(24)
        self.pairings[hashlib.sha256(code.encode()).hexdigest()] = {
            "device": device, "digest": digest, "expires": now + 300,
        }
        return web.json_response({
            "pairing_code": code, "expires_in_seconds": 300, "device_id": device,
            "scope": ["demo_echo"], "connect_bridge_after_voice_binding": True,
        }, headers={"Cache-Control": "no-store"})

    async def discovery(self, request):
        device, digest = await self.native(request)
        require(not request.query, "invalid_binding_query")
        now = time.monotonic()
        require(now - self.polls.get(device, -10) >= 1, "binding_poll_rate_limit")
        self.polls[device] = now
        binding = next((b for b in self.bindings.values()
                        if b.device_id == device and not b.closed), None)
        authorized = binding is not None and binding.digest == digest
        return web.json_response({
            "binding_version": 1, "device_id": device,
            "state": "authorized" if authorized else "waiting_authorization",
            "binding_revision": binding.revision if authorized else self.epoch,
            "session_id": binding.session_id if authorized else None,
            "generation_id": binding.generation if authorized else None,
            "scope": ["demo_echo"] if authorized else [],
            "connected": self.ready(binding) if authorized else False, "poll_after_ms": 2000,
        }, headers={"Cache-Control": "no-store", "Vary": "Authorization"})

    async def websocket(self, request):
        device, digest = await self.native(request)
        query = list(request.query.items())
        require(not query or len(query) == 2 and {k for k, _ in query} == {
            "binding_session_id", "binding_revision"}, "invalid_binding_query")
        ws = web.WebSocketResponse(max_msg_size=32768, heartbeat=20)
        await ws.prepare(request)
        binding = None
        try:
            message = await ws.receive(timeout=10)
            require(message.type == WSMsgType.TEXT, "manifest_required")
            manifest = strict_json(message.data)
            require(isinstance(manifest, dict) and set(manifest) == {
                    "protocol", "type", "device_id", "mode", "mcp_protocol", "tools",
                } and manifest["protocol"] == PROTOCOL and manifest["type"] == "tools.manifest"
                        and manifest["device_id"] == device and manifest["mode"] == "h20"
                        and manifest["mcp_protocol"] == "2025-11-25", "invalid_manifest")
            tools = manifest["tools"]
            require(isinstance(tools, list) and len(tools) == 1
                        and isinstance(tools[0], dict) and tools[0].get("name") == "demo_echo"
                        and tools[0].get("inputSchema") == PARAMETERS
                        and isinstance(tools[0].get("outputSchema"), dict), "echo_schema_mismatch")
            async with self.lock:
                await self.authenticate(expected=(device, digest))
                binding = next((b for b in self.bindings.values()
                                if b.device_id == device and not b.closed), None)
                require(binding and binding.digest == digest, "voice_session_not_paired")
                require(not self.ready(binding), "device_already_connected")
                require(not query or request.query["binding_session_id"] == binding.session_id
                        and request.query["binding_revision"] == binding.revision, "binding_changed")
                binding.peer = ws
                await ws.send_json({
                    "protocol": PROTOCOL, "type": "tools.manifest_ack", "device_id": device,
                    "session_id": binding.session_id, "generation_id": binding.generation,
                })
            await self.notify(binding)
            async for message in ws:
                require(message.type == WSMsgType.TEXT, "text_frame_required")
                current = await self.authenticate(expected=(device, digest))
                require(current == (device, digest) and binding.digest == digest
                        and binding.peer is ws, "device_revoked")
                disposition = await self.receive_result(binding, strict_json(message.data))
                # v1 has no result ACK; duplicate/late receipts remain durable.
                if disposition == "accepted":
                    continue
        except (MacToolError, asyncio.TimeoutError, OSError, RuntimeError, sqlite3.Error):
            await ws.close(code=4400, message=b"mac_bridge_rejected")
        finally:
            if binding and binding.peer is ws:
                binding.peer = None
                for record in binding.calls.values():
                    future = record.get("future")
                    if future is not None and not future.done():
                        future.set_result(outcome("unknown", "mac_disconnected"))
                await self.notify(binding)
        return ws

    def routes(self, app):
        async def guarded(handler, request):
            try:
                return await handler(request)
            except MacToolError as error:
                code = str(error)
                status = 401 if code.startswith("device_auth") else (
                    503 if code == "service_disabled" else 429 if "rate_limit" in code else 403)
                return web.json_response({"error": code}, status=status,
                                         headers={"Cache-Control": "no-store"})
        for method, path, handler in [
            ("GET", "/api/tools/capabilities", self.capabilities),
            ("POST", "/api/tools/pairing", self.pairing),
            ("GET", "/api/tools/device/binding", self.discovery),
            ("GET", "/api/tools/bridge", self.websocket),
        ]:
            async def route(request, handler=handler):
                return await guarded(handler, request)
            app.router.add_route(method, path, route)
