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
  (battery: ready / depleted / storage / damaged; `settings.json` `kinds`, none until set).
  Builds are nodes of kind `build`.
- **Locations** are nodes flagged `fixed`: they can hold nodes but aren't moved on the fast path.
  External locations (`Logistics store`, `Lost`) are where custody exits go.
- **Contents follow their container** in one event. **Every move is cycle-checked.** Only a
  container kind holds things (ledger `settings.json` `kinds`; default no; places always,
  builds never), on the CLI and the board alike.
- **Location and state change through separate events.** Bulk items are one node with a count.
- IDs are `KIND-NN`; number width is the `id_digits` setting (default 2).
- Event types: ADD, MOVE, AUD, SEC, STATE, CFG, RESOLVE, VOID, RENAME, OWNER. AUD is written
  only from an audit screen (the board's, `fl audit --check`), never typed; found elsewhere puts the node there (a mismatch). STATE is a
  kit item's state from its kind's own list; SEC stays a build's fixed-five label.
- **CFG hashes are never typed** (Teyr, 2026-10-30): the tool reads the config (a file, or
  path@commit) and computes the SHA-256. No command, import line or hub request carries a hash.
  `cfg --check` against a copy of what's deployed writes a `mismatch` CFG when it differs.
- **Owner handover:** only the current owner writes OWNER, except anyone may claim after a
  nudge has gone unanswered for `nudge_after`.
- Event fields: id, type, item, to, logged_by, moved_by (defaults to logged_by), actor_source
  (device | telegram | import), device, occurred_at, recorded_at, time_source (device |
  prompted | import), source (+ original text for imports), sha (build deploys: head commit),
  batch (shared by the events one command wrote; undo takes them back together).

## Behaviour rules

- **Ordering:** latest wins; same-device events order by a per-device sequence number.
- **Conflicts (⚠):** two moves of the same node (directly or via a parent) within the conflict
  window, to different destinations, from different devices or with a prompted/import time.
  Same destination = duplicate, merged. One tap writes RESOLVE.
- **Origin:** a move's `src` is where the log last had the node; a typed "from" is only
  checked (`from-mismatch`). A new build starts at `build_home` (default `hq`), so nothing
  comes from nowhere.
- **ID-shaped destination** (`DRN-03`) that names no item: refused as a typo when that kit
  exists, asked once (CONFIRM) when it doesn't, then a known place. CLI and phone alike.
- **Readback:** every move echoes ID, name, previous location and new location
  (`✓ BAT-12 · Blue 6S · was in Case A → van`).
- **Undo:** VOIDs every event of your own last command (they share a `batch`: a deploy, a kit,
  a whole import), inside `undo_minutes` (default 10); refused after. A node the command
  created that someone has used since is left alone.
- **Phone writes:** the phone makes each write's id, occurred_at and seq; the hub stamps
  recorded_at and logs an id once. occurred_at more than 5 min after recorded_at gets a `future`
  flag; replay counts each event at min(occurred_at, recorded_at); undo's window starts at
  recorded_at. A queued write the hub would refuse or ask about goes to
  `needs-a-look/<id>.json` in the ledger repo, settled in place (log / dismiss), never dropped.
- **Phones over HTTPS:** `serve --lan` serves http and HTTPS on one port (first byte decides). The
  hub's CA lives in `~/.local/share/field-ledger/hub-ca/` (never the ledger repo), is limited to
  private IPs, and signs a hub certificate for the current address on each start. Phones join by
  QR code (`setup.html`); `sw.js` keeps the board openable offline. Needs `openssl`.
- **Derived state** (code mode): branch age and last commit from local Git, always, offline.

## Settings (defaults)

| Setting | Default |
|---|---|
| `id_digits` | `2` |
| `undo_minutes` | `10` |
| `conflict_window` | 5 min device / 60 min prompted or import |
| `nudge_after` | 1 working day |
| `ledger_dir` | `./ledger` |
| `build_home` | `hq` (ledger repo `settings.json`; `fl set build_home <loc>`) |

## Working here

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q      # all green; the count only grows (210 on 2026-10-29)
```

- Every change keeps the whole suite green and adds tests for its own behaviour.
- Match the existing style: small modules, plain functions, docstrings that say *why*.
- Branch per change, PR to `main`. Never commit `.venv/`, `ledger/`, `*.db` or tokens.
