"""Render `portfolio sds-ready` results: the build handoff, Devon's tasks and the summary.

Each renderer reads only its `RepoFacts`, the `Verdict` and the shared guidance
text, and lists checks in the Verdict's order, so identical inputs give
byte-identical output. A check's own `fix` string is never rendered: the
guidance is the single voice for what to do.
"""

import textwrap
from dataclasses import dataclass
from pathlib import Path

from .sds_assess import Verdict
from .sds_checks import EVIDENCE_PATH
from .sds_decisions import DECISIONS_FILE, FORMAT, onboarding_dir
from .sds_guidance import ANTI_GOAL_1, ANTI_GOAL_2, GUIDANCE, SECURITY_SCAN_COMMAND

HANDOFF_FILE = "HANDOFF.md"
TASKS_FILE = "TASKS.md"


@dataclass(frozen=True)
class RepoFacts:
    name: str
    slug: str
    default_branch: str
    tooling: tuple[str, ...]
    checkout: Path


_INTRO = (
    "SDS, the Software Delivery System, is the factory that takes work for a repository, runs a "
    "coding agent on it, verifies the result with the repository's own tests and lands the pull "
    "request. Onboarding makes this repository a factory target. A readiness command measures "
    "every requirement and sorts each gap by owner: repository work, which needs judgment inside "
    "the repository and is yours; Devon's tasks, which are decisions and GitHub settings only he "
    "can act on; and onboarding actions, which a separate procedure performs after Devon says "
    "yes. This document lists your share. It is complete on its own."
)

_INSTRUCTION = (
    "Work until `portfolio sds-ready <checkout>` reports no repository work. Merge your own pull "
    "request once the repository's Quality job passes on it and the evidence file records no "
    "unexplained differences."
)


def _check_section(check: dict, heading: str) -> list[str]:
    """A check's details, one bullet each, then its guidance's why, done and how."""
    guidance = GUIDANCE[check["id"]]
    lines = [f"{heading} `{check['id']}`", ""]
    if check["details"]:
        lines += [f"- {detail['message']}" for detail in check["details"]] + [""]
    return lines + [
        f"**Why it matters.** {guidance.why}",
        "",
        f"**What done means.** {guidance.done}",
        "",
        f"**How to fix it.** {guidance.how}",
        "",
    ]


def render_handoff(facts: RepoFacts, verdict: Verdict) -> str:
    """The build handoff: everything a build agent with no other context needs."""
    tooling = ", ".join(f"`{name}`" for name in facts.tooling) or "none found"
    lines = [
        f"# Make {facts.name} ready for SDS",
        "",
        "## What SDS onboarding is",
        "",
        _INTRO,
        "",
        _INSTRUCTION,
        "",
        "## Repository facts",
        "",
        f"- Name: {facts.name}",
        f"- GitHub repository: `{facts.slug}`",
        f"- Default branch: `{facts.default_branch}`",
        f"- Checkout: `{facts.checkout}`",
        f"- Manifest files at the checkout root: {tooling}",
        f"- Behavior evidence: `{EVIDENCE_PATH}` records the before-and-after comparison of what "
        "the repository serves.",
        "",
        "## Repository work",
        "",
    ]
    if verdict.repository:
        lines += [
            "Each check below is a gap. Its details come first, then why it matters, what done "
            "means and how to fix it.",
            "",
        ]
        for check in verdict.repository:
            lines += _check_section(check, "###")
    else:
        lines += ["The readiness command reports no repository work.", ""]
    lines += [
        "## Standards that apply",
        "",
        "- Follow the code standards in `~/Developer/code-standards/STANDARDS.md`.",
        "- Run the security scanner from the repository root and clear every BLOCK finding: "
        f"`{SECURITY_SCAN_COMMAND}`",
        "- Always query Code Brain before adding a cross-cutting pattern, such as logging, error "
        "handling, authentication or secrets, and follow the rules it returns.",
        "",
        "## Hard constraints",
        "",
        "The process has failed, even if every check passes, if either of these happens:",
        "",
        f"1. {ANTI_GOAL_1}",
        f"2. {ANTI_GOAL_2}",
        "",
        "Never deploy anything. Onboarding never deploys, and the readiness work does not "
        "either: capture behavior from local builds only.",
        "",
        "## Rerun and what clean looks like",
        "",
        "From the checkout, run:",
        "",
        "```bash",
        f"portfolio sds-ready {facts.checkout}",
        "```",
        "",
        "Clean means its summary has no repository-work line. Devon's tasks, environment "
        "problems and onboarding actions can still appear; they are not yours to fix.",
    ]
    return "\n".join(lines) + "\n"


def render_tasks(facts: RepoFacts, verdict: Verdict) -> str:
    """Devon's task list: each check only he can act on, with its guidance."""
    lines = [f"# Devon's tasks for {facts.name}", ""]
    if not verdict.devon:
        lines.append(f"You have no tasks for {facts.name}.")
        return "\n".join(lines) + "\n"
    lines += [
        f"Each task blocks onboarding until the readiness command confirms it. When you finish "
        f"one, rerun `portfolio sds-ready {facts.checkout}`: its result is the completion signal.",
        "",
    ]
    for check in verdict.devon:
        lines += _check_section(check, "##")
        if check["id"] == "sds.decisions":
            path = onboarding_dir(facts.name) / DECISIONS_FILE
            lines += [f"Decisions file: `{path}`", "", "```toml", FORMAT, "```", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _count(checks: tuple[dict, ...]) -> str:
    return f"{len(checks)} check" + ("" if len(checks) == 1 else "s")


def render_summary(facts: RepoFacts, verdict: Verdict) -> str:
    """The stderr digest. When ready, it ends with the question Devon answers in chat."""
    lines = [f"{facts.name}: {verdict.phase}"]
    if verdict.refusals:
        lines.append("Refused:")
        lines += [f"  - {detail['message']}" for detail in verdict.refusals]
        lines.append(
            f"{facts.name} can't be onboarded: the refusal above is a recorded decision, "
            "not a gap to fix."
        )
    if verdict.environment:
        lines.append("Environment (the readiness command could not measure these):")
        for check in verdict.environment:
            lines.append(f"  - {check['id']}")
            lines += [f"    {detail['message']}" for detail in check["details"]]
            lines.append(textwrap.indent(GUIDANCE[check["id"]].how, "    "))
    home = onboarding_dir(facts.name)
    if verdict.repository:
        lines.append(
            f"Repository work: {_count(verdict.repository)}. "
            f"Hand {home / HANDOFF_FILE} to a build agent."
        )
    if verdict.devon:
        lines.append(f"Devon's tasks: {_count(verdict.devon)}. See {home / TASKS_FILE}.")
    if verdict.onboarding:
        lines.append("Onboarding actions:")
        lines += [
            f"  - {check['id']}: {'done' if done else 'pending'}"
            for check, done in verdict.onboarding
        ]
    if verdict.ready:
        if verdict.phase == "complete":
            lines.append("Onboarding is complete.")
        elif verdict.phase == "in-progress":
            lines.append("Onboarding is partly done; reply yes to resume it.")
        else:
            lines.append(f"Ready to onboard {facts.name}. Reply yes to onboard it.")
    return "\n".join(lines)
