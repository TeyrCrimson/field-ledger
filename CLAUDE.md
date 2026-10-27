# CLAUDE.md — field-ledger

Condensed from the field-ledger design doc (kept privately; this file carries what code
needs). `README.md` is the user-facing version. If code and this file disagree, ask; don't
silently pick one.

## What it is

One record of where things are, physical and virtual: which kit is in which case, and which
build is at which site. **One tool, two modes** sharing one event store and one board:

- **Code mode** (built first): branch/build nodes; which build is at which location.
- **Field mode**: physical kit (batteries, cases, gazebos).

Non-goals: real-time sync, logins, replacing the team chat, understanding free-text chat,
security labels from a scanner (set by hand for now).

## Hard constraints

- **Stdlib only.** `dependencies = []` in `pyproject.toml` stays empty; pytest is dev-only.
  Python >= 3.10.
- **Offline first.** Everything works airgapped. Forge APIs (GitHub/GitLab) are optional and
  need a token kept out of the repo.
- **This repo is public. Ledger data never goes in it.** Each ledger is its own nested Git repo
  in a gitignored folder (`ledger_dir`, default `./ledger`) with its own private remote or none.
  `field-ledger init` creates it. Tokens live in a gitignored file or env var.
- **Event files in Git are the record.** One file per event; new files never conflict. SQLite is
  a rebuildable cache, never the record. `ledger/store.py` is the only impure storage module, so
  the storage swap stays contained there.
- **Append-only.** Events are never edited or deleted. Corrections are events: `VOID <id>
  <reason>` cancels one, `RENAME <old> > <new>` fixes a location typo in views while stored
  events keep what was typed.
- **Pure core.** State = replay of all events in order, one pure function. Every view (where is
  X, what's at Y, history, conflicts, audit due) reads from it. Keep `model`, `ids`, `parse`,
  `state`, `validate`, `kit`, `importer` pure; I/O lives in `store`, `service`, `cli`.

## Model

- **One node type.** Every ID'd thing is a node with a `kind`; each kind defines its own states
  (battery: ready / depleted / storage / damaged). Builds are nodes of kind `build`/`branch`.
- **Locations** are nodes flagged `fixed`: they can hold nodes but aren't moved on the fast path.
  External locations (`Logistics store`, `Lost`) are where custody exits go.
- **Contents follow their container** in one event. **Every move is cycle-checked.**
- **Location and state change through separate events.** Bulk items are one node with a count.
- IDs are `KIND-NN`; number width is the `id_digits` setting (default 2).
- Event types: MOV, AUD, SEC, CFG, RESOLVE, VOID, RENAME, OWNER.
- Event fields: id, type, item, to, logged_by, moved_by (defaults to logged_by), actor_source
  (device | telegram | import), device, occurred_at, recorded_at, time_source (device |
  prompted | import), source (+ original text for imports).

## Behaviour rules

- **Ordering:** latest wins; same-device events order by a per-device sequence number.
- **Conflicts (⚠):** two moves of the same node (directly or via a parent) within the conflict
  window, to different destinations, from different devices or with a prompted/import time.
  Same destination = duplicate, merged. One tap writes RESOLVE.
- **Readback:** every move echoes ID, name, previous location and new location
  (`✓ BAT-12 · Blue 6S · was in Case A → van`).
- **Undo:** VOID of your own last event, inside `undo_minutes` (default 10); refused after.
- **Derived state** (code mode): branch age and last commit from local Git, always, offline.

## Settings (defaults)

| Setting | Default |
|---|---|
| `id_digits` | `2` |
| `undo_minutes` | `10` |
| `conflict_window` | 5 min device / 60 min prompted or import |
| `nudge_after` | 2 working days |
| `ledger_dir` | `./ledger` |

## Working here

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q      # baseline: 56 passed (2026-10-27)
```

- Every change keeps the whole suite green and adds tests for its own behaviour.
- Match the existing style: small modules, plain functions, docstrings that say *why*.
- Branch per change, PR to `main`. Never commit `.venv/`, `ledger/`, `*.db` or tokens.
