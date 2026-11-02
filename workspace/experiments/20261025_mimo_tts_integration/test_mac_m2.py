"""Five focused native v2 acceptance scenarios; no Apple system writes."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from mac_tools import EchoBridge, MacToolError
from mac_m2 import M2Bridge, CATALOG, CORRELATION, EVENT_SCOPE, PROFILE, PROTOCOL, SCHEMAS


class M2Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.token = "m2-test-" + "x" * 48
        auth, policy = root / "auth.json", root / "policy.json"
        for path in (auth, policy):
            path.touch(mode=0o600)
        auth.write_text(json.dumps({"version": 1, "devices": [{
            "device_id": "mac-test", "token_sha256": hashlib.sha256(self.token.encode()).hexdigest(),
            "scope": ["demo_echo"],
        }]}))
        self.scope = ["timer_start", "timer_list", "timer_cancel", "contacts_search",
                      "facetime_call_contact", "apple_reminder_list", "weather_get", EVENT_SCOPE]
        policy.write_text(json.dumps({"version": 1, "devices": [{
            "device_id": "mac-test", "workspace_id": "workspace-test",
            "context_id": "context-test", "scope": self.scope,
        }]}))
        self.echo = EchoBridge(auth, root / "audit.sqlite")
        self.bridge = M2Bridge(self.echo, policy, timeout=.1)
        self.events = []

        async def send(event):
            self.events.append(event)
        self.binding = self.bridge.open_session("session-test", send)
        self.echo_binding = self.echo.open_session("session-test", send)
        self.echo_binding.device_id = "mac-test"
        self.echo_binding.digest = hashlib.sha256(self.token.encode()).hexdigest()
        app = web.Application()
        self.bridge.routes(app)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = ClientSession()
        self.headers = {"Authorization": "Bearer " + self.token}
        self.peers = []

    async def asyncTearDown(self):
        for peer in self.peers:
            await peer.close()
        await self.bridge.close_session(self.binding)
        await self.client.close()
        await self.server.close()
        self.temp.cleanup()

    async def pair(self):
        await self.bridge.authorize(self.binding, self.echo_binding, self.scope, True)
        async with self.client.get(self.server.make_url("/api/tools/m2/device/binding"),
                                   headers=self.headers) as response:
            discovery = await response.json()
            self.assertEqual(response.status, 200)
            SCHEMAS["discovery"].validate(discovery)
        peer = await self.client.ws_connect(
            self.server.make_url("/api/tools/m2/bridge"), headers=self.headers,
            params={"binding_session_id": discovery["session_id"],
                    "binding_revision": discovery["binding_revision"]})
        self.peers.append(peer)
        await peer.send_json(self.bridge.frame(self.binding, "tools.manifest", {
            "profile": PROFILE, "mode": "h20", "mcp_protocol": "2025-11-25",
            "scope": self.scope, "tools": [{
                "name": name, "description": CATALOG[name]["description"],
                "inputSchema": CATALOG[name]["inputSchema"],
                "outputSchema": CATALOG[name]["outputSchema"],
            } for name in self.scope if name in CATALOG], "event_types": ["timer.finished"],
        }))
        ack = await peer.receive_json()
        SCHEMAS["bridge"].validate(ack)
        self.assertEqual(ack["type"], "tools.manifest_ack")
        return peer

    def receipt(self, call, data):
        return {"protocol": PROTOCOL, "type": "tool.result",
                **{key: call[key] for key in CORRELATION},
                "status": "succeeded", "summary": "test", "data": data, "error": None,
                "stale": False}

    async def roundtrip(self, peer, name, arguments, data, confirmed=False):
        task = asyncio.create_task(self.bridge.invoke_tool(
            self.binding, "call-" + name, name, arguments, confirmed=confirmed))
        call = await peer.receive_json()
        self.assertEqual(call["type"], "tool.call")
        result = self.receipt(call, data)
        await peer.send_json(result)
        self.assertEqual((await peer.receive_json())["delivery"], "archived")
        output = await task
        self.assertTrue(self.bridge.verified_output(self.binding, call["call_id"], output))
        self.assertEqual(json.loads(output)["status"], "succeeded")
        return call, result

    async def test_roundtrip_discovery_schema_and_authoritative_output(self):
        peer = await self.pair()
        self.assertNotIn("facetime_call_contact", self.bridge.available(self.binding))
        await self.roundtrip(peer, "timer_list", {}, {"timers": []})
        self.assertFalse(self.bridge.verified_output(self.binding, "fake", "fake"))

    async def test_scope_write_confirmation_capture_and_argument_gates(self):
        with self.assertRaises(MacToolError):
            await self.bridge.authorize(self.binding, self.echo_binding, ["note_create"], True)
        peer = await self.pair()
        for call_id, name, args, confirmed in [
            ("write", "timer_start", {"label": "test", "duration_seconds": 10}, False),
            ("capture", "facetime_call_contact", {
                "contact_id": "c", "endpoint_id": "e", "expected_revision": "r"}, True),
            ("bad-args", "timer_list", {"limit": True}, False),
            ("unknown-id", "timer_cancel", {"timer_id": "not-observed"}, True),
        ]:
            output = json.loads(await self.bridge.invoke_tool(
                self.binding, call_id, name, args, confirmed=confirmed))
            self.assertEqual(output["status"], "failed")
        self.assertFalse(self.binding.calls)
        await peer.close()

    async def test_cancel_and_late_receipt_are_archived_without_output(self):
        peer = await self.pair()
        task = asyncio.create_task(self.bridge.invoke_tool(self.binding, "cancel", "timer_list", {}))
        call = await peer.receive_json()
        await self.bridge.advance(self.binding)
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((await peer.receive_json())["type"], "tool.cancel")
        self.assertEqual((await peer.receive_json())["type"], "session.update")
        await peer.send_json(self.receipt(call, {"timers": []}))
        self.assertEqual((await peer.receive_json())["delivery"], "archived")
        self.assertNotIn("cancel", self.binding.outputs)

    async def test_timeout_duplicate_and_owner_conflict(self):
        peer = await self.pair()
        task = asyncio.create_task(self.bridge.invoke_tool(self.binding, "timeout", "timer_list", {}))
        call = await peer.receive_json()
        self.assertEqual(json.loads(await task)["status"], "unknown")
        self.assertEqual((await peer.receive_json())["type"], "tool.cancel")
        receipt = self.receipt(call, {"timers": []})
        digest = self.echo_binding.digest
        with self.assertRaises(MacToolError):
            await self.bridge.accept_receipt({**receipt, "context_id": "other"}, "mac-test", digest)
        self.assertEqual((await self.bridge.accept_receipt(receipt, "mac-test", digest))["status"], "persisted")
        self.assertEqual((await self.bridge.accept_receipt(receipt, "mac-test", digest))["status"], "duplicate")
        with self.assertRaises(MacToolError):
            await self.bridge.invoke_tool(self.binding, "timeout", "timer_list", {})

    async def test_orphan_binding_released_but_live_owner_not_taken_over(self):
        await self.bridge.authorize(self.binding, self.echo_binding, self.scope, True)
        async def send(_event):
            pass
        new = self.bridge.open_session("new-session", send)
        echo_new = self.echo.open_session("new-session", send)
        echo_new.device_id = self.echo_binding.device_id
        echo_new.digest = self.echo_binding.digest
        try:
            with self.assertRaisesRegex(MacToolError, "m2_binding_conflict"):
                await self.bridge.authorize(new, echo_new, self.scope, True)
            await self.echo.close_session(self.echo_binding)
            await self.bridge.authorize(new, echo_new, self.scope, True)
            self.assertTrue(self.binding.closed)
            self.assertNotIn(self.binding.session_id, self.bridge.bindings)
            self.assertEqual(new.device_id, "mac-test")
        finally:
            await self.bridge.close_session(new)
            await self.echo.close_session(echo_new)

    async def test_closed_browser_notification_does_not_reject_native_manifest(self):
        async def disconnected(_event):
            raise ConnectionResetError("Cannot write to closing transport")

        self.binding.send = disconnected
        peer = await self.pair()
        self.assertFalse(peer.closed)
        self.assertTrue(self.bridge.ready(self.binding))
        await self.bridge.close_session(self.binding)
        self.assertNotIn(self.binding.session_id, self.bridge.bindings)

    async def test_timer_event_origin_dedup_and_no_spoken_claim(self):
        peer = await self.pair()
        now = datetime.now(timezone.utc)
        data = {
            "timer_id": "timer-test", "label": "test", "duration_seconds": 10,
            "created_at": now.isoformat(), "due_at": (now + timedelta(seconds=10)).isoformat(),
            "timezone": "UTC", "state": "running", "remaining_seconds": 10,
        }
        call, _ = await self.roundtrip(peer, "timer_start",
                                       {"label": "test", "duration_seconds": 10}, data, True)
        event = {
            "protocol": PROTOCOL, "type": "local.event", "device_id": "mac-test",
            "workspace_id": "workspace-test", "context_id": "context-test",
            "context_revision": 1, "event_id": "event-test", "event_type": "timer.finished",
            "occurred_at": now.isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "object_id": "timer-test", "origin_invocation_id": call["invocation_id"],
            "origin_session_id": self.binding.session_id,
            "data": {"timer_id": "timer-test", "label": "test", "due_at": data["due_at"]},
        }
        for expected in ("persisted", "duplicate"):
            async with self.client.post(self.server.make_url("/api/tools/m2/events"),
                                        headers=self.headers, json=event) as response:
                self.assertEqual(response.status, 200)
                ack = await response.json()
                SCHEMAS["event"].validate(ack)
                self.assertEqual(ack["status"], expected)
                self.assertEqual(ack["delivery_state"], "suppressed")
        self.assertEqual(sum(e["type"] == "agent.mac.timer.finished" for e in self.events), 1)
