import base64
import json

import pytest

from portfolio import config
from portfolio.matrix import PASS, UNKNOWN, VIOLATION
from portfolio.sds_checks import (
    EVIDENCE_PATH,
    check_behavior_evidence,
    check_branch_settings,
    check_cred_inventory,
    check_declaration,
    check_landing_inert,
)

SLUG = "AlobarQuest/RentVSBuyGA"
NOT_FOUND = "gh: Not Found (HTTP 404)\n"
TARGET = 'factory_target = true\nfactory_target_reason = "inert, safe to try"\n'


def _inventory(credential_id, secret, repo):
    return (
        f'[[credential]]\nid = "{credential_id}"\n'
        f'  [[credential.consumer]]\n  kind = "gh-actions-secret"\n'
        f'  repo = "{repo}"\n  name = "{secret}"\n'
    )


ORCH = _inventory("orchestrator-factory-runner-bearer", "FACTORY_RUNNER_TOKEN", SLUG)
RUNNER = _inventory("factory-pr-token", "FACTORY_PR_TOKEN", SLUG)


def _serve(files, fail=()):
    """`gh_read` over {(repo, path): text}; every named repo answers its own read."""
    repos = {repo for repo, _ in files} | {SLUG}

    def gh_read(args):
        path = args[-1]
        for needle in fail:
            if needle in path:
                return None, "HTTP 500"
        for repo in repos:
            if path == f"repos/{repo}":
                return json.dumps({"full_name": repo}), ""
            prefix = f"repos/{repo}/contents/"
            if path.startswith(prefix):
                key = (repo, path[len(prefix) :])
                if key not in files:
                    return None, NOT_FOUND
                content = base64.b64encode(files[key].encode()).decode()
                return json.dumps({"content": content, "encoding": "base64"}), ""
        raise AssertionError(f"unexpected gh_read args: {args}")

    return gh_read


def _inventories(orch=ORCH, runner=RUNNER):
    files = {}
    if orch is not None:
        files[("AlobarQuest/orchestrator", ".cred-consumers.toml")] = orch
    if runner is not None:
        files[("AlobarQuest/factory-runner", ".cred-consumers.toml")] = runner
    return files


def _decl(text):
    files = {} if text is None else {(SLUG, "factory-target.toml"): text}
    return check_declaration(SLUG, gh_read=_serve(files))


def test_declared_true_passes():
    assert _decl(TARGET)["status"] == PASS


def test_absent_declaration_is_violation():
    out = _decl(None)
    assert out["status"] == VIOLATION
    assert out["details"][0]["id"] == "sds.declaration-absent"


def test_false_declaration_is_violation():
    out = _decl('factory_target = false\nfactory_target_reason = "no"\n')
    assert out["status"] == VIOLATION
    assert out["details"][0]["id"] == "sds.declaration-false"


def test_bare_true_is_malformed():
    out = _decl("factory_target = true\n")
    assert out["status"] == VIOLATION
    assert out["details"][0]["id"] == "sds.declaration-malformed"


def test_unreadable_is_unknown():
    out = check_declaration(SLUG, gh_read=lambda args: (None, "HTTP 500"))
    assert out["status"] == UNKNOWN
    assert out["details"][0]["id"] == "sds.declaration-unreadable"


def test_inventory_both_listed_passes():
    out = check_cred_inventory(SLUG, gh_read=_serve(_inventories()))
    assert out["status"] == PASS


def test_inventory_missing_one_names_it():
    out = check_cred_inventory(SLUG, gh_read=_serve(_inventories(runner="version = 1\n")))
    assert out["status"] == VIOLATION
    assert [d["id"] for d in out["details"]] == ["sds.inventory-missing-factory-pr-token"]


def test_inventory_missing_both_in_order():
    out = check_cred_inventory(SLUG, gh_read=_serve(_inventories("version = 1\n", "version = 1\n")))
    assert [d["id"] for d in out["details"]] == [
        "sds.inventory-missing-orchestrator-factory-runner-bearer",
        "sds.inventory-missing-factory-pr-token",
    ]


def test_inventory_slug_match_ignores_case():
    out = check_cred_inventory(SLUG.lower(), gh_read=_serve(_inventories()))
    assert out["status"] == PASS


def test_inventory_wrong_secret_name_does_not_count():
    wrong = _inventory("factory-pr-token", "SOMETHING_ELSE", SLUG)
    out = check_cred_inventory(SLUG, gh_read=_serve(_inventories(runner=wrong)))
    assert out["status"] == VIOLATION


