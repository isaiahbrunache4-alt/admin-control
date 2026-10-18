"""The Console's API: Fortress Core over HTTP on localhost only (Spec 01 §3.1, §5).

Reading needs nothing: the Console shows everything even while locked. Changing
anything needs the session token that `POST /unlock` returns. The token dies with the
unlock (Lock button, auto-relock, restart), so no other program on the PC can make
changes just because Fortress happens to be unlocked.
"""

import json
import math
import secrets
import threading
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import crypto, rules
from .agents import DEFAULT_AGENT_PORT, create_agent_app, lan_addresses
from .bundle import BundleRejected
from .core import Fortress, FortressError, Locked, NotSetUp, TooSoon, WrongPassword
from .rules import RuleError
from .schedule import active_blocks

DEFAULT_PORT = 47800
API = "/api/v1"


# ---- request bodies -------------------------------------------------------------------

class Password(BaseModel):
    password: str


class NewPassword(BaseModel):
    current: str
    new: str


class Recover(BaseModel):
    code: str
    new_password: str


class Name(BaseModel):
    name: str


class Item(BaseModel):
    kind: Literal["domains", "android_packages", "windows_programs"]
    item: str


class Weekly(BaseModel):
    list: str
    devices: list[str] = Field(default_factory=lambda: ["all"])
    days: list[str]
    from_: str = Field(alias="from")
    to: str
    tz: str


class BlockNow(BaseModel):
    list: str
    hours: float
    devices: list[str] = Field(default_factory=lambda: ["all"])


class Device(BaseModel):
    id: str
    name: str
    platform: Literal["android", "windows"]


class Settings(BaseModel):
    unlock_delay_minutes: int | None = None
    relock_minutes: int | None = None


class LockUntil(BaseModel):
    until: datetime


# ---- errors -----------------------------------------------------------------------------

def _error(status: int, kind: str, message: str, headers: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"error": kind, "message": message, **extra}, status, headers=headers)


def _fortress_error(request: Request, e: FortressError) -> JSONResponse:
    if isinstance(e, TooSoon):
        now = request.app.state.fortress.clock()
        wait = max(1, math.ceil((e.retry_after - now).total_seconds()))
        return _error(429, "too_soon", str(e), headers={"Retry-After": str(wait)},
                      retry_after=rules.format_utc(e.retry_after))
    if isinstance(e, WrongPassword):
        return _error(401, "wrong_password", str(e))
    if isinstance(e, Locked):
        return _error(423, "locked", str(e))
    if isinstance(e, NotSetUp):
        return _error(409, "not_set_up", str(e))
    return _error(400, "refused", str(e))


# ---- the app --------------------------------------------------------------------------

