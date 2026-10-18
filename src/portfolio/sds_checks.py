"""Checks `portfolio sds-ready` makes beyond the shared onboarding set.

Each returns the kit's `_result` shape. A remote read that fails is `unknown`,
never a pass and never a defect in the repository: the operator's environment
being wrong says nothing about the repository.
"""

import json
import tomllib

from .factory_target import FactoryTargetError, parse_declaration
from .matrix import PASS, UNKNOWN, VIOLATION
from .onboard_checks import (
    _PROTECTION_PLAN_LIMITED,
    _PROTECTION_UNSET,
    _gh_read,
    _remote_contents,
    _result,
)

DECLARATION_CHECK = "sds.declaration"
BRANCH_SETTINGS_CHECK = "sds.branch_settings"
INVENTORY_CHECK = "sds.cred_inventory"
INVENTORY_FILE = ".cred-consumers.toml"
DECLARATION_FILE = "factory-target.toml"

# (inventory repository, credential id, Actions secret name) -- one entry per
# credential a factory target must hold a copy of.
INVENTORIES = (
    ("AlobarQuest/orchestrator", "orchestrator-factory-runner-bearer", "FACTORY_RUNNER_TOKEN"),
    ("AlobarQuest/factory-runner", "factory-pr-token", "FACTORY_PR_TOKEN"),
)


def _detail(detail_id: str, message: str) -> dict:
    return {"id": detail_id, "message": message}


def check_declaration(slug: str, gh_read=_gh_read) -> dict:
    """Does the default branch declare `factory_target = true`?"""
    text, why = _remote_contents(slug, DECLARATION_FILE, gh_read)
    if why is not None:
        return _result(
            DECLARATION_CHECK,
            UNKNOWN,
            details=[
                _detail(
                    "sds.declaration-unreadable", f"{DECLARATION_FILE} could not be read: {why}"
                )
            ],
        )
    fix = (
        f"declare `factory_target = true` and a reason in {DECLARATION_FILE} on the default branch"
    )
    if text is None:
        return _result(
            DECLARATION_CHECK,
            VIOLATION,
            details=[_detail("sds.declaration-absent", f"{DECLARATION_FILE} is absent")],
            fix=fix,
        )
    try:
        target, _reason = parse_declaration(text)
    except FactoryTargetError as error:
        return _result(
            DECLARATION_CHECK,
            VIOLATION,
            details=[_detail("sds.declaration-malformed", str(error))],
            fix=fix,
        )
    if not target:
        return _result(
            DECLARATION_CHECK,
            VIOLATION,
            details=[_detail("sds.declaration-false", "factory_target = false")],
            fix=fix,
        )
    return _result(DECLARATION_CHECK, PASS)


def _holds_consumer(inventory: dict, credential_id: str, secret: str, slug: str) -> bool:
    for credential in inventory.get("credential", []):
        if credential.get("id") != credential_id:
            continue
        for consumer in credential.get("consumer", []):
            if (
                consumer.get("kind") == "gh-actions-secret"
                and consumer.get("name") == secret
                and str(consumer.get("repo", "")).lower() == slug.lower()
            ):
                return True
    return False


def check_cred_inventory(slug: str, gh_read=_gh_read) -> dict:
    """Do both rotation inventories list this repository's Actions secret copies?"""
    missing = []
    for inventory_repo, credential_id, secret in INVENTORIES:
        text, why = _remote_contents(inventory_repo, INVENTORY_FILE, gh_read)
        parsed = None
        if text is not None:
            try:
                parsed = tomllib.loads(text)
            except (tomllib.TOMLDecodeError, RecursionError) as error:
                why = f"does not parse: {error}"
        if parsed is None:
            return _result(
                INVENTORY_CHECK,
                UNKNOWN,
                details=[
                    _detail(
                        "sds.inventory-unreadable",
                        f"{inventory_repo} {INVENTORY_FILE} could not be read: "
                        f"{why or 'file absent'}",
                    )
                ],
            )
        if not _holds_consumer(parsed, credential_id, secret, slug):
            missing.append(
                _detail(
                    f"sds.inventory-missing-{credential_id}",
                    f"{inventory_repo} {INVENTORY_FILE} lists no gh-actions-secret "
                    f"{secret} consumer for this repository under {credential_id}",
                )
            )
    if missing:
        return _result(
            INVENTORY_CHECK,
            VIOLATION,
            details=missing,
            fix="add the missing gh-actions-secret consumers to the named inventories",
        )
    return _result(INVENTORY_CHECK, PASS)


