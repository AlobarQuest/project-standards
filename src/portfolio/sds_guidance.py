"""Who fixes each `portfolio sds-ready` check, and the words they act on.

Every check the command runs has an owner and three fields of prose, and the
build handoff and Devon's task list are rendered from them and nothing else:
improving an instruction means editing it here. Owners are fixed by the
onboarding design:

- `repository`: changes inside the target repository that need judgment. They
  go into the build handoff, read by an agent with no other context.
- `devon`: a decision or a GitHub settings page only Devon can act on. They go
  into his task list.
- `onboarding`: a deterministic step the onboarding procedure performs after
  Devon's yes. Before onboarding it is the plan, never a gap.

`why` is the reason the check exists, `done` the condition the check observes,
and `how` the steps, or the constraints where the fix needs judgment. The text
paraphrases the orchestrator's onboarding runbook
(`docs/operations/onboarding-a-target.md`) and must agree with each check's
own `fix` string.
"""

from dataclasses import dataclass

from .config import BACKLOG_AGE_DAYS
from .sds_checks import EVIDENCE_PATH
from .sds_decisions import FORMAT

OWNERS = ("repository", "devon", "onboarding")


@dataclass(frozen=True)
class Guidance:
    owner: str
    why: str
    done: str
    how: str


EXCLUDED = {
    "factory.pat_scope": "structurally unknown for a fine-grained token; step 6's probe tests it",
}

# Detail ids that mean "do not onboard this repository": a recorded choice, not
# a gap anyone can close.
REFUSAL_DETAIL_IDS = frozenset({"sds.refused-not-onboarding", "sds.refused-redeploys"})

_IDEMPOTENT = (
    " Do not do this by hand. Before onboarding, the readiness command lists this as a planned "
    "action, not a gap. If it fails after onboarding, rerun the onboarding procedure: every "
    "action is idempotent and a rerun resumes where the last run stopped."
)

ANTI_GOAL_1 = (
    "Readiness work breaks the functionality or appearance of a website the repository serves."
)

