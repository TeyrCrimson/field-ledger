from field_ledger.pr_source import fetch_prs, parse_gh, parse_glab

GH = '[{"headRefName":"feat/a","number":28,"updatedAt":"2026-10-01T03:00:00Z","url":"https://x/28"}]'
GLAB = '[{"source_branch":"feat/b","iid":5,"updated_at":"2026-10-02T03:00:00.000Z","web_url":"https://y/5"}]'


def test_parse_gh_keys_by_head_branch():
    prs = parse_gh(GH)
    assert prs["feat/a"].number == 28
    assert prs["feat/a"].updated_at.tzinfo is not None


def test_parse_glab_keys_by_source_branch():
    assert parse_glab(GLAB)["feat/b"].url == "https://y/5"


def test_none_provider_makes_no_call(tmp_path):
    assert fetch_prs(tmp_path, "none") == {}
