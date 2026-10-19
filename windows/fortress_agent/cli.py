"""`fortress-agent`: enrol the PC, run the PC-layer lock, or show its status.

There is no unlock or edit here. Every change to Fortress is made in the Console on the
PC (Spec 01 §6.2). This only enrols the device and enforces what Core signs.
"""

import argparse
import os
import sys
from pathlib import Path

from .agent import Agent, AgentState
from .client import CoreError
from .signer import DeviceSigner


def default_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "Fortress" / "agent"
    return Path.home() / ".fortress-agent"


def _agent(data_dir: Path) -> Agent:
    signer = DeviceSigner(data_dir / "device.key")
    state = AgentState(data_dir / "agent_state.json")
    return Agent(state, signer)


def cmd_enrol(agent: Agent, args) -> int:
    try:
        agent.enrol(args.address, args.device_id, args.code)
    except CoreError as e:
        hint = {
            "bad_proof": "Wrong code. Check it against the Console (5 wrong tries cancel it).",
            "no_enrolment": f"No enrolment is waiting for {args.device_id!r}. Check the id, or make a new code.",
            "expired": "That code has expired. Make a new one in the Console.",
            "bad_core_proof": "The PC at that address could not prove it made this code. Not enrolled.",
            "unreachable": str(e),
        }.get(e.kind, str(e))
        print(f"fortress-agent: {hint}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"fortress-agent: {e}", file=sys.stderr)
        return 2
    p = agent.current_payload()
    print(f"Enrolled as {args.device_id}. Holding rules version {p['version']}.")
    print("Run `fortress-agent run` (as administrator) to start enforcing.")
    return 0


def cmd_status(agent: Agent, args) -> int:
    s = agent.state
    if not s.enrolled:
        print("Not enrolled. Run `fortress-agent enrol` with a code from the Console.")
        return 0
    from fortress_core import crypto

    print(f"Device:        {s.device_id}")
    print(f"Core:          {s.core_url}")
    print(f"Core key:      {crypto.key_id(crypto.b64d(s.core_public_key))}")
    print(f"Rules version: {s.highest_version}")
    if s.released:
        print("Released by the Console: Fortress has stood down on this PC.")
    print(f"Last check-in: {s.last_sync or 'never'}")
    if s.last_error:
        print(f"Last problem:  {s.last_error}")
    p = agent.current_payload()
    if p:
        from .enforce import active_schedule_ids, programs_to_block

        ids = active_schedule_ids(p, s.device_id)
        progs = programs_to_block(p, s.device_id)
        print(f"Blocks now:    {', '.join(ids) if ids else 'none'}")
        print(f"Programs:      {', '.join(sorted(progs)) if progs else 'none blocked now'}")
    return 0


def cmd_run(agent: Agent, args) -> int:
    if not agent.state.enrolled:
        print("fortress-agent: not enrolled yet. Run `fortress-agent enrol` first.", file=sys.stderr)
        return 2
    if os.name == "nt":
        from .service import WindowsPlatform
        platform = WindowsPlatform()
    else:
        print("fortress-agent: the PC layer only enforces on Windows; use `enrol`/`status` elsewhere.",
              file=sys.stderr)
        return 2
    from .service import AgentService

    service = AgentService(agent, platform)
    print("Fortress PC-layer lock running. Ctrl+C to stop (blocks are lifted while stopped).")
    try:
        service.run()
    except KeyboardInterrupt:
        service.stop()
        print("\nStopped.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fortress-agent", description="Fortress PC-layer lock (Spec 01 §7.2)")
    p.add_argument("--data-dir", type=Path, default=None, help=f"state and key (default {default_dir()})")
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("enrol", help="join Fortress with a one-time code from the Console")
    e.add_argument("address", help="the Console PC's address, e.g. 127.0.0.1 on the same PC")
    e.add_argument("device_id", help="the device id, e.g. pc")
    e.add_argument("code", help="the enrolment code, e.g. ABCDE-FGHJK")
    e.set_defaults(func=cmd_enrol)

    sub.add_parser("status", help="what this PC is enforcing").set_defaults(func=cmd_status)
    sub.add_parser("run", help="enforce the rules (Windows, as administrator)").set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agent = _agent(args.data_dir or default_dir())
    return args.func(agent, args)


if __name__ == "__main__":
    sys.exit(main())
