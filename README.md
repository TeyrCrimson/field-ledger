# field-ledger

A shadow board for work in flight. Every remote branch is a tool checked out; a branch
merged and deleted is a tool back in its slot. This makes the empty outlines visible.

## Labels

| Label | Meaning | Usual fix |
|---|---|---|
| `no-PR` | Branch exists, nobody has been asked to review it | Open the PR, or delete the branch |
| `PR-stale` | PR open, untouched for more than `--stale-days` | Ping the reviewer, or close it |
| `merged-not-deleted` | Every commit already in `--base` | Delete the remote branch |
| `in-flight` | PR open and moving | Nothing |

## Usage

Needs Python 3.10+ and git. No third-party dependencies.

```bash
# From the field-ledger checkout
python -m field_ledger --repo /path/to/casio-edge --base origin/develop

# With PR lookup (needs an authenticated gh or glab CLI)
python -m field_ledger --repo /path/to/casio-edge --base origin/develop --prs gh

# Only the problems
python -m field_ledger --repo /path/to/casio-edge --base origin/develop --prs gh --hide-in-flight
```

It runs `git fetch --prune` first (skip with `--no-fetch`).

**Shallow clones:** a `--depth 1` clone only has the default branch and no history, so
`merged-not-deleted` will be wrong. Run it on a normal clone.

**WSL note:** a repo on `/mnt/c/...` works, but git is slower there than on the Linux side.

## Layout

| Module | Job | Touches |
|---|---|---|
| `model.py` | Data types | nothing |
| `git_source.py` | Branches, merge check | git |
| `pr_source.py` | Open PRs/MRs | `gh` / `glab` |
| `classify.py` | Labels, sorting | nothing (pure) |
| `render.py` | Markdown output | nothing (pure) |
| `cli.py` | Wiring | all of the above |

## Tests

```bash
pip install pytest
python -m pytest -q
```

`tests/test_integration.py` builds a real throwaway repo with a bare remote, so it checks
the git calls, not just the logic.

## Known gaps

- `--prs glab`: the JSON flag differs across glab versions (`--output json` vs `-F json`).
  NEEDS VERIFICATION against the installed version.
- `--prs gh` has a unit-tested parser but has not been run against a live repo yet.
- Fork PRs: matched by head branch name only, so a fork branch with the same name would collide.

## Roadmap

- v1: labels (done in v0)
- v2: post the board to a Telegram channel daily
- v3: alert when in-flight items exceed a WIP limit
