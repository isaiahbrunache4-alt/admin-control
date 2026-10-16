# Fortress

Self-control software for Isaiah's own devices. A Windows PC is the only control point;
the PC itself, a Pixel 8a and a Lenovo Idea Tab enforce website blocks, app blocks and scheduled blocks.
One password unlocks changes.

**Status: Phase 1 (Core) built and tested.** No Console or Agents yet.

- Design: [`docs/fortress_design.md`](docs/fortress_design.md)
- Rules and bundle format, for Agents: [`docs/rules_format.md`](docs/rules_format.md)

## Core (Phase 1)

```
cd core
python -m venv .venv
.venv/bin/pip install -e '.[test]'     # Windows: .venv\Scripts\pip
.venv/bin/pytest
```

The `fortress` command stands in for the Console until Phase 2:

```
fortress init                                   # set password, prints recovery code
fortress list add social
fortress item add social site tiktok.com *.reddit.com
fortress device add tablet android "Lenovo Idea Tab"
fortress schedule add social --devices tablet --days mon,tue,wed,thu,fri \
    --from 08:00 --to 15:00 --tz America/New_York
fortress block-now social 2
fortress check tablet site www.tiktok.com       # BLOCKED / allowed
fortress bundle --out bundle.json && fortress verify bundle.json
fortress status | show | activity | passwd | recover
```

Every changing command asks for the password, makes the change, then locks and
publishes a new signed bundle. The database defaults to `%PROGRAMDATA%\Fortress\fortress.db`
on Windows and `~/.fortress/fortress.db` elsewhere (`--db` to override).
