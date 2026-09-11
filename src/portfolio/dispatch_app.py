"""Read what the "Alobar SDS Dispatch" GitHub App can reach, and with what.

The estate's factory work needs TWO credentials and the kit only ever checked
one. `FACTORY_PR_TOKEN` checks out, pushes the branch and opens the pull
request, and `factory.pat_access` / `factory.pat_scope` / `factory.secrets`
cover it. The App is the other half: it fires `workflow_dispatch` at the
caller, reads the named check, and lands the pull request. Nothing anywhere
verified it. That was survivable only because the installation's
`repository_selection` is `all`, which makes its reach constant -- and "it has
always been true" is not a check. A narrowing of that grant is exactly the
change that would stop dispatch per repository with nothing having said so.

**This module is the one place the App's private key is handled**, so "where
does the key go" has a single answer:

- it arrives BASE64-ENCODED in an environment variable, the same encoding the
  orchestrator's own `ORCHESTRATOR_GITHUB_APP_PRIVATE_KEY_B64` uses. A single
  line rather than a multi-line PEM, so an operator's `credentials.env` stays
  an ordinary `KEY=value` file;
- it is decoded in memory and handed to `openssl` on a DEDICATED FILE
  DESCRIPTOR. Never argv (visible in `ps`), never a temporary file, never a
  log line, never a check result's details;
- the environment this module gives `openssl` is minimal and carries no
  credential of any kind.

The residual, stated rather than papered over: a credential taken from the
environment is inherited by every child this process spawns, `gh` and `git`
included. That is a property of the spec's decision to take credentials from
the environment rather than fetch them, and it is already true of the two the
kit carries. What this module adds is that the newest of them is the most
powerful -- see the note on `PRIVATE_KEY_ENV` in `config`.

**Nothing here mints a token unless it has to, and the live shape never does.**
`GET /app/installations/{id}` is a JWT-authenticated READ that reports the
granted permissions, `repository_selection` and `suspended_at`. Only a
`selected` installation needs the repository list, which no read-only route
serves; that path mints an access token DOWN-SCOPED to `metadata: read` and
revokes it immediately. Measured 2026-09-11: the down-scoped token answers 403
to `GET /repos/<private>/actions/runs` where the full installation token
answers 200, and after `DELETE /installation/token` it answers 401.

**Read the INSTALLATION, never `GET /app`.** The App reports the permissions it
REQUESTS; the installation reports what was GRANTED. They agreed on 2026-09-11
and have diverged before -- CLAUDE.md records a window in which `/app` said
`pull_requests: write` while the installation still said otherwise, so a check
written against `/app` would have certified a token that could not merge.
"""

import base64
import binascii
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config

GITHUB_API_URL = "https://api.github.com"
_USER_AGENT = "project-standards-conformance-kit/1 (+AlobarQuest/project-standards)"
_TIMEOUT = 20.0

# The JWT window GitHub accepts is ten minutes. `iat` is backdated a minute
# because GitHub rejects a token whose issue time is ahead of its own clock,
# and small clock skew between this machine and GitHub is ordinary.
_JWT_BACKDATE_S = 60
_JWT_LIFETIME_S = 540

# 100 repositories a page. A bound rather than an unbounded follow; exceeding it
# is reported, never silently truncated.
_MAX_REPOSITORY_PAGES = 20

REPOSITORY_SELECTION_ALL = "all"
REPOSITORY_SELECTION_SELECTED = "selected"


@dataclass(frozen=True)
class AppReach:
    """What the installation is granted, and where it applies.

    `repository_selection` is the discriminator and callers must branch on IT,
    never on `repositories`. An empty repository set and an unrestricted one are
    opposite facts, and a reader keyed on absence turns "reaches everything"
    into "reaches nothing" -- the fail-open shape this estate has now found in
    several vocabularies. `repositories` is None when, and only when, the
    selection is `all`, in which case there is no list to hold.
    """

    permissions: dict[str, str]
    repository_selection: str
    suspended: bool
    repositories: frozenset[str] | None


@dataclass(frozen=True)
class AppUnreadable:
    """Why the App's reach could not be established. Always `unknown`, never a verdict.

    Carries its own detail id and fix so the caller does not have to
    re-diagnose, and so a credential problem is never reported as a defect in
    the repository being measured.
    """

    detail_id: str
    message: str
    fix: str


