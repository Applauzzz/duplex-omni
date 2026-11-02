"""Revocable browser-only grants; never expose the native device credential."""

import asyncio
import hashlib
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from aiohttp import web

from mac_tools import MacToolError, encoded, require, strict_json

COOKIE = "duplex_browser"
MAX_AGE = 30 * 24 * 60 * 60


def browser_origin(request):
    raw = request.headers.get("Origin", "")
    origin = urlsplit(raw)
    require(origin.scheme in {"http", "https"} and origin.netloc == request.host
            and not origin.username and not origin.password
            and not origin.path and not origin.query and not origin.fragment,
            "browser_origin_rejected")
    require(origin.scheme == "https" or origin.hostname in {"localhost", "127.0.0.1", "::1"},
            "browser_https_required")
    return raw


class BrowserTrust:
    def __init__(self, echo, m2):
        self.echo = echo
        self.m2 = m2

    async def transaction(self, operation):
        require(self.echo.enabled, "service_disabled")
        async with self.echo.db_lock:
            def run():
                path = self.echo.audit_file
                require(not path.is_symlink(), "unsafe_audit_path")
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if not path.exists():
                    path.touch(mode=0o600, exist_ok=False)
                require(not path.stat().st_mode & 0o077, "unsafe_audit_permissions")
                with sqlite3.connect(path) as db:
                    db.execute("PRAGMA synchronous=FULL")
                    db.execute("CREATE TABLE IF NOT EXISTS mac_browser_grants "
                               "(hash TEXT PRIMARY KEY, origin TEXT NOT NULL,"
                               "device TEXT NOT NULL, digest TEXT NOT NULL,"
                               "expires REAL NOT NULL, settings TEXT NOT NULL)")
                    db.execute("DELETE FROM mac_browser_grants WHERE expires <= ?", (time.time(),))
                    return operation(db)
            return await asyncio.to_thread(run)

    async def lookup(self, request):
        origin = browser_origin(request)
        token = request.cookies.get(COOKIE, "")
        if not token:
            return None
        require(len(token) == 64 and all(c in "0123456789abcdef" for c in token),
                "browser_grant_rejected")
        key = hashlib.sha256(token.encode()).hexdigest()
        row = await self.transaction(lambda db: db.execute(
            "SELECT origin,device,digest,settings FROM mac_browser_grants WHERE hash=?",
            (key,)).fetchone())
        if not row:
            return None
        require(row[0] == origin, "browser_grant_rejected")
        await self.echo.authenticate(expected=(row[1], row[2]))
        return key, row[1], row[2], strict_json(row[3])

    async def restore(self, request, binding, m2_binding):
        if binding.device_id or not self.echo.enabled:
            return
        grant = await self.lookup(request)
        if not grant:
            return
        key, device, digest, settings = grant
        async with self.echo.lock:
            require(not binding.closed and not any(
                b.device_id == device and not b.closed and b is not binding
                for b in self.echo.bindings.values()), "binding_conflict")
            await self.echo.authenticate(expected=(device, digest))
            binding.device_id, binding.digest = device, digest
            binding.browser_grant = key
        m2_binding.capture_paused = settings.get("capture_paused") is True
        saved = settings.get("m2")
        if saved and self.m2.enabled:
            try:
                policy = await self.m2.policy(device)
                require(all(saved[k] == policy[k] for k in ("workspace_id", "context_id")),
                        "m2_owner_changed")
                await self.m2.authorize(m2_binding, binding, saved["scope"], True)
            except MacToolError:
                # Changed policy never widens or silently substitutes remembered scopes.
                await self.m2.revoke(m2_binding)
        await self.echo.notify(binding)
        await self.m2.notify(m2_binding)

    def settings(self, binding):
        m2 = self.m2.bindings.get(binding.session_id)
        return {
            "capture_paused": bool(m2 and m2.capture_paused),
            "m2": {"workspace_id": m2.workspace_id, "context_id": m2.context_id,
                   "scope": sorted(m2.scopes)} if m2 and m2.device_id else None,
        }

    async def save(self, binding):
        key = getattr(binding, "browser_grant", None)
        if key:
            settings = encoded(self.settings(binding))
            await self.transaction(lambda db: db.execute(
                "UPDATE mac_browser_grants SET settings=? WHERE hash=?", (settings, key)))

    async def revoke(self, binding):
        key = getattr(binding, "browser_grant", None)
        if key:
            await self.transaction(lambda db: db.execute(
                "DELETE FROM mac_browser_grants WHERE hash=?", (key,)))
            binding.browser_grant = None

    async def status(self, request):
        grant = await self.lookup(request) if self.echo.enabled else None
        response = web.json_response({
            "trusted": bool(grant),
            "capture_paused": bool(grant and grant[3].get("capture_paused")),
        }, headers={"Cache-Control": "no-store"})
        if grant:
            await self.transaction(lambda db: db.execute(
                "UPDATE mac_browser_grants SET expires=? WHERE hash=?",
                (time.time() + MAX_AGE, grant[0])))
            self.cookie(response, request, request.cookies[COOKIE])
        return response

    def cookie(self, response, request, token):
        response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True,
                            secure=request.headers["Origin"].startswith("https:"),
                            samesite="Strict", path="/")

    async def remember(self, request):
        origin = browser_origin(request)
        require(request.content_type == "application/json", "browser_json_required")
        value = strict_json(await request.text())
        require(isinstance(value, dict) and set(value) == {"session_id", "confirmed"}
                and value["confirmed"] is True and isinstance(value["session_id"], str),
                "browser_consent_required")
        async with self.echo.lock:
            binding = self.echo.bindings.get(value["session_id"])
            require(binding and binding.device_id and not binding.closed
                    and getattr(binding, "browser_origin", None) == origin,
                    "browser_session_not_paired")
            await self.echo.authenticate(expected=(binding.device_id, binding.digest))
            token = secrets.token_hex(32)
            key = hashlib.sha256(token.encode()).hexdigest()
            settings = encoded(self.settings(binding))
            old_key = getattr(binding, "browser_grant", None)

            def write(db):
                require(db.execute("SELECT COUNT(*) FROM mac_browser_grants").fetchone()[0] < 128,
                        "browser_grant_limit")
                if old_key:
                    db.execute("DELETE FROM mac_browser_grants WHERE hash=?", (old_key,))
                db.execute("INSERT INTO mac_browser_grants VALUES(?,?,?,?,?,?)",
                           (key, origin, binding.device_id, binding.digest,
                            time.time() + MAX_AGE, settings))
            await self.transaction(write)
            binding.browser_grant = key
        response = web.json_response({"trusted": True}, headers={"Cache-Control": "no-store"})
        self.cookie(response, request, token)
        return response

    async def forget(self, request):
        grant = await self.lookup(request)
        if grant:
            await self.transaction(lambda db: db.execute(
                "DELETE FROM mac_browser_grants WHERE hash=?", (grant[0],)))
            for binding in list(self.echo.bindings.values()):
                if getattr(binding, "browser_grant", None) == grant[0]:
                    binding.browser_grant = None
                    await binding.forget_browser()
        response = web.json_response({"trusted": False}, headers={"Cache-Control": "no-store"})
        response.del_cookie(COOKIE, path="/", httponly=True, samesite="Strict")
        return response

    def routes(self, app):
        for name, handler in [("status", self.status), ("remember", self.remember),
                              ("forget", self.forget)]:
            async def route(request, handler=handler):
                try:
                    browser_origin(request)
                    return await handler(request)
                except (MacToolError, OSError, sqlite3.Error) as error:
                    code = str(error) if isinstance(error, MacToolError) else "browser_store_unavailable"
                    return web.json_response({"error": code}, status=403,
                                             headers={"Cache-Control": "no-store"})
            app.router.add_post("/api/tools/browser/" + name, route)
