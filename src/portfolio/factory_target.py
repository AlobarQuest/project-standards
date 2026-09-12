"""A repository's own answer to "may the SDS factory be dispatched work here?" (ADR-0015).

The declaration lives in `factory-target.toml` at the repository root, and that
file's only job is to answer this one question. It used to live in `PROJECT.md`
frontmatter, which also carries the backlog and is edited routinely by
`portfolio add` and the `backlog` skill -- a multipurpose document standing in
for a config file, which Devon ruled out on 2026-09-11. The key names did not
move with it, so `git grep factory_target` still finds every site.

**Absence of the file means NOT a target.** Participation is declared, never
assumed, so a repository that has said nothing has not opted in. That is a
change of direction from the frontmatter era, where an absent key meant
"nothing declared" and left every check exactly where it was: back then a
declaration could only ever turn a `violation` into `not-applicable`, so
silence had to be inert. Now silence is an answer, and the check that reads it
has to be able to say so.

**A file that exists and cannot be read as a declaration RAISES.** It is
neither "yes" nor the deliberate silence of absence -- somebody tried to
declare something and the file does not say what. Reading it as `false` would
quietly grant a repository the non-target's exemption on a typo; reading it as
`true` would quietly demand a caller. Both keys are required, including the
reason on a `true`, because a bare `true` becomes folklore. Consumers turn the
raised error into their own "could not tell" answer: `runner.caller` reports
`unknown`, which never satisfies admission, and `portfolio lint` reports a
FAIL.
"""

import tomllib
from pathlib import Path

FILENAME = "factory-target.toml"


class FactoryTargetError(Exception):
    """`factory-target.toml` exists and cannot be read as a declaration."""


def factory_target_declaration(repo: Path) -> tuple[bool, str | None]:
    """Return `(target, reason)` for a WORKING COPY; `(False, None)` when absent.

    `portfolio lint` reads the declaration this way because it lints the tree in
    front of it. `runner.caller` does NOT: it asks whether the factory can be
    sent work into a REPOSITORY, and a working copy three commits behind is not
    that repository. It parses the remote bytes through `parse_declaration`.

    Raises `FactoryTargetError` when the file exists but is unparseable, is
    missing either key, or carries the wrong type for one.
    """
    path = repo / FILENAME
    if not path.is_file():
        return False, None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise FactoryTargetError(f"{FILENAME} cannot be read: {error}") from error
    return parse_declaration(text)


def parse_declaration(text: str) -> tuple[bool, str | None]:
    """Both keys out of the declaration's own bytes, wherever they came from.

    Split out from the reader above so the remote and the local paths cannot
    drift into two vocabularies for one file -- the failure this estate has now
    met in four separate places, and the reason `runner.caller` can move its
    read to the remote without acquiring a second parser.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise FactoryTargetError(f"{FILENAME} cannot be read: {error}") from error

    target = data.get("factory_target")
    if not isinstance(target, bool):
        raise FactoryTargetError(
            f"{FILENAME} must declare `factory_target` as a bool, got {target!r}"
        )
    reason = data.get("factory_target_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise FactoryTargetError(
            f"{FILENAME} must declare `factory_target_reason` as a non-empty string, "
            f"got {reason!r} -- a bare `factory_target = {str(target).lower()}` becomes folklore"
        )
    return target, reason.strip()
