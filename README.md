# field-ledger

Shadow boards for things in flight. Two tools, one idea: everything checked out has a
visible slot, and an empty slot is a question someone has to answer.

| Tool | Tracks | Run with |
|---|---|---|
| Stale-work board | git branches and PRs | `python -m field_ledger` |
| Movement log | field kit (batteries, cameras, ...) | `python -m field_ledger.ledger` (or `fl`) |

Python 3.10+, standard library only. Nothing to install on a field laptop.

---

## Movement log

An append-only record of where each kit item is. Works fully offline: the database is a
single SQLite file, and two laptops' files can be merged later.

### Quick start

```bash
fl init teyr                         # once per laptop: creates field-ledger.db, sets your name
fl kit kit.csv                       # create item groups (see below)
fl move BAT-07 site-b                # log a movement
fl move BAT-07 site-b --from truck   # ...and say where it came from (checked against the log)
fl where BAT-07
fl at site-b
fl flags                             # everything that needs a second look
```

`fl` is installed by `pip install -e .`. Without installing, use `python -m field_ledger.ledger`.
The database path defaults to `./field-ledger.db`; override with `--db` or `FL_DB`.

### Kit file

```csv
prefix,name,count,location
BAT,Battery,12,truck
CAM,SIYI camera,3,case-1
```

Creates `BAT-01`..`BAT-12` and `CAM-01`..`CAM-03`. Prefixes are exactly 3 letters.
Re-running the same kit file changes nothing, and raising a count only adds the missing
items. To add items beyond the file, use `fl add BAT 2 --at truck` (creates BAT-13, BAT-14).

### Text grammar

The same grammar works with `fl run "..."`, in imported files, and (later) on the web page.

```
MOVE <ITEM> [<FROM>] > <TO>     MOVE BAT-07 truck > site-B
WHERE <ITEM>
AT <LOCATION>
VOID <EVENT-ID> <reason>        VOID 3f9a2c1e wrong battery
RENAME <OLD> > <NEW>            RENAME site-bb > site-b   (location typo fix)
```

### What gets accepted

| Input | Verdict | Why |
|---|---|---|
| `MOVE BAT-07 > site-b` | OK | |
| `move bat7 > Site-B` | OK | ID format and case are canonicalised by fixed rules (one input, one ID) |
| `MOVE BTA-07 > site-b` | REJECT, "did you mean BAT-07?" | Fuzzy matches are suggested, never auto-corrected |
| `MOVE BAT-99 > site-b` | REJECT | Not in the kit. Add it with `fl add` |
| `MOVE BAT-07 truck > site-b`, log says `site-a` | WARN, written + `from-mismatch` | Someone moved it without logging. Rejecting would throw away the true information |
| `MOVE BAT-07 > site-bb` (close to `site-b`) | CONFIRM, "did you mean site-b?" | Probable typo, caught before entry |
| `MOVE BAT-07 > yoeng's bag` (nothing similar) | WARN, written + `new-location` | New locations are allowed, but flagged |
| `MOVE BAT-07 > site-b` when already at `site-b` | CONFIRM | Probably moved away and back without being logged: worth chasing |
| Same move, same person, within 2 minutes | IGNORED | Double tap |
| `MOVE BAT-07` | REJECT, shows usage | |

CONFIRM asks `Log it anyway? [y/N]`. `--yes` answers yes. With no terminal (scripts),
the answer is no. Exit codes: `0` written or ignored, `1` rejected, `2` confirmation declined.

### Corrections never edit history

- **Wrong entry:** `fl void <id> <reason>`. The event stays in the log, marked void, and
  the item goes back to where it was before.
- **Location typo:** `fl rename-location site-bb site-b`. Every view shows `site-b` from then on;
  the stored events keep what was actually typed.

### Offline contingency

| Situation | What to do |
|---|---|
| Router up | One laptop holds the ledger; others use it over the network (web page: next release) |
| No router | The ledger laptop runs a hotspot. NEEDS VERIFICATION: whether your laptops/phones can host a hotspot with no internet uplink |
| No network at all | Every laptop logs to its own file. Afterwards: `fl merge other-laptop.db` |
| Phones only | Type commands into any notes app or chat, later `fl import notes.txt` |

`fl merge` and `fl import` are both safe to re-run: nothing is added twice.

**Import** picks up UPPERCASE commands anywhere in a line, so a WhatsApp/Telegram export line
like `[17/10/26, 13:05] Teyr: MOVE BAT-07 > site-B` works, and ordinary chat ("we should move
the truck") is skipped. Lines that would normally ask for confirmation are written and
flagged `unconfirmed-import`. Rejected lines stay retryable, so fix the kit and re-import.

Known import limits:
- Every imported line is attributed to the importing person (`--actor` to override) and
  timestamped at import time. Order within the file is kept, but chat timestamps are not read yet.
- Two identical moves in one file with nothing in between count as one report.

### Layout

| Module | Job | Pure? |
|---|---|---|
| `ledger/model.py` | Data types | yes |
| `ledger/ids.py` | Item ID and location rules | yes |
| `ledger/parse.py` | Text grammar | yes |
| `ledger/state.py` | Events to current state | yes |
| `ledger/validate.py` | Accept/reject rules | yes |
| `ledger/kit.py` | Kit file, numbering | yes |
| `ledger/importer.py` | Finding commands in text | yes |
| `ledger/store.py` | SQLite, merge | no |
| `ledger/service.py` | Validate, then write | no |
| `ledger/cli.py` | `fl` command | no |

---

## Stale-work board

Every remote branch is a tool checked out; a branch merged and deleted is a tool back in
its slot.

| Label | Meaning | Usual fix |
|---|---|---|
| `no-PR` | Branch exists, nobody has been asked to review it | Open the PR, or delete the branch |
| `PR-stale` | PR open, untouched for more than `--stale-days` | Ping the reviewer, or close it |
| `merged-not-deleted` | Every commit already in `--base` | Delete the remote branch |
| `in-flight` | PR open and moving | Nothing |

```bash
python -m field_ledger --repo /path/to/casio-edge --base origin/develop
python -m field_ledger --repo /path/to/casio-edge --base origin/develop --prs gh --hide-in-flight
```

It runs `git fetch --prune` first (skip with `--no-fetch`, which also makes it work offline).
Use a full clone: a shallow one breaks `merged-not-deleted`. On WSL, a repo under `/mnt/c/...`
works but git is slower there.

Known gaps:
- `--prs glab`: the JSON flag differs across glab versions. NEEDS VERIFICATION.
- `--prs gh` has a unit-tested parser but has not been run against a live repo yet.
- Fork PRs are matched by branch name only.

---

## Tests

```bash
pip install pytest
python -m pytest -q
```

## Roadmap

- Movement log: web page for phones, served from the ledger laptop
- Movement log: outbox that mirrors events to Telegram when a connection is available
- Board: daily post to the same channel; WIP-limit alert
