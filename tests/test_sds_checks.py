import base64
import json

from portfolio.matrix import PASS, UNKNOWN, VIOLATION
from portfolio.sds_checks import check_cred_inventory, check_declaration

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
