"""`factory-target.toml` has three readers in two repositories, held to one case table.

This repository's `parse_declaration` is one; the orchestrator's dispatch-admission reader and
its work carrier's reader are the other two. None can import another across the repository
boundary, so each repository carries a byte-identical
`tests/fixtures/factory_target_declarations.json` pinned by the same `CONTRACT_SHA256`. A
one-sided edit to the table reds the repository that was not updated; a parser that stops
agreeing with it reds its own repository.

The table answers what a file's OWN BYTES say, so `null` here is `FactoryTargetError` --
the answer `runner.caller` turns into `unknown` and `portfolio lint` into a FAIL. Absence of
the file is a property of the read, covered in `test_factory_target.py`.
"""

import hashlib
import json
from pathlib import Path

import pytest

from portfolio.factory_target import FactoryTargetError, parse_declaration

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "factory_target_declarations.json"
CONTRACT_SHA256 = "64d31a44f56c9a34b6bb5f24a143b046fb459a678f66b8e5c263a96ed3ae6469"


def golden_cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _answer(text):
    try:
        target, _reason = parse_declaration(text)
    except FactoryTargetError:
        return None
    return target


def test_the_case_table_is_unchanged():
    """A one-sided edit here means the orchestrator's copy has silently drifted."""
    canonical = json.dumps(
        json.loads(FIXTURE.read_text(encoding="utf-8")), sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == CONTRACT_SHA256


def test_the_case_table_covers_all_three_answers():
    """Without this, a table of only well-formed files would agree trivially."""
    assert {case["target"] for case in golden_cases()} == {True, False, None}


@pytest.mark.parametrize("case", golden_cases(), ids=lambda case: case["name"])
def test_parse_declaration_answers_what_the_table_says(case):
    assert _answer(case["text"]) is case["target"]
