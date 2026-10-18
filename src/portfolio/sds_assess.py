"""Sort `portfolio sds-ready` check results into who acts on them."""

from dataclasses import dataclass

from .sds_guidance import EXCLUDED, GUIDANCE, REFUSAL_DETAIL_IDS


@dataclass(frozen=True)
class Verdict:
    refusals: tuple[dict, ...]
    environment: tuple[dict, ...]
    repository: tuple[dict, ...]
    devon: tuple[dict, ...]
    onboarding: tuple[tuple[dict, bool], ...]
    phase: str
    ready: bool


def _phase(done_flags: list[bool]) -> str:
    if not any(done_flags):
        return "not-started"
    return "complete" if all(done_flags) else "in-progress"


def assess(checks: list[dict]) -> Verdict:
    """Route each check result to the party who acts on it.

    A refusal detail makes the repository not ready and routes the check nowhere
    else (an onboarding-owned one still counts, not done, toward the phase).
    `unknown` is an environment problem whoever owns the check, so it never
    reaches the build handoff or Devon's list. Onboarding-owned checks are
    planned actions, not gaps: done means `pass` only.
    """
    refusals: list[dict] = []
    environment: list[dict] = []
    repository: list[dict] = []
    devon: list[dict] = []
    onboarding: list[tuple[dict, bool]] = []
    for check in checks:
        if check["id"] in EXCLUDED:
            continue
        owner = GUIDANCE[check["id"]].owner
        status = check["status"]
        done = status == "pass"
        refused = [d for d in check["details"] if d.get("id") in REFUSAL_DETAIL_IDS]
        if owner == "onboarding":
            onboarding.append((check, done))
        if refused:
            refusals.extend(refused)
        elif status == "unknown":
            environment.append(check)
        elif status == "violation":
            if owner == "repository":
                repository.append(check)
            elif owner == "devon":
                devon.append(check)
    return Verdict(
        refusals=tuple(refusals),
        environment=tuple(environment),
        repository=tuple(repository),
        devon=tuple(devon),
        onboarding=tuple(onboarding),
        phase=_phase([done for _, done in onboarding]),
        ready=not (refusals or environment or repository or devon),
    )
