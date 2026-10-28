"""Which repositories the nightly Q2 sweep measures, read from the SDS member record.

The member record (orchestrator ADR-0058) is the one list of repositories the SDS maintains,
with an explicit per-service grant on each. A repository is a factory target exactly when it is
granted `app_changes`: the orchestrator's daily membership check holds that grant equal to each
repository's `factory-target.toml`. The sweep measures those, and the members whose grant is
`remediating` (readiness found gaps and remediation work exists), because Q2 is how that work is
seen to land. It never infers scope from what a working copy declares.

INCOMPLETE IS SAID OUT LOUD, NEVER IMPLIED BY A SHORTER LIST. An unset token, a URL that is not
https, an unreachable or refusing orchestrator, a body that is not the member record, and a
record that measures no repository all raise `MemberRecordUnreadable` with the reason. The record
is one read, so there is no partial answer.
"""

import http.client
import json
import urllib.error
import urllib.request

from . import config

SERVICE = "app_changes"
MEASURED_STATES = frozenset({"granted", "remediating"})
_MEMBERS_ROUTE = "/api/v1/members"
_USER_AGENT = "project-standards-conformance-kit/1 (+AlobarQuest/project-standards)"


class MemberRecordUnreadable(Exception):
    """The member record could not be read; the message says why."""


def _fetch(url: str, token: str, timeout: float = 15.0) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Credential-Key-Id": config.SDS_OBSERVER_KEY_ID,
            "Accept": "application/json",
            # sds.alobar.net is Cloudflare-proxied, which refuses a default Python User-Agent.
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        raise MemberRecordUnreadable(
            f"the orchestrator answered {error.code} for GET {_MEMBERS_ROUTE}"
        ) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        raise MemberRecordUnreadable(
            f"the member record is unreachable: {type(error).__name__}"
        ) from None
    except ValueError:
        # A body that is not JSON, or a malformed URL (IDNA raises UnicodeError, a ValueError).
        raise MemberRecordUnreadable(
            f"the answer to GET {_MEMBERS_ROUTE} was not the member record"
        ) from None


def _slug(member: dict) -> str:
    repository = member["repository"]
    if not isinstance(repository, str) or "/" not in repository:
        raise TypeError("repository")
    return repository.lower()


def granted(body: object) -> frozenset[str]:
    """The live members whose `app_changes` grant is measured, as lowercased `owner/repo` slugs."""
    try:
        if not isinstance(body, dict):
            raise TypeError("body")
        members = body["members"]
        if not isinstance(members, list):
            raise TypeError("members")
        slugs = frozenset(
            _slug(m)
            for m in members
            if m["state"] != "retired" and m["grants"][SERVICE]["state"] in MEASURED_STATES
        )
    except KeyError, TypeError:
        raise MemberRecordUnreadable(
            f"the answer to GET {_MEMBERS_ROUTE} was not the member record"
        ) from None
    if not slugs:
        raise MemberRecordUnreadable(f"the member record grants {SERVICE} to no repository")
    return slugs


def read_granted(fetch=_fetch) -> frozenset[str]:
    """One read of the member record, answering the repositories the sweep measures."""
    token = config.sds_observer_token()
    if not token:
        raise MemberRecordUnreadable(f"${config.SDS_OBSERVER_TOKEN_ENV} is not set")
    base = config.sds_url().rstrip("/")
    if not base.startswith("https://"):
        # The bearer is a shared SDS credential: it goes nowhere it could be read in transit.
        raise MemberRecordUnreadable(f"the orchestrator URL {base!r} is not https")
    return granted(fetch(f"{base}{_MEMBERS_ROUTE}", token))
