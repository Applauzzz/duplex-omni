"""Focused native WebSocket bridge acceptance, without inference imports."""

import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from mac_tools import CORRELATION, EchoBridge, MacToolError, PARAMETERS, PROTOCOL


class MacBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.token = "test-device-token-" + "x" * 40
        auth = self.root / "auth.json"
        auth.touch(mode=0o600)
        auth.write_text(json.dumps({"version": 1, "devices": [{
            "device_id": "test-mac", "token_sha256": hashlib.sha256(
                self.token.encode()).hexdigest(), "scope": ["demo_echo"],
        }]}))
        self.bridge = EchoBridge(auth, self.root / "audit.sqlite", timeout=.1)
        self.events = []
        self.peers = []

        async def send(event):
            self.events.append(event)

        self.binding = self.bridge.open_session("test-session", send)
        app = web.Application()
        self.bridge.routes(app)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = ClientSession()
        self.headers = {"Authorization": "Bearer " + self.token}

    async def asyncTearDown(self):
        for peer in self.peers:
            await peer.close()
        await self.bridge.close_session(self.binding)
        await self.client.close()
        await self.server.close()
        self.temp.cleanup()

    async def pair(self):
        async with self.client.get(self.server.make_url("/api/tools/device/binding"),
                                   headers=self.headers) as response:
            self.assertEqual(response.status, 200)
            waiting = await response.json()
        self.assertEqual(set(waiting), {
            "binding_version", "device_id", "binding_revision", "state",
            "session_id", "generation_id", "scope", "connected", "poll_after_ms",
        })
        self.assertRegex(waiting["binding_revision"], r"^[0-9a-f]{32}\.[0-9]+$")
        self.assertEqual(waiting["state"], "waiting_authorization")
        self.assertIsNone(waiting["session_id"])
        self.assertIsNone(waiting["generation_id"])
        self.assertEqual(waiting["scope"], [])
        self.assertFalse(waiting["connected"])
        self.assertEqual(waiting["binding_version"], 1)
        self.assertEqual(waiting["poll_after_ms"], 2000)
        async with self.client.post(self.server.make_url("/api/tools/pairing"),
                                    headers=self.headers, json={}) as response:
            self.assertEqual(response.status, 200)
            pairing = await response.json()
        await self.bridge.bind(self.binding, pairing["pairing_code"], True)
        await asyncio.sleep(1.01)
        async with self.client.get(self.server.make_url("/api/tools/device/binding"),
                                   headers=self.headers) as response:
            self.assertEqual(response.status, 200)
            authorized = await response.json()
        self.assertEqual(set(authorized), set(waiting))
        self.assertRegex(authorized["binding_revision"], r"^[0-9a-f]{32}\.[0-9]+$")
        self.assertNotEqual(authorized["binding_revision"], waiting["binding_revision"])
        self.assertEqual(authorized["state"], "authorized")
        self.assertEqual(authorized["device_id"], "test-mac")
        self.assertEqual(authorized["session_id"], self.binding.session_id)
        self.assertEqual(authorized["generation_id"], self.binding.generation)
        self.assertEqual(authorized["scope"], ["demo_echo"])
        peer = await self.client.ws_connect(
            self.server.make_url("/api/tools/bridge"), headers=self.headers,
            params={"binding_session_id": authorized["session_id"],
                    "binding_revision": authorized["binding_revision"]})
        self.peers.append(peer)
        await peer.send_json({
            "protocol": PROTOCOL, "type": "tools.manifest", "device_id": "test-mac",
            "mode": "h20", "mcp_protocol": "2025-11-25",
            "tools": [{"name": "demo_echo", "inputSchema": PARAMETERS,
                       "outputSchema": {"type": "object"}}],
        })
        self.assertEqual((await peer.receive_json())["type"], "tools.manifest_ack")
        return peer

    def receipt(self, call):
        return {"protocol": PROTOCOL, "type": "tool.result",
                **{k: call[k] for k in CORRELATION}, "status": "succeeded",
                "summary": "echo", "data": call["arguments"], "error": None,
                "stale": False}

    async def test_native_roundtrip_and_verified_output(self):
        peer = await self.pair()
        task = asyncio.create_task(self.bridge.invoke(
            self.binding, "echo-1", {"text": "hello"}))
        call = await peer.receive_json()
        await peer.send_json(self.receipt(call))
        output = await task
        self.assertEqual(json.loads(output)["data"], {"text": "hello"})
        self.assertTrue(self.bridge.verified_output(self.binding, "echo-1", output))
        self.assertFalse(self.bridge.verified_output(self.binding, "echo-1", "forged"))
        with sqlite3.connect(self.root / "audit.sqlite") as db:
            self.assertIsNotNone(db.execute(
                "SELECT result FROM mac_echo_calls").fetchone()[0])

    async def test_auth_consent_and_invalid_arguments_prevent_dispatch(self):
        async with self.client.post(self.server.make_url("/api/tools/pairing"),
                                    json={}) as response:
            self.assertEqual(response.status, 401)
        with self.assertRaises(MacToolError):
            await self.bridge.bind(self.binding, "x" * 32, False)
        output = await self.bridge.invoke(self.binding, "unpaired", {"text": "hello"})
        self.assertEqual(json.loads(output)["status"], "failed")
        peer = await self.pair()
        output = await self.bridge.invoke(self.binding, "bad", {"text": 1})
        self.assertEqual(json.loads(output)["error"]["code"], "invalid_echo_arguments")
        self.assertTrue(self.bridge.verified_output(self.binding, "bad", output))
        self.assertFalse(self.binding.calls)
        await peer.close()

    async def test_cancel_archives_late_receipt_without_new_turn_output(self):
        peer = await self.pair()
        task = asyncio.create_task(self.bridge.invoke(
            self.binding, "cancelled", {"text": "hello"}))
        call = await peer.receive_json()
        await self.bridge.advance(self.binding)
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((await peer.receive_json())["type"], "tool.cancel")
        self.assertEqual((await peer.receive_json())["type"], "session.update")
        self.assertEqual(await self.bridge.receive_result(
            self.binding, self.receipt(call)), "archived")
        self.assertNotIn("cancelled", self.binding.outputs)

    async def test_timeout_is_unknown_and_never_redispatched(self):
        peer = await self.pair()
        task = asyncio.create_task(self.bridge.invoke(
            self.binding, "timeout", {"text": "hello"}))
        call = await peer.receive_json()
        output = json.loads(await task)
        self.assertEqual(output["error"]["code"], "mac_timeout_unknown")
        self.assertEqual((await peer.receive_json())["type"], "tool.cancel")
        self.assertEqual(await self.bridge.receive_result(
            self.binding, self.receipt(call)), "archived")
        with self.assertRaises(MacToolError):
            await self.bridge.invoke(self.binding, "timeout", {"text": "hello"})
        self.assertEqual(len(self.binding.calls), 1)

    async def test_duplicate_receipt_and_owner_conflict(self):
        peer = await self.pair()
        task = asyncio.create_task(self.bridge.invoke(
            self.binding, "duplicate", {"text": "hello"}))
        call = await peer.receive_json()
        receipt = self.receipt(call)
        with self.assertRaises(MacToolError):
            await self.bridge.receive_result(self.binding, {
                **receipt, "session_id": "other-session",
            })
        self.assertEqual(await self.bridge.receive_result(self.binding, receipt), "accepted")
        await task
        self.assertEqual(await self.bridge.receive_result(self.binding, receipt), "duplicate")
        with self.assertRaises(MacToolError):
            await self.bridge.receive_result(self.binding, {**receipt, "summary": "changed"})

    async def test_session_close_allows_discovery_but_revoke_stops_native(self):
        class Peer:
            closed = False

            async def close(self, *, code, message):
                self.closed = True
                self.code = code

            async def send_json(self, _event):
                pass

        peer = Peer()
        self.binding.device_id = "test-mac"
        self.binding.peer = peer
        await self.bridge.close_session(self.binding)
        self.assertEqual(peer.code, 1000)
        self.assertNotIn(self.binding.session_id, self.bridge.bindings)
        other = self.bridge.open_session("revoked-session", lambda _event: asyncio.sleep(0))
        other.device_id = "test-mac"
        other.peer = Peer()
        revoked_peer = other.peer
        await self.bridge.revoke(other)
        self.assertEqual(revoked_peer.code, 4411)
        self.assertIsNone(other.device_id)