def test_inventory_read_failure_is_unknown():
    out = check_cred_inventory(
        SLUG, gh_read=_serve(_inventories(), fail=("factory-runner/contents",))
    )
    assert out["status"] == UNKNOWN
    assert out["details"][0]["id"] == "sds.inventory-unreadable"
    assert "AlobarQuest/factory-runner" in out["details"][0]["message"]


def test_inventory_not_toml_is_unknown():
    out = check_cred_inventory(SLUG, gh_read=_serve(_inventories(orch="= not toml [")))
    assert out["status"] == UNKNOWN
    assert out["details"][0]["id"] == "sds.inventory-unreadable"


REPO_OK = {
    "default_branch": "main",
    "allow_squash_merge": True,
    "squash_merge_commit_message": "COMMIT_MESSAGES",
    "allow_auto_merge": True,
}
PROTECTION_OK = {"required_status_checks": {"strict": False, "contexts": ["Quality"]}}
UNPROTECTED = "gh: Branch not protected (HTTP 404)\n"


def _settings(repo, protection):
    """`gh_read` serving the repo body and the protection body (a dict, raw text or error tuple)."""

    def gh_read(args):
        path = args[-1]
        answer = protection if path.endswith("/protection") else repo
        if isinstance(answer, tuple):
            return answer
        return (answer if isinstance(answer, str) else json.dumps(answer)), ""

    return gh_read


def _ids(out):
    return [d["id"] for d in out["details"]]


def test_fully_configured_passes():
    assert check_branch_settings(SLUG, gh_read=_settings(REPO_OK, PROTECTION_OK))["status"] == PASS


def test_rentvsbuyga_as_surveyed():
    repo = {**REPO_OK, "allow_auto_merge": False}
    out = check_branch_settings(SLUG, gh_read=_settings(repo, (None, UNPROTECTED)))
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.no-protection", "sds.auto-merge-off"]


def test_every_unmet_setting_in_listed_order():
    repo = {"default_branch": "main"}
    protection = {
        "required_status_checks": {"strict": True, "contexts": [], "checks": []},
        "required_pull_request_reviews": {"required_approving_review_count": 1},
    }
    out = check_branch_settings(SLUG, gh_read=_settings(repo, protection))
    assert _ids(out) == [
        "sds.squash-disallowed",
        "sds.squash-message",
        "sds.no-required-check",
        "sds.strict",
        "sds.review-required",
        "sds.auto-merge-off",
    ]


def test_review_count_is_flagged():
    protection = {
        **PROTECTION_OK,
        "required_pull_request_reviews": {"required_approving_review_count": 2},
    }
    out = check_branch_settings(SLUG, gh_read=_settings(REPO_OK, protection))
    assert _ids(out) == ["sds.review-required"]


def test_zero_review_count_passes():
    protection = {
        **PROTECTION_OK,
        "required_pull_request_reviews": {"required_approving_review_count": 0},
    }
    assert check_branch_settings(SLUG, gh_read=_settings(REPO_OK, protection))["status"] == PASS


def test_checks_list_counts_as_a_required_check():
    protection = {
        "required_status_checks": {
            "strict": False,
            "contexts": [],
            "checks": [{"context": "Quality"}],
        }
    }
    assert check_branch_settings(SLUG, gh_read=_settings(REPO_OK, protection))["status"] == PASS


def test_unreadable_repo_is_unknown():
    out = check_branch_settings(SLUG, gh_read=_settings((None, "HTTP 500"), PROTECTION_OK))
    assert out["status"] == UNKNOWN
    assert _ids(out) == ["sds.settings-unreadable"]


def test_unreadable_protection_is_unknown():
    out = check_branch_settings(SLUG, gh_read=_settings(REPO_OK, (None, "HTTP 500")))
    assert out["status"] == UNKNOWN
    assert _ids(out) == ["sds.protection-unreadable"]


def test_plan_limited_protection_is_unknown():
    why = "gh: Upgrade to GitHub Pro or make this repository public (HTTP 403)"
    out = check_branch_settings(SLUG, gh_read=_settings(REPO_OK, (None, why)))
    assert out["status"] == UNKNOWN
    assert _ids(out) == ["sds.protection-unavailable"]


@pytest.mark.parametrize(
    "repo",
    [
        "[]",
        "not json",
        "null",
        {"default_branch": 7},
        {**REPO_OK, "allow_squash_merge": "true"},
        {**REPO_OK, "allow_auto_merge": 1},
        {**REPO_OK, "squash_merge_commit_message": 5},
    ],
)
def test_malformed_repo_body_is_unknown(repo):
    out = check_branch_settings(SLUG, gh_read=_settings(repo, PROTECTION_OK))
    assert out["status"] == UNKNOWN
    assert _ids(out) == ["sds.settings-unreadable"]