GUIDANCE: dict[str, Guidance] = {
    # -- repository: the build handoff --------------------------------------
    "git.current": Guidance(
        owner="repository",
        why=(
            "The readiness command measures the local checkout, so a checkout that is behind "
            "origin/main or carries uncommitted changes answers for code that is not on GitHub."
        ),
        done=(
            "After a fetch, HEAD equals origin/main and `git status --porcelain` prints nothing."
        ),
        how=(
            "Land your changes on main first, by push or by merged pull request, following the "
            "repository's branch protection. Then run "
            "`git -C <repo> checkout main && git -C <repo> pull --ff-only origin main`. Commit, "
            "stash or discard anything left in the working tree, and rerun the readiness command "
            "from that checkout. A feature branch never passes this check."
        ),
    ),
    "project.manifest": Guidance(
        owner="repository",
        why=(
            "`PROJECT.md` is the repository's portfolio manifest. The conformance kit, the "
            "nightly sweep and the factory read the repository's identity, standards pins and "
            "delivery profile from its frontmatter."
        ),
        done="`portfolio lint <repo>` reports no FAIL finding for `PROJECT.md`.",
        how=(
            "If `PROJECT.md` is missing, run `portfolio init` in the repository to scaffold it. "
            "Run `portfolio lint <repo>` and fix every FAIL it reports. Keep the existing "
            "`## Backlog` section; add backlog lines with `portfolio add`, not by hand."
        ),
    ),
    "code.onboarded": Guidance(
        owner="repository",
        why=(
            "The code standards reach a repository through `.code-standards.toml` and the "
            "vendored Quality workflow. Without them no linter, type check or test runs in CI, "
            "and the factory has no verifier to trust."
        ),
        done=(
            "`.code-standards.toml` and `.github/workflows/quality.yml` both exist at the "
            "repository root."
        ),
        how=(
            "Run `code-standards init` in the repository, then `code-standards sync`, which "
            "writes the Quality workflow and vendors `dependabot.yml`. Then make the code follow "
            "`~/Developer/code-standards/STANDARDS.md` until the Quality workflow's linters pass. "
            "Fix violations in the code; never add a suppression comment (`# noqa`, "
            "`# type: ignore`, `eslint-disable`) to make a linter quiet."
        ),
    ),
    "ci.executed": Guidance(
        owner="repository",
        why=(
            "SDS lands a change only when the repository's own tests pass, so those tests must "
            "run in CI. The vendored Quality workflow skips any tool it cannot find, so a green "
            "run can mean nothing ran at all."
        ),
        done=(
            "The latest Quality (`quality.yml`) run on main concluded `success`, and its job log "
            "shows `collected N items` or `N passed` with N greater than zero."
        ),
        how=(
            "For a Python repository, put the test runner and its plugins in a dependency group "
            "(`[dependency-groups].dev` in `pyproject.toml`), never in "
            "`[project.optional-dependencies]`: the workflow installs with `uv sync`, which "
            "installs dependency groups and skips optional extras. Run `uv lock` and commit the "
            "lockfile. For an npm repository, make `npm test` run the test suite and collect at "
            "least one test, make the Quality workflow run it, and make its output include an "
            "`N passed` summary line. If the repository has no tests, write tests that exercise "
            "what a change could break, without changing behavior. Push to main, wait for the "
            "Quality run to finish, and read its log for the test count; a green check alone "
            "proves nothing."
        ),
    ),
    "security.clean": Guidance(
        owner="repository",
        why=(
            "The factory gives an agent write access to the repository, so it must hold no "
            "leaked secret, and any Bitwarden Secrets Manager (BWS) secret it uses must be "
            "inventoried so a rotation reaches it."
        ),
        done=(
            "The security-standards scanner reports no BLOCK finding. If the repository "
            "references BWS secret UUIDs, `.bws-secrets.toml` also exists and security-standards' "
            "`governance-map.toml` has a `[[repo]]` entry for it."
        ),
        how=(
            "From the repository root run "
            '`PYTHONPATH="$HOME/Projects/security-standards/src" '
            "~/Projects/security-standards/.venv/bin/python -m security_scan.cli . "
            "--category security` and clear every BLOCK. Treat a token found in a tracked file "
            "or in git history as leaked: report it to Devon for rotation, because deleting it "
            "is not enough. If the repository uses BWS, generate the manifest with "
            "`security_scan.genmanifest <repo> --write` (same interpreter and PYTHONPATH) and add "
            "a `[[repo]]` consumer entry to security-standards' `governance-map.toml`, then run "
            "`make ownership` there. Never write a secret value into any file."
        ),
    ),
    "profile.declared": Guidance(
        owner="repository",
        why=(
            "The delivery profile tells the factory which kind of work, budgets and verifiers "
            "apply to the repository, and the kit measures factory checks only for a repository "
            "that declares one."
        ),
        done=(
            "`PROJECT.md` frontmatter declares `delivery_profile` with a value registered in "
            "intent-packages."
        ),
        how=(
            "Add `delivery_profile: <name>` to the `PROJECT.md` frontmatter. Choose the name from "
            "the registered profiles the check's failure lists; if none fits, stop and say so "
            "rather than inventing one."
        ),
    ),
    "deps.dependabot": Guidance(
        owner="repository",
        why=(
            "Dependabot's pull requests are the steady stream of small, inert changes the "
            "factory's landing lanes are built to take."
        ),
        done="`.github/dependabot.yml` exists.",
        how=(
            "Run `code-standards sync` in the repository; it vendors a `dependabot.yml` that "
            "matches the repository's tooling. Commit it unchanged."
        ),
    ),
    "backlog.hygiene": Guidance(
        owner="repository",
        why=(
            "An aged backlog item is either done, dropped or still wanted, and leaving it open "
            "makes the repository's stated pending work untrustworthy."
        ),
        done=(
            f"No backlog item in `PROJECT.md` is older than {BACKLOG_AGE_DAYS} days by its "
            "`added` date."
        ),
        how=(
            "For each aged item `portfolio lint <repo>` lists, check the code. If the work is "
            "done, remove the line and name the item in your final report; a ticked item still "
            "counts as aged. Otherwise leave it and list it in your final report for Devon to "
            "keep, re-scope or drop. Never re-date an item, and never remove one whose work is "
            "not done."
        ),
    ),
    "standards.pinned": Guidance(
        owner="repository",
        why=(
            "The `applicable_standards` pins say which version of each standard the repository "
            "was last brought up to; a stale pin means the repository has not been checked "
            "against the current rules."
        ),
        done=(
            "The `project`, `code` and `security` pins in `PROJECT.md`'s `applicable_standards` "
            "each equal that standard's current `STANDARD_VERSION`."
        ),
        how=(
            "The current version of each standard is the `STANDARD_VERSION` file in its "
            "checkout: `~/Projects/project-standards` (project), `~/Developer/code-standards` "
            "(code) and `~/Projects/security-standards` (security). For each drifted standard, "
            "read what changed between the pinned and current version in that checkout's git "
            "history, apply it to the repository, then set the pin to the current "
            "version. Never raise a pin without applying what changed."
        ),
    ),
    "sds.behavior_evidence": Guidance(
        owner="repository",
        why=(
            "Readiness work must not change what the repository serves. The readiness command "
            "cannot judge screenshots, so the evidence file makes the before-and-after "
            "comparison reviewable."
        ),
        done=(
            f"`{EVIDENCE_PATH}` exists on the default branch, follows the format below, and its "
            "`unexplained_differences` list is empty."
        ),
        how=(
            f"Anti-goal 1, a hard constraint: {ANTI_GOAL_1} If that happens, the process has "
            "failed even if every check passes. "
            "Capture a baseline before you change anything: build and run the repository "
            "locally at the commit you start from, take screenshots of the site's key pages at "
            "desktop and phone widths, and record the responses of its API routes and its "
            "health endpoint. "
            "After your changes, capture the same pages, widths and responses from a local build "
            "of your branch. Never deploy anything to capture either set. "
            "Commit the captures under `docs/sds-readiness/`, and compare each pair. "
            f"Write `{EVIDENCE_PATH}` with these keys: `serves_site` (true or false), "
            "`baseline_commit` and `after_commit` (the two commit shas), "
            "`unexplained_differences` (a list of strings), and either `pages` (a non-empty list "
            "of the pages you captured, when `serves_site` is true) or `reason` (why the "
            "repository serves no site, when it is false). "
            "Treat any visible or behavioral difference as a failure unless the handoff named it "
            "as intended: list every other difference in `unexplained_differences` and fix it, "
            "so the list is empty when you finish. Do not add intended differences to that list."
        ),
    ),
    # -- devon: the task list -----------------------------------------------
    "sds.decisions": Guidance(
        owner="devon",
        why=(
            "Two calls only Devon can make: whether the repository becomes a factory target at "
            "all, and whether landing on its default branch redeploys anything. Nothing "
            "proceeds on a guess, and a missing answer never reads as consent."
        ),
        done=(
            "The decisions file records `onboard = true` with a non-empty `onboard_reason`, and "
            '`landing = "inert"`.'
        ),
        how=(
            "Write `<portfolio home, default ~/.portfolio>/onboarding/<repository name>/"
            "decisions.toml` in this format:\n"
            f"{FORMAT}\n"
            "Decide the landing answer by reading all three ways a landing can redeploy: the "
            "repository's workflow steps, its webhooks, and the hosting platform's git "
            "integration. Checking one of them fails open. `onboard = false` or "
            '`landing = "redeploys"` is a refusal: the repository is not onboarded.'
        ),
    ),
    "factory.pat_access": Guidance(
        owner="devon",
        why=(
            "`FACTORY_PR_TOKEN` is a fine-grained personal access token with an explicit "
            "repository list. Setting the Actions secret copies a token that cannot reach a "
            "repository missing from that list, and the first run fails at `actions/checkout` "
            "with a 403."
        ),
        done=(
            "Read with the token, `GET /repos/<owner>/<repo>` reports `permissions.push: true`. "
            "A 200 alone is not enough, because any valid token can read a public repository."
        ),
        how=(
            "On GitHub, signed in as the account that owns the token, open Settings, Developer "
            "settings, Personal access tokens, Fine-grained tokens, and open the token behind "
            "`FACTORY_PR_TOKEN` (BWS `a3240c2e-92d7-4b32-a726-b49b0135565a`). Under Repository "
            "access, add this repository to the selected repositories. Under Repository "
            "permissions, confirm Contents and Workflows are Read and write; without Workflows, "
            "a push that touches `.github/workflows/**` is rejected. Save. No API extends the "
            "list. Rerun the readiness command to confirm; the caller probe (runbook step 6) is "
            "the final proof."
        ),
    ),
    "factory.app_access": Guidance(
        owner="devon",
        why=(
            "The Alobar SDS Dispatch GitHub App starts the factory run, reads the named check and "
            "merges the pull request. If its installation does not reach the repository, or "
            "lacks a permission, each of those fails."
        ),
        done=(
            "The installation is not suspended, covers this repository (all repositories, or a "
            "selected list that names it), and holds at least actions, contents, pull_requests "
            "and workflows write, and metadata read."
        ),
        how=(
            "The installation normally covers every repository, so this is usually already "
            "done. If the check reports the repository not granted, open the account's GitHub "
            "Settings, Applications, Installed GitHub Apps, configure Alobar SDS Dispatch, and "
            "add the repository under Repository access. If it reports the installation "
            "suspended, un-suspend it on the same page. If a permission is below what is needed, "
            "raise it in the App's settings and accept the new permissions on the installation. "
            "No API does any of these. Read the App's permissions from a token mint response, "
            "never from `/app`."
        ),
    ),
    # -- onboarding: the planned actions ------------------------------------
    "sds.declaration": Guidance(
        owner="onboarding",
        why=(
            "A repository is a factory target only by its own declaration. Admission reads "
            "`factory-target.toml` from the default branch on GitHub and refuses a repository "
            "that does not declare itself."
        ),
        done=(
            "`factory-target.toml` on the default branch, read from GitHub, parses and declares "
            "`factory_target = true` with a non-empty `factory_target_reason`."
        ),
        how=(
            "The onboarding procedure commits `factory-target.toml` with the reason Devon "
            "recorded as `onboard_reason` (action 1, runbook step 1)." + _IDEMPOTENT
        ),
    ),
    "runner.caller": Guidance(
        owner="onboarding",
        why=(
            "Dispatch starts a run through the caller workflow. A caller pinned to anything but "
            "factory-runner's recommended pin, or missing the secrets the reusable workflow "
            "needs, first shows up as a failed dispatch."
        ),
        done=(
            "`.github/workflows/factory-runner-pilot.yml` exists, its `uses:` is pinned to the "
            "full sha in factory-runner's `RECOMMENDED_CALLER_PIN`, and every secret the "
            "reusable workflow requires is set on the repository."
        ),
        how=(
            "The onboarding procedure commits the caller from project-standards' "
            "`src/portfolio/templates/factory-runner-caller.yml`, pinned to "
            "`RECOMMENDED_CALLER_PIN` and never `@main`, with `work_unit_id` as its only input "
            "(action 1, runbook step 2). It sets the secrets in action 3 (runbook step 3)."
            + _IDEMPOTENT
        ),
    ),
    "sds.cred_inventory": Guidance(
        owner="onboarding",
        why=(
            "Actions secrets are write-only copies. A rotation reaches a copy only if the "
            "rotation inventory lists it, so an unlisted copy keeps the old value and breaks "
            "the next run after a rotation."
        ),
        done=(
            "The orchestrator's `.cred-consumers.toml` lists this repository's "
            "`FACTORY_RUNNER_TOKEN` as a `gh-actions-secret` consumer of "
            "`orchestrator-factory-runner-bearer`, and factory-runner's lists its "
            "`FACTORY_PR_TOKEN` under `factory-pr-token`."
        ),
        how=(
            "The onboarding procedure adds both consumer entries (action 2, runbook step 3)."
            + _IDEMPOTENT
        ),
    ),
    "factory.secrets": Guidance(
        owner="onboarding",
        why=(
            "The reusable workflow refuses to run without its secrets, and a dispatch to a "
            "repository missing one fails before any work starts."
        ),
        done=(
            "Every secret factory-runner's workflow requires at its declared pin is set on the "
            "repository, by name: `FACTORY_RUNNER_TOKEN`, `FACTORY_RUNNER_CREDENTIAL_KEY_ID`, "
            "`ANTHROPIC_API_KEY` and `FACTORY_PR_TOKEN` at the time of writing."
        ),
        how=(
            "The onboarding procedure sets each secret from its source, fetching and setting it "
            "in one process so no value enters a prompt, a tool argument or a log (action 3, "
            "runbook step 3): `FACTORY_RUNNER_TOKEN` from BWS "
            "`d2a4c0fc-128b-4bf5-8e25-b481010e1be0`, `ANTHROPIC_API_KEY` from BWS "
            "`b56cf0df-27bc-46a8-8e94-b48201478aff`, `FACTORY_PR_TOKEN` from BWS "
            "`a3240c2e-92d7-4b32-a726-b49b0135565a`, and `FACTORY_RUNNER_CREDENTIAL_KEY_ID` "
            "from factory-runner's `docs/rollout.md`." + _IDEMPOTENT
        ),
    ),
    "factory.landing_known": Guidance(
        owner="onboarding",
        why=(
            "Admission and the landing lane both ask App Brain what landing on the default "
            "branch does. Without an answer, admission refuses the unit and the lane refuses to "
            "merge its pull request."
        ),
        done=(
            "App Brain's default-branch-landing answer for the repository is `inert` or "
            "`redeploys`, not `unknown`."
        ),
        how=(
            "The onboarding procedure records Devon's `landing` decision in App Brain with "
            "`record_default_branch_landing` (action 4, runbook step 7). App Brain also needs an "
            "app record for the repository." + _IDEMPOTENT
        ),
    ),
    "sds.landing_inert": Guidance(
        owner="onboarding",
        why=(
            "This process onboards only inert repositories. A repository whose landing "
            "redeploys needs a change-manager deploy policy and change windows, which are out "
            "of scope."
        ),
        done="App Brain's default-branch-landing answer for the repository is `inert`.",
        how=(
            "The onboarding procedure records the answer from Devon's decision (action 4, "
            "runbook step 7)." + _IDEMPOTENT + " A recorded `redeploys` is a refusal, not a "
            "gap, and a rerun does not change it: choose a repository whose landing is inert."
        ),
    ),
    "repo.protection": Guidance(
        owner="onboarding",
        why=(
            "The landing lane merges through branch protection, and auto-merge with no required "
            "check merges a pull request instantly."
        ),
        done=(
            "The main branch has branch protection. A plan that does not offer protection on a "
            "private repository is not done."
        ),
        how=(
            "The readiness command never writes settings. The onboarding procedure applies "
            "branch protection with the settings `sds.branch_settings` lists, then reads them "
            "back (action 5, runbook step 9). It never sets a required review count: a solo "
            "account cannot approve its own pull requests." + _IDEMPOTENT
        ),
    ),
    "sds.branch_settings": Guidance(
        owner="onboarding",
        why=(
            "The landing lane squash-merges and depends on factory-runner's `SDS-Unit:` trailer "
            "surviving the merge. Nothing else in the code checks these settings, so a wrong "
            "one fails at the first landing."
        ),
        done=(
            "Squash merging is allowed, `squash_merge_commit_message` is `COMMIT_MESSAGES`, "
            "auto-merge is on, and the default branch's protection requires at least one status "
            "check, is not strict, and requires no approving review."
        ),
        how=(
            "The readiness command never writes settings. The onboarding procedure applies them "
            "and reads each back (action 5, runbook step 9): at least one required status check "
            "named by its job name and verified against a real open pull request, "
            "`strict: false`, no required review count, squash merging allowed, "
            "`squash_merge_commit_message` set to `COMMIT_MESSAGES`, and `allow_auto_merge: "
            "true` enabled only after the required checks read back." + _IDEMPOTENT
        ),
    ),
}
