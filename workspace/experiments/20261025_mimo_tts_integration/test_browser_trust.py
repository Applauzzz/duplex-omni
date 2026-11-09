"""Five focused browser-grant HTTP/WebSocket lifecycle cases."""

import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from aiohttp import ClientSession, CookieJar, web
from aiohttp.test_utils import TestServer

from browser_trust import BrowserTrust, COOKIE
from mac_tools import EchoBridge, MacToolError
from mac_m2 import M2Bridge


class BrowserTrustTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.auth = self.root / "auth.json"
        self.auth.touch(mode=0o600)
        self.auth.write_text(json.dumps({"version": 1, "devices": [{
            "device_id": "test-mac", "token_sha256": "a" * 64, "scope": ["demo_echo"],
        }]}))
        self.echo = EchoBridge(self.auth, self.root / "audit.sqlite")
        self.m2 = M2Bridge(self.echo)
        self.trust = BrowserTrust(self.echo, self.m2)
        app = web.Application()
        self.trust.routes(app)

        async def websocket(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            binding = self.echo.open_session("new-session", ws.send_json)
            m2 = self.m2.open_session("new-session", ws.send_json)
            try:
                await self.trust.restore(request, binding, m2)
                async for _ in ws:
                    pass
            finally:
                await self.echo.close_session(binding)
                await self.m2.close_session(m2)
            return ws
        app.router.add_get("/ws", websocket)
        self.server = TestServer(app)
        await self.server.start_server()
        self.origin = str(self.server.make_url("")).rstrip("/")
        self.client = ClientSession(cookie_jar=CookieJar(unsafe=True), trust_env=False,
                                    headers={"Origin": self.origin})
        self.binding = self.echo.open_session("paired-session", self.send)
        self.binding.device_id, self.binding.digest = "test-mac", "a" * 64
        self.binding.browser_origin = self.origin
        self.native = self.m2.open_session("paired-session", self.send)
        self.binding.forget_browser = self.forget

    async def send(self, _event):
        pass

    async def forget(self):
        await self.echo.revoke(self.binding)
        await self.m2.revoke(self.native)

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temp.cleanup()

    async def remember(self):
        async with self.client.post(self.server.make_url("/api/tools/browser/remember"),
                                    json={"session_id": "paired-session", "confirmed": True}) as response:
            self.assertEqual(response.status, 200, await response.text())
            cookie = response.cookies[COOKIE]
            self.assertTrue(cookie["httponly"])
            self.assertEqual(cookie["samesite"], "Strict")
            self.assertFalse(cookie["domain"])
            return cookie.value

    async def test_http_cookie_restore_new_websocket_and_persisted_restart(self):
        token = await self.remember()
        await self.echo.close_session(self.binding)
        async with self.client.ws_connect(self.server.make_url("/ws")) as ws:
            event = await asyncio.wait_for(ws.receive_json(), 3)
            self.assertEqual(event["device_id"], "test-mac")
            self.assertEqual(event["session_id"], "new-session")
            self.assertFalse(self.echo.bindings["new-session"].calls)
        other = BrowserTrust(EchoBridge(self.auth, self.root / "audit.sqlite"), self.m2)
        rows = await other.transaction(lambda db: db.execute(
            "SELECT hash FROM mac_browser_grants").fetchall())
        self.assertEqual(rows, [(hashlib.sha256(token.encode()).hexdigest(),)])
        self.assertNotIn(token, (self.root / "audit.sqlite").read_bytes().decode("latin1"))

    async def test_expiry_and_revocation_block_recovery(self):
        await self.remember()
        async with self.client.post(self.server.make_url("/api/tools/browser/forget"),
                                    json={}) as response:
            self.assertEqual(response.status, 200)
        self.assertIsNone(self.binding.device_id)
        self.binding.device_id, self.binding.digest = "test-mac", "a" * 64
        await self.remember()
        await self.trust.transaction(lambda db: db.execute(
            "UPDATE mac_browser_grants SET expires=0"))
        async with self.client.post(self.server.make_url("/api/tools/browser/status"),
                                    json={}) as response:
            self.assertFalse((await response.json())["trusted"])

    async def test_origin_consent_and_device_rotation_rejected(self):
        async with self.client.post(self.server.make_url("/api/tools/browser/remember"),
                                    headers={"Origin": "http://evil.invalid"},
                                    json={"session_id": "paired-session", "confirmed": True}) as response:
            self.assertEqual(response.status, 403)
        async with self.client.post(self.server.make_url("/api/tools/browser/remember"),
                                    json={"session_id": "paired-session", "confirmed": False}) as response:
            self.assertEqual(response.status, 403)
        await self.remember()
        value = json.loads(self.auth.read_text())
        value["devices"][0]["token_sha256"] = "b" * 64
        self.auth.write_text(json.dumps(value))
        async with self.client.post(self.server.make_url("/api/tools/browser/status"),
                                    json={}) as response:
            self.assertEqual(response.status, 403)

    async def test_concurrent_session_does_not_take_over_and_old_output_fenced(self):
        await self.remember()
        new = self.echo.open_session("other-session", self.send)
        m2 = self.m2.open_session("other-session", self.send)
        request = type("Request", (), {
            "headers": {"Origin": self.origin}, "host": self.server.make_url("").host
                + ":" + str(self.server.port),
            "cookies": {COOKIE: self.client.cookie_jar.filter_cookies(
                self.server.make_url(""))[COOKIE].value},
        })()
        self.binding.outputs["old"] = (0, "old-result")
        with self.assertRaisesRegex(MacToolError, "binding_conflict"):
            await self.trust.restore(request, new, m2)
        await self.echo.close_session(self.binding)
        await self.trust.restore(request, new, m2)
        self.assertFalse(self.echo.verified_output(self.binding, "old", "old-result"))
        self.assertFalse(self.echo.verified_output(new, "old", "old-result"))
        self.assertEqual(new.device_id, "test-mac")

    async def test_capture_hold_and_exact_m2_scope_survive_refresh(self):
        policy = self.root / "policy.json"
        policy.touch(mode=0o600)
        policy.write_text(json.dumps({"version": 1, "devices": [{
            "device_id": "test-mac", "workspace_id": "workspace",
            "context_id": "context", "scope": ["timer_list"],
        }]}))
        self.m2.policy_file = policy
        await self.m2.authorize(self.native, self.binding, ["timer_list"], True)
        self.native.capture_paused = True
        await self.remember()
        await self.echo.close_session(self.binding)
        await self.m2.close_session(self.native)
        async with self.client.ws_connect(self.server.make_url("/ws")) as ws:
            while True:
                event = await asyncio.wait_for(ws.receive_json(), 3)
                if event["type"] == "agent.mac.status":
                    break
            binding = self.m2.bindings["new-session"]
            self.assertTrue(binding.capture_paused)
            self.assertEqual(binding.scopes, {"timer_list"})
            self.assertEqual(binding.negotiated, set())