def _read_object(endpoint: str, gh_read) -> tuple[dict | None, str]:
    """GET `endpoint` as a JSON object, or (None, why it could not be read)."""
    text, why = gh_read(["api", endpoint])
    if text is None:
        return None, why or "the read failed"
    try:
        body = json.loads(text)
    except json.JSONDecodeError, RecursionError:
        return None, "the response is not JSON"
    if not isinstance(body, dict):
        return None, "the response is not a JSON object"
    return body, ""


class _Unreadable(Exception):
    """A response had a shape the check cannot judge."""


def _branch_unknown(detail_id: str, message: str) -> dict:
    return _result(BRANCH_SETTINGS_CHECK, UNKNOWN, details=[_detail(detail_id, message)])


def _typed(body: dict, field: str, kind: type):
    """`body[field]` when it is a `kind`, None when absent or null; anything else is unjudgeable."""
    value = body.get(field)
    if value is not None and not isinstance(value, kind):
        raise _Unreadable(f"{field} is not a {kind.__name__}")
    return value


def _merge_details(repo: dict) -> tuple[list[dict], bool]:
    squash = _typed(repo, "allow_squash_merge", bool)
    message = _typed(repo, "squash_merge_commit_message", str)
    auto = _typed(repo, "allow_auto_merge", bool)
    details = []
    if squash is not True:
        details.append(_detail("sds.squash-disallowed", "squash merging is not allowed"))
    if message != "COMMIT_MESSAGES":
        details.append(
            _detail(
                "sds.squash-message",
                "squash_merge_commit_message is not COMMIT_MESSAGES "
                "(the landing trailer depends on it)",
            )
        )
    return details, auto is not True


def _protection_details(protection: dict, branch: str) -> list[dict]:
    checks = _typed(protection, "required_status_checks", dict) or {}
    reviews = _typed(protection, "required_pull_request_reviews", dict) or {}
    count = reviews.get("required_approving_review_count", 0)
    if isinstance(count, bool) or not isinstance(count, int):
        raise _Unreadable("required_approving_review_count is not an integer")
    strict = _typed(checks, "strict", bool)
    contexts = _typed(checks, "contexts", list)
    named_checks = _typed(checks, "checks", list)
    required = contexts or named_checks
    details = []
    if not required:
        details.append(_detail("sds.no-required-check", f"{branch} requires no status check"))
    if strict is True:
        details.append(
            _detail("sds.strict", "required status checks are strict (up-to-date branch)")
        )
    if count > 0:
        details.append(
            _detail("sds.review-required", f"{branch} requires {count} approving review(s)")
        )
    return details


def check_branch_settings(slug: str, gh_read=_gh_read) -> dict:
    """Merge settings and default-branch protection a factory target needs.

    Reads only. The rationale for each setting is step 9 of the orchestrator's
    onboarding runbook; the review count is flagged but never recommended.
    """
    repo, why = _read_object(f"repos/{slug}", gh_read)
    if repo is None:
        return _branch_unknown("sds.settings-unreadable", f"repos/{slug} could not be read: {why}")
    branch = repo.get("default_branch")
    if not isinstance(branch, str) or not branch:
        return _branch_unknown(
            "sds.settings-unreadable", f"repos/{slug} names no readable default_branch"
        )

    try:
        details, auto_merge_off = _merge_details(repo)
    except _Unreadable as error:
        return _branch_unknown("sds.settings-unreadable", str(error))
    protection, why = _read_object(f"repos/{slug}/branches/{branch}/protection", gh_read)
    if protection is not None:
        try:
            details += _protection_details(protection, branch)
        except _Unreadable as error:
            return _branch_unknown("sds.protection-unreadable", str(error))
    elif _PROTECTION_PLAN_LIMITED in why.lower():
        return _branch_unknown(
            "sds.protection-unavailable",
            f"branch protection is not available for {slug} on its plan",
        )
    elif _PROTECTION_UNSET in why.lower():
        details.append(_detail("sds.no-protection", f"{branch} has no branch protection"))
    else:
        return _branch_unknown(
            "sds.protection-unreadable", f"{branch} protection could not be read: {why}"
        )

    if auto_merge_off:
        details.append(_detail("sds.auto-merge-off", "auto-merge is not enabled"))
    if details:
        return _result(
            BRANCH_SETTINGS_CHECK,
            VIOLATION,
            details=details,
            fix=(
                "set the merge and branch-protection settings in step 9 of the orchestrator "
                "runbook, docs/operations/onboarding-a-target.md "
                f"(repos/{slug}; Devon runs this, the kit never writes settings)"
            ),
        )
    return _result(BRANCH_SETTINGS_CHECK, PASS)
