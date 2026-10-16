# Fortress Console

The main UI for Fortress (Spec 01 §5): a Flutter Windows desktop app that talks to
Fortress Core on `127.0.0.1:47800`. See the top-level [README](../README.md) for how
to run it and its tests.

| File | What |
|---|---|
| `lib/api.dart` | Client for Core's localhost API |
| `lib/models.dart` | Typed views of Core's status and rules |
| `lib/state.dart` | Polls Core; runs every action |
| `lib/ui/` | Lock bar, setup/unlock, and the seven screens |
