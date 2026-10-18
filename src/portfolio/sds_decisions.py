"""Devon's per-repository onboarding decisions (`portfolio sds-ready`).

Two decisions only Devon can make are recorded in
`<portfolio home>/onboarding/<repo>/decisions.toml`: whether the repository
should be a factory target, and whether landing on its default branch is
`inert` or `redeploys`. A missing decision, a refusal and an unreadable file
are all violations; none is ever read as consent.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config
from .matrix import PASS, VIOLATION
from .onboard_checks import _result

DECISIONS_FILE = "decisions.toml"
LANDING_VALUES = ("inert", "redeploys")

FORMAT = (
    "onboard = true\n"
    'onboard_reason = "why the factory works on this repository"\n'
    'landing = "inert"   # or "redeploys"'
)


class DecisionsError(Exception):
    """The decisions file exists but cannot be read as decisions."""


@dataclass(frozen=True)
class Decisions:
    onboard: bool | None
    onboard_reason: str | None
    landing: str | None


def repo_key(slug: str) -> str:
    """The directory name for a GitHub slug: two checkouts named alike never share one."""
    return slug.replace("/", "__")


def onboarding_dir(key: str) -> Path:
    return config.portfolio_home() / "onboarding" / key


def _path(key: str) -> Path:
    return onboarding_dir(key) / DECISIONS_FILE


def read_decisions(repo_name: str) -> Decisions:
    """The recorded decisions; all None when the file is absent."""
    path = _path(repo_name)
    if not path.exists():
        return Decisions(None, None, None)
    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise DecisionsError(f"{path} cannot be read: {exc}") from exc
    onboard = data.get("onboard")
    reason = data.get("onboard_reason")
    landing = data.get("landing")
    if onboard is not None and not isinstance(onboard, bool):
        raise DecisionsError(f"{path}: onboard must be true or false")
    if reason is not None and not isinstance(reason, str):
        raise DecisionsError(f"{path}: onboard_reason must be a string")
    if landing is not None and landing not in LANDING_VALUES:
        raise DecisionsError(f'{path}: landing must be "inert" or "redeploys"')
    return Decisions(onboard, reason, landing)


def check_decisions(repo_name: str) -> dict:
    path = _path(repo_name)
    fix = f"Record the decisions in {path} in this format:\n{FORMAT}"
    try:
        decisions = read_decisions(repo_name)
    except DecisionsError as exc:
        details = [{"id": "sds.decisions-unreadable", "message": str(exc)}]
        return _result("sds.decisions", VIOLATION, details, fix)

    if decisions.onboard is False:
        message = f"{path} records onboard = false: this repository is not to be onboarded."
        details = [{"id": "sds.refused-not-onboarding", "message": message}]
        return _result("sds.decisions", VIOLATION, details, fix)

    details = []
    if decisions.onboard is None:
        details.append(
            {"id": "sds.decide-onboard", "message": f"{path} does not say whether to onboard."}
        )
    elif not (decisions.onboard_reason or "").strip():
        details.append(
            {
                "id": "sds.decide-onboard",
                "message": f"{path} has onboard = true but no onboard_reason (required).",
            }
        )
    if decisions.landing == "redeploys":
        message = f'{path} records landing = "redeploys": landing redeploys this repository.'
        return _result(
            "sds.decisions",
            VIOLATION,
            [{"id": "sds.refused-redeploys", "message": message}],
            fix,
        )
    if decisions.landing is None:
        message = f'{path} does not say whether landing is "inert" or "redeploys".'
        details.append({"id": "sds.decide-landing", "message": message})

    if details:
        return _result("sds.decisions", VIOLATION, details, fix)
    return _result("sds.decisions", PASS)
