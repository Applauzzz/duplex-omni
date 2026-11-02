"""Selected native Mac v2 tools; policy and grants never come from the model."""

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import uuid

from aiohttp import web, WSMsgType
from jsonschema import Draft202012Validator, FormatChecker

from mac_tools import EchoBridge, MacToolError, encoded, outcome, require, strict_json, valid_id


CONTRACT_ROOT = Path(__file__).resolve().parents[3] / (
    "third_party/openai-realtime-agents/src/app/agentConfigs/duplexMimo/macContracts")
CATALOG = {item["name"]: item for item in json.loads(
    (CONTRACT_ROOT / "catalog.json").read_text())["tools"]}
SCHEMAS = {name: Draft202012Validator(json.loads(
    (CONTRACT_ROOT / f"{name}.json").read_text()), format_checker=FormatChecker())
    for name in ("bridge", "discovery", "event")}
PROTOCOL = "duplex-mac-tools/v2"
PROFILE = "apple_contacts_facetime_demo_v1"
OWNER = ("device_id", "workspace_id", "context_id")
CORRELATION = (*OWNER, "session_id", "generation_id", "call_id", "invocation_id")
GROUPS = {
    "timers": ["timer_start", "timer_list", "timer_cancel"],
    "weather_travel": ["weather_get", "place_search", "route_plan"],
    "reminders": ["apple_reminder_create", "apple_reminder_list",
                  "apple_reminder_update", "apple_reminder_delete"],
    "contacts_facetime": ["contacts_search", "facetime_call", "facetime_call_contact"],
}
WRITES = {"timer_start", "timer_cancel", "apple_reminder_create",
          "apple_reminder_update", "apple_reminder_delete", "facetime_call",
          "facetime_call_contact"}
CALLS = {"facetime_call", "facetime_call_contact"}
EVENT_SCOPE = "timer.events.receive"
FUNCTIONS = {name: {"type": "function", "function": {
    "name": name, "description": item["description"], "parameters": item["inputSchema"],
}} for name, item in CATALOG.items() if name != "demo_echo"}


def validate(value, schema):
    try:
        schema.validate(value)
    except Exception:
        # Do not include schema-validation messages containing private arguments.
        raise MacToolError("m2_schema_invalid") from None