@pytest.mark.parametrize(
    "protection",
    [
        "[]",
        "not json",
        "null",
        {"required_status_checks": []},
        {"required_pull_request_reviews": "x"},
        {"required_pull_request_reviews": {"required_approving_review_count": "1"}},
        {"required_status_checks": {"strict": "true", "contexts": ["Quality"]}},
        {"required_status_checks": {"strict": 1, "contexts": ["Quality"]}},
        {"required_status_checks": {"contexts": "Quality"}},
        {"required_status_checks": {"contexts": ["Quality"], "checks": "x"}},
    ],
)
def test_malformed_protection_body_is_unknown(protection):
    out = check_branch_settings(SLUG, gh_read=_settings(REPO_OK, protection))
    assert out["status"] == UNKNOWN
    assert _ids(out) == ["sds.protection-unreadable"]


def test_absent_strict_passes():
    protection = {"required_status_checks": {"contexts": ["Quality"]}}
    assert check_branch_settings(SLUG, gh_read=_settings(REPO_OK, protection))["status"] == PASS


def test_protection_is_read_for_the_default_branch():
    requested = []

    def gh_read(args):
        requested.append(args[-1])
        if args[-1] == f"repos/{SLUG}":
            return json.dumps({**REPO_OK, "default_branch": "trunk"}), ""
        if args[-1] == f"repos/{SLUG}/branches/trunk/protection":
            return json.dumps(PROTECTION_OK), ""
        return None, "HTTP 500"

    assert check_branch_settings(SLUG, gh_read=gh_read)["status"] == PASS
    assert f"repos/{SLUG}/branches/trunk/protection" in requested


# --- behavior evidence ---------------------------------------------------

GOOD_EVIDENCE = (
    "serves_site = true\n"
    'baseline_commit = "aaa111"\n'
    'after_commit = "bbb222"\n'
    'pages = ["/", "/results"]\n'
    "unexplained_differences = []\n"
)


def _evidence(text, fail=()):
    files = {} if text is None else {(SLUG, EVIDENCE_PATH): text}
    return check_behavior_evidence(SLUG, gh_read=_serve(files, fail=fail))


def _edit(old, new):
    assert old in GOOD_EVIDENCE
    return GOOD_EVIDENCE.replace(old, new)


def test_good_evidence_passes():
    assert _evidence(GOOD_EVIDENCE)["status"] == PASS


def test_non_site_with_reason_passes():
    text = (
        "serves_site = false\n"
        'baseline_commit = "a"\nafter_commit = "b"\n'
        'reason = "a CLI, nothing to render"\n'
        "unexplained_differences = []\n"
    )
    assert _evidence(text)["status"] == PASS


def test_absent_evidence_is_violation():
    out = _evidence(None)
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.evidence-absent"]
    assert out["id"] == "sds.behavior_evidence"


def test_unreadable_evidence_is_unknown():
    out = _evidence(GOOD_EVIDENCE, fail=("contents",))
    assert out["status"] == UNKNOWN
    assert _ids(out) == ["sds.evidence-unreadable"]


def test_unparseable_evidence_is_malformed():
    out = _evidence("serves_site = [")
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.evidence-malformed"]


@pytest.mark.parametrize("key", ["serves_site", "baseline_commit", "after_commit"])
def test_missing_required_key_is_malformed_naming_it(key):
    text = "\n".join(line for line in GOOD_EVIDENCE.splitlines() if not line.startswith(key))
    out = _evidence(text)
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.evidence-malformed"]
    assert key in out["details"][0]["message"]


def test_missing_differences_key_is_malformed():
    out = _evidence(_edit("unexplained_differences = []\n", ""))
    assert _ids(out) == ["sds.evidence-malformed"]
    assert "unexplained_differences" in out["details"][0]["message"]


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("serves_site = true", 'serves_site = "true"', "serves_site"),
        ("serves_site = true", "serves_site = 1", "serves_site"),
        ('baseline_commit = "aaa111"', "baseline_commit = 7", "baseline_commit"),
        ('after_commit = "bbb222"', 'after_commit = ""', "after_commit"),
        ('after_commit = "bbb222"', 'after_commit = "  "', "after_commit"),
        ("unexplained_differences = []", 'unexplained_differences = "none"', "unexplained"),
        ('pages = ["/", "/results"]', 'pages = "/"', "pages"),
        ('pages = ["/", "/results"]', 'pages = ["/", 3]', "pages"),
        ('pages = ["/", "/results"]', 'pages = ["/", ""]', "pages"),
    ],
)
def test_wrongly_typed_field_is_malformed_naming_it(old, new, key):
    out = _evidence(_edit(old, new))
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.evidence-malformed"]
    assert key in out["details"][0]["message"]


