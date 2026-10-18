"""Checks `portfolio sds-ready` makes beyond the shared onboarding set.

Each returns the kit's `_result` shape. A remote read that fails is `unknown`,
never a pass and never a defect in the repository: the operator's environment
being wrong says nothing about the repository.
"""

import tomllib

from .factory_target import FactoryTargetError, parse_declaration
from .matrix import PASS, UNKNOWN, VIOLATION
from .onboard_checks import _gh_read, _remote_contents, _result

DECLARATION_CHECK = "sds.declaration"
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
