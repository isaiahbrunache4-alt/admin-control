# Beeminder check

Runs hourly on the PC and posts a 1 to one Beeminder goal (Do More, 1 a day) on days when
every rule passes. A day with a failed rule gets no point; the goal's own slack in
Beeminder decides how many missed days it allows before it derails.

| Rule | Passes when | Data |
|---|---|---|
| `devices` | every listed device checked in within `max_hours` | Fortress Core's status page |
| `deliveries` | at most `max_per_week` delivery orders Monday to Sunday | Pocket Ledger for Windows |
| `workouts` | last week, every training day in Block Trainer was fully logged (checked on Mondays) | Block Trainer, via Fortress Agent and Core |
| `weight` | a bodyweight entry dated today | Block Trainer, via Fortress Agent and Core |

Leave a section out of `config.json` to turn that rule off. `devices` is always on.

Block Trainer hands Fortress Agent a summary whenever you log something; the Agent passes
it to Core at each check-in (`docs/agent_protocol.md`, "reports"), and this script reads
it from `http://127.0.0.1:47800/api/v1/reports`.

## Files

- `beeminder_check.py`: the check. Standard library only, Python 3.9+.
- `config.example.json`: copy to a folder only administrators can read
  (`C:\ProgramData\Fortress\beeminder\config.json`), then fill in the username and the token
  from https://www.beeminder.com/api/v1/auth_token.json.

The log (`beeminder-log.txt`) and state (`beeminder-state.json`) are written next to the
config.

## Run

```
python beeminder_check.py --config C:\ProgramData\Fortress\beeminder\config.json --dry-run
python beeminder_check.py --config C:\ProgramData\Fortress\beeminder\config.json
```

The setup guide's Parts 9 and 11 run it hourly as SYSTEM.