def test_site_without_pages_is_malformed():
    out = _evidence(_edit('pages = ["/", "/results"]\n', ""))
    assert _ids(out) == ["sds.evidence-malformed"]
    assert "pages" in out["details"][0]["message"]


def test_site_with_empty_pages_is_malformed():
    out = _evidence(_edit('pages = ["/", "/results"]', "pages = []"))
    assert _ids(out) == ["sds.evidence-malformed"]


def test_non_site_needs_a_reason():
    text = (
        "serves_site = false\n"
        'baseline_commit = "a"\nafter_commit = "b"\n'
        "unexplained_differences = []\n"
    )
    out = _evidence(text)
    assert _ids(out) == ["sds.evidence-malformed"]
    assert "reason" in out["details"][0]["message"]


def test_non_site_blank_reason_is_malformed():
    text = (
        "serves_site = false\n"
        'baseline_commit = "a"\nafter_commit = "b"\nreason = " "\n'
        "unexplained_differences = []\n"
    )
    assert _ids(_evidence(text)) == ["sds.evidence-malformed"]


def test_each_problem_gets_its_own_detail():
    text = "serves_site = true\nbaseline_commit = 1\nunexplained_differences = []\n"
    out = _evidence(text)
    assert len(out["details"]) == 3  # baseline_commit, after_commit, pages
    assert {d["id"] for d in out["details"]} == {"sds.evidence-malformed"}


def test_unexplained_differences_are_a_violation_listing_them():
    out = _evidence(
        _edit("unexplained_differences = []", 'unexplained_differences = ["/results header"]')
    )
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.evidence-differences"]
    assert "/results header" in out["details"][0]["message"]


def test_differences_not_reported_when_file_is_malformed():
    text = _edit("unexplained_differences = []", 'unexplained_differences = ["x"]')
    text = text.replace('after_commit = "bbb222"', "after_commit = 3")
    assert _ids(_evidence(text)) == ["sds.evidence-malformed"]


# --- inert landing -------------------------------------------------------


@pytest.fixture
def brain_key(monkeypatch):
    monkeypatch.setenv(config.APP_BRAIN_KEY_ENV, "test-brain-key")


def _landing(answer):
    seen = []

    def fetch(slug):
        seen.append(slug)
        return answer

    return check_landing_inert(SLUG, fetch=fetch), seen


def test_inert_landing_passes(brain_key):
    out, seen = _landing({"landing": "inert"})
    assert out["status"] == PASS
    assert out["id"] == "sds.landing_inert"
    assert seen == [SLUG]


def test_unrecorded_landing_is_violation(brain_key):
    out, _ = _landing({"landing": "unknown", "reason": "not_assessed"})
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.landing-unrecorded"]


def test_redeploying_landing_is_violation(brain_key):
    out, _ = _landing({"landing": "redeploys"})
    assert out["status"] == VIOLATION
    assert _ids(out) == ["sds.refused-redeploys"]


@pytest.mark.parametrize(
    "answer", [None, {}, {"landing": "bogus"}, {"landing": ["inert"]}, {"landing": None}, "inert"]
)
def test_no_usable_answer_is_unknown(brain_key, answer):
    out, _ = _landing(answer)
    assert out["status"] == UNKNOWN
    assert _ids(out) == ["sds.landing-unreadable"]


def test_missing_read_key_is_unknown_and_never_fetches(monkeypatch):
    monkeypatch.delenv(config.APP_BRAIN_KEY_ENV, raising=False)
    out, seen = _landing({"landing": "inert"})
    assert out["status"] == UNKNOWN
    assert out["id"] == "sds.landing_inert"
    assert config.APP_BRAIN_KEY_ENV in out["details"][0]["message"]
    assert seen == []


def test_every_unknown_result_carries_a_fix(monkeypatch):
    monkeypatch.setenv(config.APP_BRAIN_KEY_ENV, "key")

    def unreadable(args):
        return None, "HTTP 500"

    def bad_shape(args):
        return '["not an object"]', ""

    results = [
        check_declaration(SLUG, gh_read=unreadable),
        check_cred_inventory(SLUG, gh_read=unreadable),
        check_branch_settings(SLUG, gh_read=unreadable),
        check_branch_settings(SLUG, gh_read=bad_shape),
        check_behavior_evidence(SLUG, gh_read=unreadable),
        check_landing_inert(SLUG, fetch=lambda slug: None),
    ]
    monkeypatch.delenv(config.APP_BRAIN_KEY_ENV)
    results.append(check_landing_inert(SLUG))
    assert [r["status"] for r in results] == [UNKNOWN] * len(results)
    assert all((r["fix"] or "").strip() for r in results)
    assert "credentials.env" in results[-1]["fix"]