def create_app(fortress: Fortress, guard: threading.Lock | None = None,
               agent_port: int = DEFAULT_AGENT_PORT) -> FastAPI:
    app = FastAPI(title="Fortress Core", docs_url=None, redoc_url=None, openapi_url=None)
    # Refuse any Host but localhost, so a web page cannot reach this through DNS rebinding.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.fortress = fortress
    # One SQLite connection and one unlocked key: serialise every request on them,
    # including the Agents' (agents.py shares this lock when both run).
    guard = guard or threading.Lock()
    session = {"token": None}

    app.add_exception_handler(FortressError, _fortress_error)
    app.add_exception_handler(
        RuleError, lambda req, e: _error(400, "invalid", str(e)))
    app.add_exception_handler(
        BundleRejected, lambda req, e: _error(400, "rejected", str(e)))

    def locked_section():
        with guard:
            yield fortress

    def unlocked_section(authorization: str | None = Header(default=None)):
        with guard:
            token = session["token"]
            given = (authorization or "").removeprefix("Bearer ").strip()
            if fortress.state() == "locked":
                session["token"] = None
                raise Locked("unlock first")
            if token is None or not secrets.compare_digest(given, token):
                raise Locked("this unlock belongs to another session")
            yield fortress

    reader = Depends(locked_section)
    editor = Depends(unlocked_section)

    def status_of(f: Fortress) -> dict:
        if not f.is_set_up:
            return {"set_up": False, "state": "locked"}
        state = f.state()
        if state == "locked":
            session["token"] = None
        now = f.clock()
        published = _published_rules(f)
        devices = []
        for d in f.store.devices():
            blocks = active_blocks(published, d["id"], now)
            devices.append({
                "id": d["id"], "name": d["name"], "platform": d["platform"],
                "added_at": d["added_at"], "last_seen": d["last_seen"],
                "status": f.device_status(d), "active_schedules": blocks.schedule_ids,
                "enrolled": bool(d["public_key"]), "enrolled_at": d["enrolled_at"],
                "version_held": d["version_held"], "agent_version": d["agent_version"],
            })
        unlocks_at = f.unlocks_at
        return {
            "set_up": True,
            "state": state,
            "unlocks_at": rules.format_utc(unlocks_at) if unlocks_at else None,
            "now": rules.format_utc(now),
            "version": f.store.get("version"),
            "key_id": crypto.key_id(f.public_key),
            "unpublished_changes": bool(f.store.get("dirty")),
            "locked_until": f.store.get("locked_until"),
            "unlock_delay_minutes": f.store.get("unlock_delay_minutes", 0),
            "relock_minutes": f.store.get("relock_minutes"),
            "devices": devices,
            "active_schedules": sorted(
                {s for d in devices for s in d["active_schedules"]}
                | set(active_blocks(published, "all", now).schedule_ids),
                key=lambda s: int(s[1:])),
        }

    # -- reading

    @app.get(API + "/status")
    def status(f: Fortress = reader):
        return status_of(f)

    @app.get(API + "/rules")
    def get_rules(f: Fortress = reader):
        return f.draft

    @app.get(API + "/activity")
    def activity(limit: int = 100, f: Fortress = reader):
        return f.store.activity(max(1, min(limit, 1000)))

    @app.get(API + "/bundle")
    def latest_bundle(f: Fortress = reader):
        return f.latest_bundle()

    # -- setup, lock, unlock

    @app.post(API + "/setup")
    def setup(body: Password, f: Fortress = reader):
        return {"recovery_code": f.setup(body.password)}

    @app.post(API + "/unlock")
    def unlock(body: Password, f: Fortress = reader):
        f.unlock(body.password)
        session["token"] = secrets.token_urlsafe(32)
        return {"token": session["token"], **status_of(f)}

    @app.post(API + "/lock")
    def lock(f: Fortress = editor):
        f.lock()
        session["token"] = None
        return status_of(f)

    @app.post(API + "/recover")
    def recover(body: Recover, f: Fortress = reader):
        f.lock()
        session["token"] = None
        f.recover(body.code, body.new_password)
        return status_of(f)

    # -- editing (needs the session token)

    def done(f: Fortress, **extra) -> dict:
        return {"rules": f.draft, **status_of(f), **extra}

    @app.post(API + "/lists")
    def add_list(body: Name, f: Fortress = editor):
        f.add_list(body.name)
        return done(f)

    @app.delete(API + "/lists/{name}")
    def remove_list(name: str, f: Fortress = editor):
        f.remove_list(name)
        return done(f)

    @app.post(API + "/lists/{name}/items")
    def add_item(name: str, body: Item, f: Fortress = editor):
        f.add_item(name, body.kind, body.item)
        return done(f)

    @app.post(API + "/lists/{name}/items/remove")
    def remove_item(name: str, body: Item, f: Fortress = editor):
        f.remove_item(name, body.kind, body.item)
        return done(f)

    @app.post(API + "/allow")
    def allow(body: Item, f: Fortress = editor):
        f.allow(body.kind, body.item)
        return done(f)

    @app.post(API + "/allow/remove")
    def disallow(body: Item, f: Fortress = editor):
        f.disallow(body.kind, body.item)
        return done(f)

    @app.post(API + "/schedules")
    def add_schedule(body: Weekly, f: Fortress = editor):
        sid = f.add_schedule({
            "kind": "weekly", "list": body.list, "devices": body.devices,
            "days": body.days, "from": body.from_, "to": body.to, "tz": body.tz,
        })
        return done(f, id=sid)

    @app.post(API + "/block-now")
    def block_now(body: BlockNow, f: Fortress = editor):
        sid = f.block_now(body.list, body.hours, body.devices)
        return done(f, id=sid)

    @app.delete(API + "/schedules/{schedule_id}")
    def remove_schedule(schedule_id: str, f: Fortress = editor):
        f.remove_schedule(schedule_id)
        return done(f)

    @app.post(API + "/devices")
    def add_device(body: Device, f: Fortress = editor):
        f.add_device(body.id, body.name, body.platform)
        return done(f)

    @app.delete(API + "/devices/{device_id}")
    def remove_device(device_id: str, f: Fortress = editor):
        f.remove_device(device_id)
        return done(f)

    @app.post(API + "/devices/{device_id}/enrolment")
    def start_enrolment(device_id: str, f: Fortress = editor):
        code, expires = f.start_enrolment(device_id)
        return {"code": code, "expires_at": rules.format_utc(expires), "device_id": device_id,
                "port": agent_port, "addresses": lan_addresses(), "key_id": crypto.key_id(f.public_key)}

    @app.post(API + "/publish")
    def publish(f: Fortress = editor):
        f.publish()
        return done(f)

    @app.post(API + "/settings")
    def settings(body: Settings, f: Fortress = editor):
        if body.unlock_delay_minutes is not None:
            f.set_unlock_delay(body.unlock_delay_minutes)
        if body.relock_minutes is not None:
            f.set_relock_minutes(body.relock_minutes)
        return done(f)

    @app.post(API + "/lock-until")
    def lock_until(body: LockUntil, f: Fortress = editor):
        until = body.until
        if until.tzinfo is None:
            raise RuleError("give the time with a time zone")
        f.lock_until(until.astimezone(timezone.utc))
        session["token"] = None
        return status_of(f)

    @app.post(API + "/password")
    def change_password(body: NewPassword, f: Fortress = editor):
        f.change_password(body.current, body.new)
        return status_of(f)

    return app


def _published_rules(f: Fortress) -> dict:
    """What the devices are enforcing: the latest signed bundle, not the draft."""
    env = f.latest_bundle()
    return json.loads(crypto.b64d(env["payload"]))["rules"]


def serve(fortress: Fortress, port: int = DEFAULT_PORT, agent_host: str | None = "0.0.0.0",
          agent_port: int = DEFAULT_AGENT_PORT) -> None:
    """The Console's API on localhost and, unless agent_host is None, the Agents' API
    on the home network, in one process sharing one lock."""
    import asyncio

    import uvicorn

    guard = threading.Lock()
    servers = [uvicorn.Server(uvicorn.Config(
        create_app(fortress, guard, agent_port), host="127.0.0.1", port=port, log_level="warning"))]
    if agent_host is not None:
        servers.append(uvicorn.Server(uvicorn.Config(
            create_agent_app(fortress, guard), host=agent_host, port=agent_port, log_level="warning")))

    async def run_all():
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(run_all())