class M2Bridge(EchoBridge):
    def __init__(self, echo, policy_file=None, *, timeout=5.0):
        super().__init__(echo.auth_file, echo.audit_file, timeout=timeout)
        self.echo = echo
        self.policy_file = Path(policy_file) if policy_file else None

    @property
    def enabled(self):
        return self.policy_file is not None and self.echo.enabled

    async def authenticate(self, authorization=None, *, expected=None):
        return await self.echo.authenticate(authorization, expected=expected)

    async def policy(self, device):
        require(self.enabled, "m2_disabled")

        def read():
            require(not self.policy_file.is_symlink()
                    and self.policy_file.stat().st_size <= 16384
                    and not self.policy_file.stat().st_mode & 0o077, "unsafe_m2_policy")
            value = strict_json(self.policy_file.read_text())
            require(isinstance(value, dict) and value.get("version") == 1
                    and isinstance(value.get("devices"), list), "invalid_m2_policy")
            entries = [entry for entry in value["devices"] if entry.get("device_id") == device]
            require(len(entries) == 1, "m2_device_not_allowed")
            entry = entries[0]
            require(set(entry) == {"device_id", "workspace_id", "context_id", "scope"}
                    and all(valid_id(entry[k]) for k in OWNER)
                    and isinstance(entry["scope"], list)
                    and len(set(entry["scope"])) == len(entry["scope"])
                    and set(entry["scope"]) <= set(FUNCTIONS) | {EVENT_SCOPE},
                    "invalid_m2_policy")
            return entry

        try:
            return await asyncio.to_thread(read)
        except (OSError, ValueError, TypeError, KeyError):
            raise MacToolError("m2_policy_unavailable") from None

    def open_session(self, session_id, send):
        binding = super().open_session(session_id, send)
        binding.scopes = set()
        binding.negotiated = set()
        binding.workspace_id = binding.context_id = None
        binding.authorization_revision = 0
        binding.capture_ready = False
        binding.capture_paused = False
        return binding

    def frame(self, binding, kind, fields=None):
        return {
            "protocol": PROTOCOL, "type": kind, "device_id": binding.device_id,
            "workspace_id": binding.workspace_id, "context_id": binding.context_id,
            **(fields or {}),
        }

    def available(self, binding):
        if not self.ready(binding) or binding.capture_paused:
            return []
        return sorted((binding.scopes & binding.negotiated & set(FUNCTIONS)) -
                      (set() if binding.capture_ready else CALLS))

    async def notify(self, binding):
        if not binding.closed:
            try:
                await binding.send({
                    "type": "agent.mac.m2.status", "enabled": self.enabled,
                    "connected": self.ready(binding), "device_id": binding.device_id,
                    "workspace_id": binding.workspace_id, "context_id": binding.context_id,
                    "scope": sorted(binding.scopes), "available_tools": self.available(binding),
                    "capture_paused": binding.capture_paused,
                })
            except (OSError, RuntimeError):
                pass

    async def authorize(self, binding, echo_binding, scopes, confirmed):
        require(confirmed is True and not binding.closed, "m2_explicit_consent_required")
        require(echo_binding.device_id and not echo_binding.closed, "m2_pair_device_first")
        device, digest = await self.authenticate(
            expected=(echo_binding.device_id, echo_binding.digest))
        policy = await self.policy(device)
        require(isinstance(scopes, list) and scopes and len(set(scopes)) == len(scopes)
                and set(scopes) <= set(policy["scope"]), "m2_scope_denied")
        require("facetime_call_contact" not in scopes or "contacts_search" in scopes,
                "m2_scope_dependency")
        async with self.lock:
            for old in list(self.bindings.values()):
                if old is binding or old.closed or old.device_id != device:
                    continue
                owner = self.echo.bindings.get(old.session_id)
                if (owner is None or owner.closed or owner.device_id != device
                        or owner.digest != old.digest):
                    await self.close_session(old)
            require(not any(b.device_id == device and not b.closed and b is not binding
                            for b in self.bindings.values()), "m2_binding_conflict")
            await self.revoke(binding)
            binding.device_id, binding.digest = device, digest
            binding.workspace_id, binding.context_id = policy["workspace_id"], policy["context_id"]
            binding.scopes = set(scopes)
            binding.authorization_revision += 1
            binding.revision = uuid.uuid4().hex + ".0"
        await self.notify(binding)

    async def revoke(self, binding):
        await super().revoke(binding)
        binding.scopes = set()
        binding.negotiated = set()
        binding.workspace_id = binding.context_id = None
        binding.authorization_revision += 1

    async def advance(self, binding):
        binding.generation += 1
        for record in binding.calls.values():
            future = record.get("future")
            if future is not None and not future.done():
                future.cancel()
                await self.send_cancel(binding, record["request"])
        if self.ready(binding):
            await self.send_peer(binding, self.frame(binding, "session.update", {
                "session_id": binding.session_id, "generation_id": binding.generation,
                "authorization_revision": binding.authorization_revision,
            }))

    async def send_cancel(self, binding, request):
        await self.send_peer(binding, {
            "protocol": PROTOCOL, "type": "tool.cancel",
            **{key: request[key] for key in CORRELATION},
        })

    async def transaction(self, operation):
        async with self.db_lock:
            def run():
                require(self.audit_file is not None and not self.audit_file.is_symlink(),
                        "unsafe_m2_audit")
                if not self.audit_file.exists():
                    self.audit_file.touch(mode=0o600, exist_ok=False)
                require(not self.audit_file.stat().st_mode & 0o077, "unsafe_m2_audit")
                with sqlite3.connect(self.audit_file) as db:
                    db.execute("PRAGMA synchronous=FULL")
                    db.execute("CREATE TABLE IF NOT EXISTS mac_m2_calls "
                               "(invocation_id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT)")
                    db.execute("CREATE TABLE IF NOT EXISTS mac_m2_events "
                               "(device_id TEXT, event_id TEXT, event TEXT NOT NULL, ack TEXT NOT NULL,"
                               " PRIMARY KEY(device_id,event_id))")
                    return operation(db)
            return await asyncio.to_thread(run)

    async def persist(self, request, result=None):
        def write(db):
            if result is None:
                db.execute("INSERT INTO mac_m2_calls VALUES (?,?,NULL)",
                           (request["invocation_id"], encoded(request)))
            else:
                db.execute("UPDATE mac_m2_calls SET result=? WHERE invocation_id=?",
                           (encoded(result), request["invocation_id"]))
        await self.transaction(write)

    async def owner_records(self, binding):
        rows = await self.transaction(lambda db: db.execute(
            "SELECT request,result FROM mac_m2_calls WHERE result IS NOT NULL").fetchall())
        records = []
        for request, result in rows:
            request, result = strict_json(request), strict_json(result)
            if (all(request[key] == getattr(binding, key) for key in OWNER)
                    and result.get("status") == "succeeded" and not result.get("stale")):
                records.append((request, result["data"]))
        return records

    async def check_references(self, binding, name, args):
        needed = {
            "timer_cancel": ("timer_id",),
            "route_plan": ("origin_place_id", "destination_place_id"),
            "apple_reminder_update": ("reminder_id", "expected_revision"),
            "apple_reminder_delete": ("reminder_id", "expected_revision"),
            "facetime_call_contact": ("contact_id", "endpoint_id", "expected_revision"),
        }.get(name)
        if not needed:
            return
        records = await self.owner_records(binding)
        if name == "route_plan":
            ids = {place["place_id"] for request, data in records
                   if request["tool_name"] == "place_search" for place in data.get("places", [])}
            require(all(args[key] in ids for key in needed), "m2_unobserved_place")
            return
        # Keep ID and revision on the same object; never combine unrelated receipts.
        objects = []
        allowed = ({"timer_start", "timer_list"} if name == "timer_cancel" else
                   {"contacts_search"} if name == "facetime_call_contact" else
                   {"apple_reminder_create", "apple_reminder_list", "apple_reminder_update"})
        for request, data in records:
            if request["tool_name"] not in allowed:
                continue
            objects.append(data)
            for key in ("timers", "items"):
                objects.extend(data.get(key, []))
        def matches(item):
            if item.get(needed[0]) != args[needed[0]]:
                return False
            if "expected_revision" in needed and item.get("revision") != args["expected_revision"]:
                return False
            if "endpoint_id" in needed:
                return any(endpoint.get("endpoint_id") == args["endpoint_id"]
                           for endpoint in item.get("endpoints", []))
            return True
        require(any(matches(item) for item in objects), "m2_unobserved_object_or_revision")

    async def invoke_tool(self, binding, call_id, name, arguments, *, confirmed=False):
        require(valid_id(call_id) and call_id not in binding.calls
                and call_id not in binding.outputs and call_id not in binding.executing,
                "mac_call_id_conflict")
        generation = binding.generation
        binding.executing.add(call_id)
        try:
            try:
                require(name in self.available(binding)
                        or name in CALLS and binding.capture_paused
                        and name in binding.negotiated & binding.scopes, "m2_tool_unavailable")
                require(name not in WRITES or confirmed is True, "m2_confirmation_required")
                require(name not in CALLS or binding.capture_paused, "m2_capture_pause_required")
                validate(arguments, Draft202012Validator(CATALOG[name]["inputSchema"]))
                require(len(encoded(arguments).encode()) <= 8192, "m2_arguments_too_large")
                await self.check_references(binding, name, arguments)
                await self.authenticate(expected=(binding.device_id, binding.digest))
                policy = await self.policy(binding.device_id)
                require(name in policy["scope"] and all(
                    policy[key] == getattr(binding, key) for key in OWNER), "m2_scope_revoked")
                require(len(binding.calls) < 128 and sum(
                    r["request"]["generation_id"] == generation for r in binding.calls.values()) < 4,
                    "m2_call_budget")
                request = self.frame(binding, "tool.call", {
                    "session_id": binding.session_id, "generation_id": generation,
                    "call_id": call_id, "invocation_id": uuid.uuid4().hex,
                    "tool_name": name, "arguments": arguments, "timeout_ms": 5000,
                    "authorization_revision": binding.authorization_revision,
                })
                validate(request, SCHEMAS["bridge"])
                await self.persist(request)
                future = asyncio.get_running_loop().create_future()
                binding.calls[call_id] = {"request": request, "future": future}
                require(self.ready(binding) and binding.generation == generation, "m2_old_generation")
                await binding.peer.send_json(request)
                try:
                    value = await asyncio.wait_for(asyncio.shield(future), self.timeout)
                except asyncio.TimeoutError:
                    binding.calls[call_id]["expired"] = True
                    await self.send_cancel(binding, request)
                    value = outcome("unknown", "m2_timeout_unknown")
                finally:
                    if not future.done():
                        future.cancel()
            except MacToolError as error:
                value = outcome("failed", str(error))
            except (OSError, sqlite3.Error):
                value = outcome("unknown", "m2_audit_or_transport_unavailable")
            require(not binding.closed and binding.generation == generation, "m2_old_generation")
            output = encoded(value)
            binding.outputs[call_id] = (generation, output)
            return output
        finally:
            binding.executing.discard(call_id)

    async def accept_receipt(self, result, device, digest, binding=None):
        require(len(encoded(result).encode()) <= 32768, "m2_frame_too_large")
        validate(result, SCHEMAS["bridge"])
        require(result["type"] == "tool.result" and result["device_id"] == device,
                "m2_invalid_receipt")
        await self.authenticate(expected=(device, digest))
        def archive(db):
            row = db.execute("SELECT request,result FROM mac_m2_calls WHERE invocation_id=?",
                             (result["invocation_id"],)).fetchone()
            require(row is not None, "m2_unknown_invocation")
            request = strict_json(row[0])
            require(all(request[key] == result[key] for key in CORRELATION), "m2_owner_mismatch")
            require(request["tool_name"] in CATALOG, "m2_unknown_tool")
            validate({k: result[k] for k in ("status", "summary", "data", "error")},
                     Draft202012Validator(CATALOG[request["tool_name"]]["outputSchema"]))
            if result["status"] == "succeeded":
                require(result["error"] is None, "m2_invalid_outcome")
                validate(result["data"], Draft202012Validator(
                    CATALOG[request["tool_name"]]["dataSchema"], format_checker=FormatChecker()))
                if request["tool_name"] in CALLS and not result["data"].get("is_mock"):
                    require(result["data"].get("assistant_should_pause_capture") is True
                            and result["data"].get("call_connection_observed") is False,
                            "m2_invalid_facetime_receipt")
            else:
                require(result["data"] is None and isinstance(result["error"], dict),
                        "m2_invalid_outcome")
            if row[1] is not None:
                require(strict_json(row[1]) == result, "m2_receipt_conflict")
                return "duplicate"
            db.execute("UPDATE mac_m2_calls SET result=? WHERE invocation_id=?",
                       (encoded(result), result["invocation_id"]))
            return "persisted"
        status = await self.transaction(archive)
        if binding and not binding.closed:
            record = binding.calls.get(result["call_id"])
            if (record and not record["future"].done() and not record.get("expired")
                    and result["generation_id"] == binding.generation and not result["stale"]):
                record["future"].set_result({k: result[k] for k in ("status", "summary", "data", "error")})
        return {
            "protocol": PROTOCOL, "type": "tool.result_ack",
            **{key: result[key] for key in OWNER},
            "invocation_id": result["invocation_id"], "status": status, "delivery": "archived",
        }

    async def discovery(self, request):
        device, digest = await self.native(request)
        require(not request.query, "invalid_binding_query")
        policy = await self.policy(device)
        binding = next((b for b in self.bindings.values()
                        if b.device_id == device and not b.closed and b.digest == digest), None)
        authorized = binding is not None
        scope = sorted(binding.scopes) if authorized else []
        value = {
            "binding_version": 2, "protocol": PROTOCOL, "profile": PROFILE,
            "device_id": device, "state": "authorized" if authorized else "waiting_scope_authorization",
            "binding_revision": binding.revision if authorized else self.epoch,
            "session_id": binding.session_id if authorized else None,
            "generation_id": binding.generation if authorized else None,
            "authorization_revision": binding.authorization_revision if authorized else None,
            "workspace_id": policy["workspace_id"], "context_id": policy["context_id"],
            "scope": scope, "granted_scope": scope,
            "connected": self.ready(binding) if authorized else False,
            "available_tools": self.available(binding) if authorized else [],
            "model_tools_available": bool(self.available(binding)) if authorized else False,
            "event_types": ["timer.finished"] if EVENT_SCOPE in scope else [], "poll_after_ms": 2000,
        }
        validate(value, SCHEMAS["discovery"])
        return web.json_response(value, headers={"Cache-Control": "no-store"})

    async def websocket(self, request):
        device, digest = await self.native(request)
        require(set(request.query) == {"binding_session_id", "binding_revision"},
                "invalid_binding_query")
        binding = self.bindings.get(request.query["binding_session_id"])
        policy = await self.policy(device)
        require(binding and not binding.closed and binding.device_id == device
                and binding.digest == digest and binding.revision == request.query["binding_revision"]
                and not self.ready(binding)
                and binding.scopes <= set(policy["scope"])
                and all(getattr(binding, k) == policy[k] for k in OWNER), "m2_binding_changed")
        ws = web.WebSocketResponse(max_msg_size=32768, heartbeat=20)
        await ws.prepare(request)
        try:
            message = await ws.receive(timeout=10)
            require(message.type == WSMsgType.TEXT, "manifest_required")
            manifest = strict_json(message.data)
            validate(manifest, SCHEMAS["bridge"])
            require(manifest["type"] == "tools.manifest" and manifest["profile"] == PROFILE
                    and all(manifest[k] == getattr(binding, k) for k in OWNER),
                    "m2_manifest_owner_mismatch")
            scope = set(manifest["scope"])
            require(scope <= binding.scopes, "m2_manifest_scope_denied")
            tools = manifest["tools"]
            names = {tool["name"] for tool in tools}
            require(len(names) == len(tools) and names == scope & set(FUNCTIONS) and names,
                    "m2_manifest_tools_mismatch")
            for tool in tools:
                require(tool["inputSchema"] == CATALOG[tool["name"]]["inputSchema"]
                        and tool["outputSchema"] == CATALOG[tool["name"]]["outputSchema"],
                        "m2_manifest_schema_mismatch")
            events = ["timer.finished"] if EVENT_SCOPE in scope else []
            require(manifest["event_types"] == events, "m2_manifest_event_mismatch")
            binding.peer, binding.negotiated = ws, names
            ack = self.frame(binding, "tools.manifest_ack", {
                "profile": PROFILE, "session_id": binding.session_id,
                "generation_id": binding.generation,
                "authorization_revision": binding.authorization_revision,
                "scope": sorted(scope), "available_tools": sorted(names), "event_types": events,
            })
            validate(ack, SCHEMAS["bridge"])
            await ws.send_json(ack)
            await self.notify(binding)
            async for message in ws:
                require(message.type == WSMsgType.TEXT, "m2_text_frame_required")
                await ws.send_json(await self.accept_receipt(
                    strict_json(message.data), device, digest, binding))
        except (MacToolError, asyncio.TimeoutError, OSError, sqlite3.Error) as error:
            logging.getLogger("mimo_tts.mac_m2").warning(
                "M2 bridge rejected session=%s code=%s", binding.session_id,
                str(error) if isinstance(error, MacToolError) else type(error).__name__,
            )
            await ws.close(code=4400, message=b"m2_bridge_rejected")
        finally:
            if binding.peer is ws:
                binding.peer = None
                for record in binding.calls.values():
                    if not record["future"].done():
                        record["future"].set_result(outcome("unknown", "m2_disconnected"))
                await self.notify(binding)
        return ws

    async def receipt_http(self, request):
        device, digest = await self.native(request)
        require(not request.query and request.content_type == "application/json",
                "m2_invalid_receipt_request")
        result = strict_json(await request.text())
        # Archival only; never resume a waiting model from the offline receipt endpoint.
        ack = await self.accept_receipt(result, device, digest)
        return web.json_response(ack)

    async def event_http(self, request):
        device, digest = await self.native(request)
        require(not request.query and request.content_type == "application/json", "m2_invalid_event")
        event = strict_json(await request.text())
        validate(event, SCHEMAS["event"])
        require(event["type"] == "local.event" and event["device_id"] == device, "m2_invalid_event")
        policy = await self.policy(device)
        require(EVENT_SCOPE in policy["scope"], "m2_event_scope_denied")
        binding = next((b for b in self.bindings.values() if b.device_id == device
                        and not b.closed and b.digest == digest), None)
        def store(db):
            original = db.execute("SELECT request,result FROM mac_m2_calls WHERE invocation_id=?",
                                  (event["origin_invocation_id"],)).fetchone()
            require(original and original[1], "m2_event_origin_unverified_retry")
            call, result = strict_json(original[0]), strict_json(original[1])
            require(all(call[k] == event[k] for k in OWNER)
                    and call["session_id"] == event["origin_session_id"]
                    and call["tool_name"] == "timer_start" and result["status"] == "succeeded"
                    and result["data"]["timer_id"] == event["object_id"] == event["data"]["timer_id"]
                    and result["data"]["label"] == event["data"]["label"]
                    and result["data"]["due_at"] == event["data"]["due_at"], "m2_event_origin_mismatch")
            old = db.execute("SELECT event,ack FROM mac_m2_events WHERE device_id=? AND event_id=?",
                             (device, event["event_id"])).fetchone()
            if old:
                require(strict_json(old[0]) == event, "m2_event_conflict")
                return {**strict_json(old[1]), "status": "duplicate"}
            expires = datetime.fromisoformat(event["expires_at"].replace("Z", "+00:00"))
            require(expires.tzinfo is not None, "m2_invalid_event_time")
            ack = {
                "protocol": PROTOCOL, "type": "local.event_ack",
                **{key: event[key] for key in OWNER}, "event_id": event["event_id"],
                "receipt_id": uuid.uuid4().hex, "status": "persisted",
                "delivery_state": "expired" if expires <= datetime.now(timezone.utc) else "suppressed",
            }
            db.execute("INSERT INTO mac_m2_events VALUES (?,?,?,?)",
                       (device, event["event_id"], encoded(event), encoded(ack)))
            return ack
        ack = await self.transaction(store)
        if (ack["status"] == "persisted" and ack["delivery_state"] != "expired"
                and binding and EVENT_SCOPE in binding.scopes
                and all(getattr(binding, k) == event[k] for k in OWNER)):
            await binding.send({"type": "agent.mac.timer.finished", "event_id": event["event_id"],
                                "data": event["data"], "spoken": False})
        return web.json_response(ack)

    async def options(self, binding, echo_binding):
        policy = await self.policy(echo_binding.device_id)
        await binding.send({
            "type": "agent.mac.m2.options", "workspace_id": policy["workspace_id"],
            "context_id": policy["context_id"], "allowed_scope": policy["scope"], "groups": GROUPS,
        })

    def routes(self, app):
        for method, path, handler in [
            ("GET", "/api/tools/m2/device/binding", self.discovery),
            ("GET", "/api/tools/m2/bridge", self.websocket),
            ("POST", "/api/tools/m2/results", self.receipt_http),
            ("POST", "/api/tools/m2/events", self.event_http),
        ]:
            async def route(request, handler=handler):
                try:
                    return await handler(request)
                except MacToolError as error:
                    code = str(error)
                    status = (401 if code.startswith("device_auth") else
                              503 if code == "m2_disabled" else
                              409 if "origin_unverified" in code or "conflict" in code else 403)
                    return web.json_response({"error": code}, status=status)
            app.router.add_route(method, path, route)
