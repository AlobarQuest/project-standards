"""Q2 — can the factory actually WORK in this repository?

A repository DECLARES whether it wants to be a factory target (Q1, ADR-0015);
the estate MEASURES whether the factory can work there (Q2, this module).
Dispatch permission is eventually derived from both, and Q2 comes first because
a derivation is worthless while Q2 lies -- and it did lie. Every check here
exists because it caused a measured failure while the kit reported the
repository ready:

- `factory.pat_access`  2026-08-07: caller present, four secrets set, allowlist
  entry present, and the probe run died in 35 seconds at `actions/checkout`
  with a 403. `FACTORY_PR_TOKEN` is a FINE-GRAINED PAT with an explicit
  repository list, and setting the secret in a repository does not add it.
- `factory.pat_scope`   2026-08-03: two work units died AFTER coding and
  verification succeeded, because a push touching `.github/workflows/**` needs
  the Workflows permission and the rejection arrives only at the final push.
- `factory.secrets`     the four Actions secrets, by name. PRESENCE IS NOT
  SUFFICIENCY -- `factory.pat_access` exists precisely because a present secret
  can hold a token that cannot reach the repository.
- `factory.landing_known` 2026-08-09: `security-standards` was a factory target
  that App Brain had never assessed, and the refusal surfaced only in a dry run.

**Green does not mean dispatchable.** A repository passing all of these is
proven not to fail in the ways this estate has already failed. It is not proven
to work.

**Credentials come from the ENVIRONMENT and nowhere else** (see `config`).
Absent means `unknown` with a named reason -- exactly how `repo.protection`
behaves when GitHub refuses. An unmeasured capability is not a demonstrated
one, so the fail-open of reporting `pass` without the credential is the one
outcome this module must never produce.

The fifth Q2 check, `runner.caller`, lives in `onboard_checks` because it was
already built there; this module owns the four new ones plus the scope
predicate they share.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import config
from .checkers import _run
from .manifest import read_manifest
from .matrix import NA, PASS, UNKNOWN, VIOLATION
from .onboard_checks import (
    _gh,
    _result,
    check_runner_caller,
    declared_pin,
    repo_slug,
    required_secrets,
)

FACTORY_CHECKS = (
    "factory.pat_access",
    "factory.pat_scope",
    "factory.secrets",
    "factory.landing_known",
)

# App Brain's answer vocabulary, mirrored from AlobarQuest/brain
# `src/brains/app/models.py` and served by GET /api/apps/default-branch-landing.
# Nothing is added to it here: a value invented on this side would be a second
# copy of a vocabulary that already lives somewhere else.
LANDING_REDEPLOYS = "redeploys"
LANDING_INERT = "inert"
LANDING_UNKNOWN = "unknown"
_LANDING_ROUTE = "/api/apps/default-branch-landing"
_USER_AGENT = "project-standards-conformance-kit/1 (+AlobarQuest/project-standards)"

_NOT_IN_SCOPE = (
    "not measured: this repository declares no delivery_profile, so it is outside "
    "the Q2 sweep's scope"
)
_GREEN_MEANS = (
    "green here means the repository does not fail in a way this estate has "
    "already failed -- it is not proof that a dispatch would work"
)


def in_q2_scope(repo) -> bool:
    """Whether the Q2 capability checks are measured for this repository.

    **`delivery_profile` is an INTERIM PROXY for Q1's declaration, not Q1.**
    Q1's explicit key is a later increment and scoping on it now would make this
    one depend on unbuilt work; ADR-0015 itself puts the declaration "alongside
    `delivery_profile:`, which the kit already reads". The proxy is imperfect in
    a way worth knowing rather than hiding: measured 2026-08-17, `orchestrator`
    declares a profile and is not in the dispatch allowlist, while
    `project-standards` was allowlisted and declares none. Measuring
    `orchestrator` is harmless and informative; that disagreement is Q1's to
    resolve.

    Scoping is the point rather than an optimisation. Running Q2 against a
    repository that does not want to be a target produces failures that are
    decisions -- the exact noise ADR-0015 identified.
    """
    m = read_manifest(repo)
    if m is None or "_yaml_error" in m.frontmatter:
        return False
    profile = m.frontmatter.get("delivery_profile")
    return isinstance(profile, str) and bool(profile.strip())


def _out_of_scope(check_id: str) -> dict:
    return _result(
        check_id,
        NA,
        details=[{"id": f"{check_id}.out-of-scope", "message": _NOT_IN_SCOPE}],
        fix=(
            "declare `delivery_profile: <name>` in PROJECT.md frontmatter if this "
            "repository is meant to be a factory target"
        ),
    )


def _credential_absent(check_id: str, env_name: str, purpose: str) -> dict:
    """An absent credential is UNKNOWN -- never pass, never violation.

    This is the fail-open that would make the whole check set decorative, so it
    is one function with one caller-visible shape rather than four hand-written
    branches.
    """
    return _result(
        check_id,
        UNKNOWN,
        details=[
            {
                "id": f"{check_id}.credential-absent",
                "message": f"${env_name} is not set, so {purpose} was not measured",
            }
        ],
        fix=(
            f"export {env_name} before running (the kit reads credentials from the "
            "environment and never fetches them); integrations/portfolio-scan.sh "
            "supplies both for the nightly sweep"
        ),
    )


def _token_gh_read(token: str):
    """A `gh` reader authenticated AS THE PAT, returning (stdout|None, why).

    `GH_TOKEN` takes precedence over gh's stored credentials, and `GITHUB_TOKEN`
    is popped so an ambient one cannot answer in the PAT's place -- which would
    turn "the PAT can reach this" into "somebody can reach this", the exact
    question the 2026-08-07 failure proved is different. The token never reaches
    argv (it would be visible in `ps`) and never reaches a result's details.
    """

    def gh_read(args: list[str]) -> tuple[str | None, str]:
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        env["GH_TOKEN"] = token
        result = _run(["gh", *args], env=env)
        if result is None:
            return None, ""
        if result.returncode != 0:
            return None, f"{result.stdout}{result.stderr}"
        return result.stdout, ""

    return gh_read


def check_pat_access(repo, slug: str, token: str | None = None, gh_read=None) -> dict:
    """Can `FACTORY_PR_TOKEN` reach this repository, with WRITE access?

    **A 200 is not the answer, and taking it as one is fail-open.** Measured
    2026-08-17: `GET /repos/anthropics/anthropic-sdk-python` answers 200 under
    this PAT with `permissions.push: false`, because a PUBLIC repository is
    readable by any valid token whether or not it is in the fine-grained access
    list. Two of the estate's factory-adjacent repositories are public, so the
    status-only probe the spec prescribed would have certified them on a token
    that cannot push. The answer is `permissions.push`.

    A 404 is the repository being outside the token's list (GitHub hides rather
    than 403s), which is a real Q2 violation. `Bad credentials` is a problem
    with the credential rather than a defect in the repository, so it is
    UNKNOWN: this check must never report a repository defective because the
    operator's environment was wrong.
    """
    check_id = "factory.pat_access"
    if not in_q2_scope(repo):
        return _out_of_scope(check_id)
    token = token if token is not None else config.factory_pat()
    if not token:
        return _credential_absent(
            check_id, config.FACTORY_PAT_ENV, "the token's access to this repository"
        )
    gh_read = gh_read or _token_gh_read(token)
    raw, diagnostic = gh_read(["api", f"repos/{slug}"])
    if raw is None:
        lowered = diagnostic.lower()
        if "bad credentials" in lowered or "http 401" in lowered:
            return _result(
                check_id,
                UNKNOWN,
                details=[
                    {
                        "id": "factory.pat-rejected",
                        "message": (
                            f"GitHub rejected ${config.FACTORY_PAT_ENV} itself, so this "
                            "repository's access was not measured"
                        ),
                    }
                ],
                fix=(
                    f"the value in ${config.FACTORY_PAT_ENV} is not a valid token "
                    "(expired or wrong secret); refresh it and re-run"
                ),
            )
        if "not found" in lowered or "http 404" in lowered:
            return _result(
                check_id,
                VIOLATION,
                details=[
                    {
                        "id": "factory.pat-no-access",
                        "message": (
                            f"{config.FACTORY_PAT_ENV} cannot reach {slug} (GitHub answers "
                            "404, which is how a fine-grained PAT reports a repository "
                            "outside its access list)"
                        ),
                    }
                ],
                fix=(
                    f"add {slug} to {config.FACTORY_PAT_ENV}'s repository access list on the "
                    "account that owns the PAT. This is a settings-page operation; no API "
                    "extends the list, and setting the Actions secret in the repository does "
                    "not grant access to it"
                ),
            )
        return _result(
            check_id,
            UNKNOWN,
            details=[
                {
                    "id": "factory.pat-probe-failed",
                    "message": "could not probe repository access: "
                    + (diagnostic.strip()[:200] or "no output"),
                }
            ],
            fix=f"check network and `gh` availability, then re-run; repos/{slug} was not readable",
        )
    try:
        body = json.loads(raw)
        push = body["permissions"]["push"]
    except (ValueError, TypeError, KeyError):
        return _result(
            check_id,
            UNKNOWN,
            details=[
                {
                    "id": "factory.pat-permissions-unreadable",
                    "message": "the repository response carried no readable permissions object",
                }
            ],
            fix=f"inspect `gh api repos/{slug}` by hand; the permissions field was missing",
        )
    if push is not True:
        return _result(
            check_id,
            VIOLATION,
            details=[
                {
                    "id": "factory.pat-read-only",
                    "message": (
                        f"{config.FACTORY_PAT_ENV} can see {slug} but has no write access "
                        "(permissions.push is not true) -- for a public repository a 200 "
                        "proves only that the repository is public"
                    ),
                }
            ],
            fix=(
                f"grant {config.FACTORY_PAT_ENV} write access to {slug} on the account that "
                "owns the PAT (settings page; no API does this)"
            ),
        )
    return _result(
        check_id,
        PASS,
        details=[
            {
                "id": "factory.pat-can-write",
                "message": f"{config.FACTORY_PAT_ENV} has write access to {slug}; {_GREEN_MEANS}",
            }
        ],
    )


def check_pat_scope(repo, token: str | None = None) -> dict:
    """May `FACTORY_PR_TOKEN` push a commit touching `.github/workflows/**`?

    **This check is ALWAYS `unknown`, and saying so is the point.** There is no
    read-only way to establish it: Actions secrets are write-only so nothing can
    confirm which token a repository holds; a fine-grained PAT reports no
    `x-oauth-scopes` header (that is classic-token-only); and no API exposes a
    fine-grained PAT's permission set. The only demonstration is a push that
    touches a workflow file, which mutates -- and the kit never mutates.

    It is here rather than omitted because the failure it names is expensive and
    silent: the rejection arrives at the final push, after coding and
    verification have already succeeded, which cost two work units on
    2026-08-03. A named `unknown` is worse than a measurement and better than
    the silence this had before.

    The two unknowns are deliberately different. Without the credential nothing
    was attempted; with it, the capability is unobservable in principle. Only
    the second is a statement about GitHub.
    """
    check_id = "factory.pat_scope"
    if not in_q2_scope(repo):
        return _out_of_scope(check_id)
    token = token if token is not None else config.factory_pat()
    if not token:
        return _credential_absent(
            check_id, config.FACTORY_PAT_ENV, "the token's workflow-push permission"
        )
    return _result(
        check_id,
        UNKNOWN,
        details=[
            {
                "id": "factory.pat-scope-unobservable",
                "message": (
                    "not establishable read-only: a fine-grained PAT reports no "
                    "x-oauth-scopes header and no API exposes its permission set, so "
                    "whether it may push a commit touching .github/workflows/** is "
                    "unknown until a push is attempted"
                ),
            }
        ],
        fix=(
            "confirm Workflows: Read-and-write on the PAT's settings page, or prove it "
            "with a throwaway branch workflow that pushes a commit touching "
            ".github/workflows/** using the secret. Every caller-pin remediation edits "
            "exactly such a file, so a token without it fails at the final push"
        ),
    )


def check_secrets(repo, slug: str, gh=_gh) -> dict:
    """The Actions secrets the reusable workflow requires, present BY NAME.

    The required set is read from factory-runner's workflow AT ITS DECLARED PIN,
    never hard-coded -- the stale documentation template passed 2 of 4. Values
    are write-only and are never read.

    This overlaps `runner.caller`'s last step deliberately. That check reaches
    the secrets only after the caller exists and is correctly pinned, so a
    repository with a stale pin hides its missing secrets behind the pin
    violation; this one answers independently.

    **Presence is not sufficiency.** `factory.pat_access` exists because a
    present `FACTORY_PR_TOKEN` can hold a token that cannot reach the
    repository, and nothing here can see a secret's value.
    """
    check_id = "factory.secrets"
    if not in_q2_scope(repo):
        return _out_of_scope(check_id)
    pin = declared_pin(gh=gh)
    if pin is None:
        return _result(
            check_id,
            UNKNOWN,
            details=[
                {
                    "id": "factory.secrets-pin-unreachable",
                    "message": (
                        "cannot read factory-runner's RECOMMENDED_CALLER_PIN, so the "
                        "required secret names are unknown"
                    ),
                }
            ],
            fix="check gh auth / that factory-runner declares RECOMMENDED_CALLER_PIN, then re-run",
        )
    needed = required_secrets(pin, gh=gh)
    if needed is None:
        return _result(
            check_id,
            UNKNOWN,
            details=[
                {
                    "id": "factory.secrets-required-set-unreadable",
                    "message": "cannot read the reusable workflow's secrets block at the pin",
                }
            ],
            fix="check gh auth and the declared pin, then re-run",
        )
    listing = gh(["secret", "list", "--repo", slug, "--json", "name"])
    if listing is None:
        return _result(
            check_id,
            UNKNOWN,
            details=[
                {
                    "id": "factory.secrets-list-failed",
                    "message": f"cannot list Actions secrets on {slug}",
                }
            ],
            fix="check gh auth (reading secret NAMES needs admin), then re-run",
        )
    try:
        have = {entry["name"] for entry in json.loads(listing)}
    except (ValueError, TypeError, KeyError):
        have = set()
    missing = sorted(needed - have)
    if missing:
        return _result(
            check_id,
            VIOLATION,
            details=[
                {
                    "id": "factory.secrets-missing",
                    "message": f"missing Actions secrets: {', '.join(missing)}",
                }
            ],
            fix=f"gh secret set {' / '.join(missing)} --repo {slug} (values piped from BWS)",
        )
    return _result(
        check_id,
        PASS,
        details=[
            {
                "id": "factory.secrets-present",
                "message": (
                    f"{len(needed)} required secret name(s) present on {slug}; presence is "
                    "not sufficiency -- values are write-only, and factory.pat_access exists "
                    "because a present FACTORY_PR_TOKEN can hold a token that cannot reach "
                    "this repository"
                ),
            }
        ],
    )


def _http_get_json(url: str, headers: dict, timeout: float = 15.0):
    """GET returning a parsed body, or None for ANY failure. Never raises.

    Cloudflare 403s a default Python User-Agent on proxied estate endpoints
    (`error code: 1010`), so an identifying one is sent. `UnicodeError` is a
    `ValueError` and is raised by IDNA encoding of a malformed host -- an
    ordinary environment-variable typo -- so `ValueError` is in the tuple
    alongside the URL errors; without it a bad `APP_BRAIN_URL` would escape as
    a traceback from a checker whose contract is to report `unknown`.
    """
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            if response.status != 200:
                return None
            return json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _landing_fetch(slug: str, base_url: str, key: str):
    query = urllib.parse.urlencode({"github_repo": slug})
    return _http_get_json(
        f"{base_url.rstrip('/')}{_LANDING_ROUTE}?{query}",
        {"x-brain-key": key, "user-agent": _USER_AGENT},
    )


def check_landing_known(repo, slug: str, fetch=None) -> dict:
    """Has the estate DETERMINED what landing on this repository's default branch does?

    App Brain is the authority and is asked, never re-derived: the answer needs
    all three mechanisms that can advance a running service on a landing (a
    workflow step, a repository webhook, and the hosting platform's own git
    integration), and checking any one of them fails open.

    The two failure directions are different facts and must stay
    distinguishable. App Brain answering `unknown` is the ESTATE saying it never
    assessed this repository -- a real Q2 violation, and the state
    `security-standards` was in as a live factory target on 2026-08-09. A
    timeout, a 401, a malformed body or an absent credential is THIS PROCESS
    having no answer, which is `unknown`. One of those needs someone to assess a
    repository; the other needs someone to set an environment variable.
    """
    check_id = "factory.landing_known"
    if not in_q2_scope(repo):
        return _out_of_scope(check_id)
    key = config.app_brain_read_key()
    if not key:
        return _credential_absent(
            check_id, config.APP_BRAIN_KEY_ENV, "what landing on this repository does"
        )
    fetch = fetch or (lambda s: _landing_fetch(s, config.app_brain_url(), key))
    body = fetch(slug)
    landing = body.get("landing") if isinstance(body, dict) else None
    if landing not in (LANDING_REDEPLOYS, LANDING_INERT, LANDING_UNKNOWN):
        return _result(
            check_id,
            UNKNOWN,
            details=[
                {
                    "id": "factory.landing-source-unreadable",
                    "message": (
                        "App Brain did not answer with a landing value this build "
                        "recognises, so what landing does was not measured"
                    ),
                }
            ],
            fix=(
                f"check that {config.app_brain_url()} is reachable and that "
                f"${config.APP_BRAIN_KEY_ENV} is the read-only key, then re-run"
            ),
        )
    if landing == LANDING_UNKNOWN:
        reason = body.get("reason") if isinstance(body, dict) else None
        return _result(
            check_id,
            VIOLATION,
            details=[
                {
                    "id": "factory.landing-not-determined",
                    "message": (
                        f"the estate has not determined what landing on {slug} does "
                        f"(App Brain: unknown/{reason or 'no reason given'}); a fail-closed "
                        "consumer refuses this, so no work can land here"
                    ),
                }
            ],
            fix=(
                f"determine what landing on {slug}'s default branch does across ALL THREE "
                "mechanisms (workflow steps, repository webhooks, and the hosting platform's "
                "git integration -- checking one fails open) and record it in App Brain"
            ),
        )
    return _result(
        check_id,
        PASS,
        details=[
            {
                "id": "factory.landing-determined",
                "message": f"the estate records landing on {slug} as {landing!r}; {_GREEN_MEANS}",
            }
        ],
    )


def run_factory_checks(repo, slug: str, gh=_gh) -> list[dict]:
    """The four Q2 capability checks, in `FACTORY_CHECKS` order.

    `runner.caller` is the fifth Q2 check and is NOT here: it predates this
    module and stays in `onboard_checks`, which is also where its Q1
    `not-applicable` path belongs.
    """
    return [
        check_pat_access(repo, slug),
        check_pat_scope(repo),
        check_secrets(repo, slug, gh=gh),
        check_landing_known(repo, slug),
    ]


def memoizing_gh(gh=_gh):
    """A `gh` reader that answers each identical argv once per sweep.

    Six repositories asking factory-runner for the same pin and the same
    reusable workflow is six identical round trips, and `runner.caller` and
    `factory.secrets` each list the same repository's secrets. Read-only calls
    within one sweep, so a cached answer is the same answer.

    **Failures are NOT cached, and that is the whole subtlety.** A cached `None`
    turns one transient GitHub blip into every repository in the sweep reporting
    `unknown` for the rest of the night -- observed on the first real run, where
    a single failed read of `RECOMMENDED_CALLER_PIN` unknown-ed `factory.secrets`
    for every subject. It fails safe rather than open, but it converts a
    momentary outage into a whole-estate one, and retrying costs a call.
    """
    cache: dict[tuple, str] = {}

    def cached(args: list[str]) -> str | None:
        key = tuple(args)
        if key in cache:
            return cache[key]
        value = gh(args)
        if value is not None:
            cache[key] = value
        return value

    return cached


def sweep(repos, gh=None) -> dict[str, list[dict]]:
    """Q2 for every repository IN SCOPE, keyed by path string.

    **Q2's answer changes without anyone touching the repository** -- a PAT
    rotation, an expired Actions secret, an App Brain record edited, or
    factory-runner advancing `RECOMMENDED_CALLER_PIN`. So a check run once at
    onboarding is worse than none: it certifies a capability that has since
    lapsed. This is the nightly half of the answer; `portfolio onboard` is the
    on-demand half.

    Out-of-scope repositories are absent from the result rather than carrying
    four `not-applicable` rows, so the sweep's cost stays proportional to the
    repositories that declare a delivery profile (six today, not sixty-one).
    """
    gh = gh or memoizing_gh()
    results: dict[str, list[dict]] = {}
    for repo in repos:
        if not in_q2_scope(repo):
            continue
        slug = repo_slug(repo)
        if slug is None:
            results[str(repo)] = [
                _result(
                    check_id,
                    UNKNOWN,
                    details=[
                        {
                            "id": f"{check_id}.no-origin",
                            "message": "cannot derive a GitHub slug from the origin remote",
                        }
                    ],
                    fix=f"add a GitHub origin remote to {repo}",
                )
                for check_id in ("runner.caller", *FACTORY_CHECKS)
            ]
            continue
        results[str(repo)] = [
            check_runner_caller(repo, slug, gh=gh),
            *run_factory_checks(repo, slug, gh=gh),
        ]
    return results
