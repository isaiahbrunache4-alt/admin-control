"""`fortress`: the Phase 1 command line for Core, until the Console exists.

Each changing command asks for the password, unlocks, makes the change, then locks
again (which signs and publishes it). Reading commands need no password.
"""

import argparse
import getpass
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import bundle, crypto, rules
from .core import Fortress, FortressError
from .rules import RuleError
from .schedule import is_app_blocked, is_domain_blocked

KIND_ALIASES = {
    "domain": "domains", "site": "domains",
    "app": "android_packages", "package": "android_packages",
    "program": "windows_programs", "exe": "windows_programs",
}


def default_db() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Fortress" / "fortress.db"
    return Path.home() / ".fortress" / "fortress.db"


def _kind(text: str) -> str:
    k = KIND_ALIASES.get(text, text)
    if k not in rules.ITEM_KINDS:
        raise argparse.ArgumentTypeError(f"kind is one of: {', '.join(KIND_ALIASES)}")
    return k


def _devices(text: str) -> list[str]:
    return [d.strip() for d in text.split(",") if d.strip()]


def _read_secret(args, prompt: str) -> str:
    if args.password_stdin:
        line = sys.stdin.readline()
        if not line:
            raise FortressError("expected a password on standard input")
        return line.rstrip("\r\n")
    return getpass.getpass(prompt)


def _new_secret(args, prompt: str) -> str:
    first = _read_secret(args, prompt)
    if not args.password_stdin and getpass.getpass("Again: ") != first:
        raise FortressError("the two passwords differ")
    return first


def _unlocked(f: Fortress, args) -> None:
    state = f.unlock(_read_secret(args, "Fortress password: "))
    if state == "pending":
        f.lock()
        raise FortressError("an unlock delay is set; the command line cannot wait it out")


# ---- commands ----------------------------------------------------------------------

def cmd_init(f, args):
    code = f.setup(_new_secret(args, "New Fortress password: "))
    print("Fortress is set up and locked.")
    print()
    print("Recovery code (shown only now; print it and keep it somewhere safe):")
    print()
    print("    " + code)
    print()
    print(f"Public key id: {crypto.key_id(f.public_key)}")


def cmd_status(f, args):
    print(f"Lock:       {f.state()}")
    print(f"Version:    {f.store.get('version')}")
    print(f"Key id:     {crypto.key_id(f.public_key)}")
    until = f.store.get("locked_until")
    if until:
        print(f"Locked until {until}")
    delay = f.store.get("unlock_delay_minutes", 0)
    if delay:
        print(f"Unlock delay: {delay} min")
    if f.store.get("dirty"):
        print("Unpublished changes: yes")
    devices = f.store.devices()
    print(f"Devices:    {len(devices)}")
    for d in devices:
        print(f"  {d['id']:<16} {d['platform']:<8} {f.device_status(d):<6} {d['name']}")


def cmd_show(f, args):
    print(json.dumps(f.draft, indent=2))


def _edit(fn):
    """Wrap a changing command: unlock, run it, lock (publishing)."""
    def run(f, args):
        _unlocked(f, args)
        before = f.store.get("version")
        try:
            out = fn(f, args)
        finally:
            f.lock()
        after = f.store.get("version")
        print(f"Published version {after}." if after != before else "Saved; the rules are unchanged.")
        return out
    return run


@_edit
def cmd_list_add(f, args):
    f.add_list(args.name)


@_edit
def cmd_list_remove(f, args):
    f.remove_list(args.name)


@_edit
def cmd_item_add(f, args):
    for item in args.items:              # all or nothing: check every item first
        rules.normalize_item(args.kind, item)
    for item in args.items:
        f.add_item(args.list, args.kind, item)


@_edit
def cmd_item_remove(f, args):
    for item in args.items:
        f.remove_item(args.list, args.kind, item)


@_edit
def cmd_allow_add(f, args):
    f.allow(args.kind, args.item)


@_edit
def cmd_allow_remove(f, args):
    f.disallow(args.kind, args.item)


@_edit
def cmd_schedule_add(f, args):
    sid = f.add_schedule({
        "kind": "weekly", "list": args.list, "devices": args.devices,
        "days": [d.strip().lower() for d in args.days.split(",")],
        "from": args.start, "to": args.end, "tz": args.tz,
    })
    print(f"Added schedule {sid}.")


@_edit
def cmd_schedule_remove(f, args):
    f.remove_schedule(args.id)


@_edit
def cmd_block_now(f, args):
    sid = f.block_now(args.list, args.hours, args.devices)
    print(f"Added one-off block {sid}.")


@_edit
def cmd_device_add(f, args):
    f.add_device(args.id, args.name, args.platform)


@_edit
def cmd_device_remove(f, args):
    f.remove_device(args.id)


@_edit
def cmd_publish(f, args):
    f.publish()


def cmd_passwd(f, args):
    current = _read_secret(args, "Current password: ")
    if f.unlock(current) == "pending":
        f.lock()
        raise FortressError("an unlock delay is set; the command line cannot wait it out")
    try:
        f.change_password(current, _new_secret(args, "New password: "))
    finally:
        f.lock()
    print("Password changed.")


def cmd_recover(f, args):
    code = _read_secret(args, "Recovery code: ")
    f.recover(code, _new_secret(args, "New password: "))
    print("Password reset. Fortress is locked.")


def cmd_bundle(f, args):
    env = f.latest_bundle()
    text = json.dumps(env, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)


def cmd_pubkey(f, args):
    print(crypto.b64e(f.public_key))