def _minimal_env() -> dict[str, str]:
    """An environment for `openssl` carrying no credential and nothing else it needs.

    `PATH` so the binary resolves; nothing more. The App key, the PAT and the
    App Brain key are all absent by construction rather than by filtering,
    which cannot drift as the kit's credential set grows.
    """
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _sign_rs256(payload: bytes, private_key_pem: bytes) -> bytes | None:
    """RS256 over `payload`, or None if the key or `openssl` will not cooperate.

    The key travels on file descriptor 3 and is named to `openssl` as
    `/dev/fd/3`, so it never appears in argv and never touches disk. It is
    written and the write end closed BEFORE the signing input is sent, which is
    safe for any RSA key: a 4096-bit PEM is about 3.2KB against a pipe buffer of
    64KB, so the write cannot block waiting for a reader that is waiting for us.
    """
    read_fd, write_fd = os.pipe()
    try:
        process = subprocess.Popen(  # noqa: S603
            ["openssl", "dgst", "-sha256", "-sign", f"/dev/fd/{read_fd}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(read_fd,),
            env=_minimal_env(),
        )
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        return None
    os.close(read_fd)
    try:
        os.write(write_fd, private_key_pem)
    except OSError:
        process.kill()
        return None
    finally:
        os.close(write_fd)
    try:
        signature, _ = process.communicate(payload, timeout=_TIMEOUT)
    except (subprocess.SubprocessError, OSError):
        process.kill()
        return None
    # stderr is deliberately discarded rather than reported: openssl's message
    # for an unusable key quotes nothing of the key, but a future version's
    # might, and this value must never reach a result or a log.
    return signature if process.returncode == 0 and signature else None


def _app_jwt(private_key_b64: str, app_id: str, now: float | None = None) -> str | None:
    """A signed App JWT, or None when the key cannot produce one."""
    try:
        pem = base64.b64decode("".join(private_key_b64.split()), validate=True)
    except (binascii.Error, ValueError):
        return None
    issued = int(now if now is not None else time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64url(
        json.dumps(
            {
                "iat": issued - _JWT_BACKDATE_S,
                "exp": issued + _JWT_LIFETIME_S,
                "iss": app_id,
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = header + b"." + claims
    signature = _sign_rs256(signing_input, pem)
    if signature is None:
        return None
    return (signing_input + b"." + _b64url(signature)).decode()


def _api(path: str, bearer: str, method: str = "GET", body: dict | None = None):
    """One GitHub call, returning (status, parsed body). `(None, None)` for a transport failure.

    `UnicodeError` is a `ValueError` and is what IDNA encoding raises for a
    malformed host, so an environment-variable typo in an API base would
    otherwise escape as a traceback from a module whose contract is to report
    `unknown`.
    """
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{GITHUB_API_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def _unreadable(detail_id: str, message: str, fix: str) -> AppUnreadable:
    return AppUnreadable(detail_id=detail_id, message=message, fix=fix)


def _selected_repositories(jwt: str, installation_id: str) -> frozenset[str] | AppUnreadable:
    """Enumerate a `selected` installation's repositories. Mints, then revokes.

    No read-only route serves this list -- `GET /installation/repositories`
    needs an installation access token, and the JWT that reads the installation
    cannot call it. So this path mints one, DOWN-SCOPED to `metadata: read`
    (which reaches this listing and nothing else), and revokes it in a `finally`
    so a failure part-way through does not leave a live credential behind.

    It is unreachable while the installation is `all`, which is the live shape.
    It exists because a narrowing to `selected` is precisely the change this
    check was built to notice, and a branch that answered `unknown` there would
    go quiet at the only moment it matters.
    """
    status, body = _api(
        f"/app/installations/{installation_id}/access_tokens",
        jwt,
        method="POST",
        body={"permissions": {"metadata": "read"}},
    )
    token = body.get("token") if isinstance(body, dict) else None
    if status != 201 or not isinstance(token, str) or not token:
        return _unreadable(
            "factory.app-token-unmintable",
            "the installation is repository-selected and a token to enumerate its "
            f"repositories could not be minted (HTTP {status})",
            "check that the App installation is active and the private key current, then re-run",
        )
    try:
        names: set[str] = set()
        expected: int | None = None
        page = 1
        while page <= _MAX_REPOSITORY_PAGES:
            status, body = _api(f"/installation/repositories?per_page=100&page={page}", token)
            if status != 200 or not isinstance(body, dict):
                return _unreadable(
                    "factory.app-repositories-unreadable",
                    "the installation is repository-selected and its repository list "
                    f"could not be read (HTTP {status})",
                    "re-run; if it persists, read the installation's repository access by hand",
                )
            if expected is None and isinstance(body.get("total_count"), int):
                expected = body["total_count"]
            batch = body.get("repositories")
            if not isinstance(batch, list) or not batch:
                break
            names.update(
                entry["full_name"].lower()
                for entry in batch
                if isinstance(entry, dict) and isinstance(entry.get("full_name"), str)
            )
            if len(batch) < 100:
                break
            page += 1
        # A SHORT LIST IS NOT A SHORTER GRANT. The page bound, a name this build
        # could not read, or a listing that simply stopped early all produce a set
        # missing entries the installation does in fact reach -- and the caller
        # turns a missing entry into `violation`, which is the one thing a
        # measurement problem must never become. GitHub states the count, so the
        # truncation is detectable rather than assumed.
        if expected is None or len(names) != expected:
            return _unreadable(
                "factory.app-repositories-incomplete",
                "the installation is repository-selected and its repository list came "
                f"back incomplete ({len(names)} read against "
                f"{'no stated total' if expected is None else expected}), so which "
                "repositories it reaches was not measured",
                "re-run; a list this long may exceed the page bound this build follows, in "
                "which case raise _MAX_REPOSITORY_PAGES",
            )
        return frozenset(names)
    finally:
        _api("/installation/token", token, method="DELETE")


def read_reach(
    private_key_b64: str | None = None,
    app_id: str | None = None,
    installation_id: str | None = None,
) -> AppReach | AppUnreadable:
    """What the Dispatch App installation is granted, and over which repositories.

    Every non-answer is an `AppUnreadable` with its own detail id, because the
    binding clause of the 2026-08-17 spec is that a credential problem must
    produce `unknown` and never `violation`: this must not report a repository
    defective because the operator's environment was wrong.

    A 404 is deliberately `unknown` rather than a verdict. It is returned both
    for an app or installation id this build has wrong and for an App that has
    been uninstalled, and those want opposite remedies -- the two are
    indistinguishable from the response, so the honest answer is that the reach
    was not established.
    """
    key = private_key_b64 if private_key_b64 is not None else config.dispatch_app_private_key_b64()
    if not key:
        return _unreadable(
            "factory.app-credential-absent",
            f"${config.DISPATCH_APP_KEY_ENV} is not set, so the App's reach was not measured",
            f"export {config.DISPATCH_APP_KEY_ENV} before running",
        )
    app_id = app_id or config.dispatch_app_id()
    installation_id = installation_id or config.dispatch_app_installation_id()
    jwt = _app_jwt(key, app_id)
    if jwt is None:
        return _unreadable(
            "factory.app-key-unusable",
            f"${config.DISPATCH_APP_KEY_ENV} could not sign an App JWT, so the App's "
            "reach was not measured (the value must be a base64-encoded PEM private key, "
            "and `openssl` must be on PATH)",
            f"re-export {config.DISPATCH_APP_KEY_ENV} as base64 of the App's PEM private key "
            "(`base64 < key.pem`), and confirm `openssl` is available",
        )
    status, body = _api(f"/app/installations/{installation_id}", jwt)
    if status != 200 or not isinstance(body, dict):
        return _unreadable(
            "factory.app-installation-unreadable",
            f"the App installation could not be read (HTTP {status}); the App's reach "
            "was not measured",
            "a 401 means the key is not this App's; a 404 means the app/installation id is "
            "wrong or the App is uninstalled -- the two are indistinguishable here, so check "
            "both and re-run",
        )
    permissions = body.get("permissions")
    selection = body.get("repository_selection")
    if not isinstance(permissions, dict) or not isinstance(selection, str):
        return _unreadable(
            "factory.app-installation-unreadable",
            "the App installation answered without a readable permissions object or "
            "repository_selection, so its reach was not measured",
            "inspect GET /app/installations/{id} by hand; the response shape was not the "
            "documented one",
        )
    repositories: frozenset[str] | None = None
    if selection == REPOSITORY_SELECTION_SELECTED:
        listed = _selected_repositories(jwt, installation_id)
        if isinstance(listed, AppUnreadable):
            return listed
        repositories = listed
    return AppReach(
        permissions={k: v for k, v in permissions.items() if isinstance(v, str)},
        repository_selection=selection,
        suspended=body.get("suspended_at") is not None,
        repositories=repositories,
    )


def memoizing_reach(read=read_reach):
    """`read_reach` answered once per sweep rather than once per repository.

    The App's reach is an installation-level fact, so six repositories asking
    for it is six identical round trips and, under a `selected` installation,
    six minted tokens. **Failures are NOT cached**, for the reason
    `memoizing_gh` gives: a cached failure turns one transient blip into every
    repository in the sweep reporting `unknown` for the rest of the night.
    """
    cache: list[AppReach] = []

    def cached() -> AppReach | AppUnreadable:
        if cache:
            return cache[0]
        answer = read()
        if isinstance(answer, AppReach):
            cache.append(answer)
        return answer

    return cached
