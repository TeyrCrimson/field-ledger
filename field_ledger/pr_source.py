"""Read open PR/MR state from GitHub (`gh`) or GitLab (`glab`).

Parsers are pure and take JSON text, so they can be tested without a network.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .model import PullRequest

GH_CMD = ["gh", "pr", "list", "--state", "open", "--limit", "200",
          "--json", "headRefName,number,updatedAt,url"]
# NEEDS VERIFICATION: glab's JSON flag differs across versions (`--output json` vs `-F json`).
GLAB_CMD = ["glab", "mr", "list", "--per-page", "100", "--output", "json"]


def _parse_time(value: str) -> datetime:
    """ISO 8601 with a trailing Z (both CLIs emit this) to an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_gh(text: str) -> dict[str, PullRequest]:
    """`gh pr list --json headRefName,number,updatedAt,url` output -> {branch: PR}."""
    return {
        item["headRefName"]: PullRequest(
            branch=item["headRefName"],
            number=item["number"],
            updated_at=_parse_time(item["updatedAt"]),
            url=item["url"],
        )
        for item in json.loads(text)
    }


def parse_glab(text: str) -> dict[str, PullRequest]:
    """`glab mr list` JSON output (GitLab REST MR objects) -> {branch: PR}."""
    return {
        item["source_branch"]: PullRequest(
            branch=item["source_branch"],
            number=item["iid"],
            updated_at=_parse_time(item["updated_at"]),
            url=item["web_url"],
        )
        for item in json.loads(text)
    }


def fetch_prs(repo: Path, provider: str) -> dict[str, PullRequest]:
    """Ask the provider's CLI for open PRs. `none` skips the lookup entirely."""
    if provider == "none":
        return {}
    cmd, parse = {"gh": (GH_CMD, parse_gh), "glab": (GLAB_CMD, parse_glab)}[provider]
    out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=True).stdout
    return parse(out)