def cmd_verify(f, args):
    """Check a bundle file the way an Agent would (contract A2)."""
    env = json.loads(Path(args.file).read_text(encoding="utf-8"))
    pub = crypto.b64d(args.pubkey) if args.pubkey else f.public_key
    payload = bundle.BundleVerifier(pub, args.newer_than).accept(env)
    print(f"OK: version {payload['version']}, issued {payload['issued_at']}")


def cmd_check(f, args):
    """Would this site or app be blocked on a device right now (or at --at)?"""
    now = rules.parse_utc(args.at) if args.at else datetime.now().astimezone()
    r = f.draft if args.draft else json.loads(
        crypto.b64d(f.latest_bundle()["payload"]))["rules"]
    if args.kind == "domains":
        blocked = is_domain_blocked(r, args.device, args.item, now)
    else:
        blocked = is_app_blocked(r, args.device, args.kind, args.item, now)
    print("BLOCKED" if blocked else "allowed")
    return 0 if not blocked else 3


def cmd_activity(f, args):
    for a in reversed(f.store.activity(args.limit)):
        print(f"{a['at']}  {a['kind']:<15} {a['detail']}")


# ---- argument parsing ----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fortress", description="Fortress Core (Spec 01, Phase 1)")
    p.add_argument("--db", type=Path, default=None, help=f"database (default {default_db()})")
    p.add_argument("--password-stdin", action="store_true",
                   help="read passwords and codes from standard input, one per line")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="first-time setup").set_defaults(func=cmd_init)
    sub.add_parser("status", help="lock state, version, devices").set_defaults(func=cmd_status)
    sub.add_parser("show", help="print the current rules").set_defaults(func=cmd_show)

    lst = sub.add_parser("list", help="block lists").add_subparsers(dest="sub", required=True)
    x = lst.add_parser("add"); x.add_argument("name"); x.set_defaults(func=cmd_list_add)
    x = lst.add_parser("remove"); x.add_argument("name"); x.set_defaults(func=cmd_list_remove)

    item = sub.add_parser("item", help="items in a block list").add_subparsers(dest="sub", required=True)
    for verb, fn in (("add", cmd_item_add), ("remove", cmd_item_remove)):
        x = item.add_parser(verb)
        x.add_argument("list"); x.add_argument("kind", type=_kind); x.add_argument("items", nargs="+")
        x.set_defaults(func=fn)

    al = sub.add_parser("allow", help="the always-allowed list").add_subparsers(dest="sub", required=True)
    for verb, fn in (("add", cmd_allow_add), ("remove", cmd_allow_remove)):
        x = al.add_parser(verb); x.add_argument("kind", type=_kind); x.add_argument("item")
        x.set_defaults(func=fn)

    sch = sub.add_parser("schedule", help="weekly schedules").add_subparsers(dest="sub", required=True)
    x = sch.add_parser("add")
    x.add_argument("list"); x.add_argument("--devices", type=_devices, default=["all"])
    x.add_argument("--days", required=True, help="e.g. mon,tue,wed,thu,fri")
    x.add_argument("--from", dest="start", required=True, help="HH:MM")
    x.add_argument("--to", dest="end", required=True, help="HH:MM (earlier than --from = overnight)")
    x.add_argument("--tz", required=True, help="e.g. America/New_York")
    x.set_defaults(func=cmd_schedule_add)
    x = sch.add_parser("remove"); x.add_argument("id"); x.set_defaults(func=cmd_schedule_remove)

    x = sub.add_parser("block-now", help="block a list for N hours from now")
    x.add_argument("list"); x.add_argument("hours", type=float)
    x.add_argument("--devices", type=_devices, default=["all"])
    x.set_defaults(func=cmd_block_now)

    dev = sub.add_parser("device", help="enrolled devices").add_subparsers(dest="sub", required=True)
    x = dev.add_parser("add")
    x.add_argument("id"); x.add_argument("platform", choices=rules.PLATFORMS); x.add_argument("name")
    x.set_defaults(func=cmd_device_add)
    x = dev.add_parser("remove", help="send a signed release")
    x.add_argument("id"); x.set_defaults(func=cmd_device_remove)

    sub.add_parser("publish", help="sign and publish the rules now").set_defaults(func=cmd_publish)
    sub.add_parser("passwd", help="change the password").set_defaults(func=cmd_passwd)
    sub.add_parser("recover", help="reset the password with the recovery code").set_defaults(func=cmd_recover)

    x = sub.add_parser("bundle", help="print the latest signed bundle")
    x.add_argument("--out"); x.set_defaults(func=cmd_bundle)
    sub.add_parser("pubkey", help="print Core's public key").set_defaults(func=cmd_pubkey)

    x = sub.add_parser("verify", help="check a bundle file as an Agent would")
    x.add_argument("file"); x.add_argument("--pubkey", help="base64; default: this Fortress's key")
    x.add_argument("--newer-than", type=int, default=0)
    x.set_defaults(func=cmd_verify)

    x = sub.add_parser("check", help="is a site/app blocked on a device now?")
    x.add_argument("device"); x.add_argument("kind", type=_kind); x.add_argument("item")
    x.add_argument("--at", help="ISO date-time with zone; default now")
    x.add_argument("--draft", action="store_true", help="check the draft, not the published bundle")
    x.set_defaults(func=cmd_check)

    x = sub.add_parser("activity", help="recent activity log")
    x.add_argument("--limit", type=int, default=50); x.set_defaults(func=cmd_activity)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    f = Fortress(args.db or default_db())
    try:
        if args.command != "init" and not f.is_set_up:
            raise FortressError("Fortress is not set up; run `fortress init`")
        return args.func(f, args) or 0
    except (FortressError, RuleError, bundle.BundleRejected) as e:
        print(f"fortress: {e}", file=sys.stderr)
        return 2
    finally:
        f.close()


if __name__ == "__main__":
    sys.exit(main())
