"""Fortress Agent for Windows: the PC-layer lock (Spec 01 §7.2, §8; Phases 7-8).

Follows the same Agent contract as the Android app (docs/agent_protocol.md): enrols once,
accepts only signed rules newer than it holds, blocks websites and programs on schedule,
keeps enforcing offline, checks in, and stands down on a signed release. It reuses
fortress_core for the crypto, bundle verification and schedule evaluation, so the PC and
the phones give the same answers, but it is a separate program with no access to the
signing key: nothing typed on the PC changes the rules without the Console and the password.
"""

AGENT_VERSION = "0.1.0"
