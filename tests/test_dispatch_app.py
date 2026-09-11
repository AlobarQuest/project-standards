"""The Dispatch App credential surface.

Two properties carry the whole module and are asserted rather than assumed: the
private key never reaches argv or a child's environment, and every way the
reach can fail to be established produces an `AppUnreadable` — a reason — and
never a verdict about the repository being measured.
"""

import base64
import json
import subprocess

import pytest

from portfolio import config, dispatch_app
from portfolio.dispatch_app import AppReach, AppUnreadable, memoizing_reach, read_reach


@pytest.fixture(scope="module")
def rsa_key_b64():
    """A throwaway RSA key, generated here and never written to disk."""
    pem = subprocess.run(["openssl", "genrsa", "2048"], capture_output=True, check=True).stdout
    return base64.b64encode(pem).decode()


# --------------------------------------------------------------------------
# signing
# --------------------------------------------------------------------------


def test_a_real_key_produces_a_three_part_rs256_jwt(rsa_key_b64):
    token = dispatch_app._app_jwt(rsa_key_b64, "4259746", now=1_700_000_000)
    assert token is not None
    header, claims, signature = token.split(".")

    def unpad(part):
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

    assert json.loads(unpad(header)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(unpad(claims)) == {
        "iat": 1_700_000_000 - 60,
        "exp": 1_700_000_000 + 540,
        "iss": "4259746",
    }
    assert len(unpad(signature)) == 256  # RS256 over a 2048-bit key


def test_a_value_that_is_not_base64_yields_no_jwt():
    assert dispatch_app._app_jwt("-----BEGIN RSA PRIVATE KEY-----", "1") is None


def test_base64_of_something_that_is_not_a_key_yields_no_jwt():
    assert dispatch_app._app_jwt(base64.b64encode(b"not a key").decode(), "1") is None


def test_the_key_reaches_neither_argv_nor_the_child_environment(rsa_key_b64, monkeypatch):
    """The one property that makes a private key in an environment variable survivable.

    argv is visible in `ps` to every process on the machine; a child's
    environment is visible to the child. The key travels on a dedicated file
    descriptor instead, so neither carries it.
    """
    pem = base64.b64decode(rsa_key_b64)
    seen = {}
    real_popen = subprocess.Popen

    def spy(cmd, **kwargs):
        seen["argv"] = cmd
        seen["env"] = kwargs.get("env")
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr(dispatch_app.subprocess, "Popen", spy)
    monkeypatch.setenv(config.DISPATCH_APP_KEY_ENV, rsa_key_b64)
    assert dispatch_app._app_jwt(rsa_key_b64, "1") is not None

    blob = " ".join(seen["argv"])
    assert pem.decode() not in blob
    assert rsa_key_b64 not in blob
    assert "PRIVATE KEY" not in blob
    # Not just the whole key: ANY run of it is key material, and a leak of a
    # fragment is a leak. Sixteen characters is short enough that no plausible
    # partial disclosure slips under it and long enough that a chunk of base64
    # cannot collide with an argument by accident.
    body = "".join(pem.decode().splitlines()[1:-1])
    fragments = [body[i : i + 16] for i in range(0, len(body) - 16, 16)]
    assert fragments, "the key body was not long enough to fragment"
    assert not [f for f in fragments if f in blob]
    assert list(seen["env"]) == ["PATH"]
    assert config.DISPATCH_APP_KEY_ENV not in seen["env"]


def test_the_signer_reports_failure_rather_than_raising_when_openssl_is_absent(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no openssl")

    monkeypatch.setattr(dispatch_app.subprocess, "Popen", boom)
    assert dispatch_app._sign_rs256(b"payload", b"key") is None


# --------------------------------------------------------------------------
# read_reach — every non-answer is a reason, never a verdict
# --------------------------------------------------------------------------

_INSTALLATION = {
    "permissions": {"actions": "write", "contents": "write", "metadata": "read"},
    "repository_selection": "all",
    "suspended_at": None,
}


def _api(responses):
    """Replay a list of (status, body) in call order, recording the calls."""
    calls = []

    def fake(path, bearer, method="GET", body=None):
        calls.append((method, path))
        return responses[len(calls) - 1]

    fake.calls = calls
    return fake


def test_an_absent_credential_is_a_reason_not_a_verdict():
    answer = read_reach(private_key_b64=None)
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-credential-absent"
    assert config.DISPATCH_APP_KEY_ENV in answer.message


def test_an_unusable_key_is_a_reason(monkeypatch):
    answer = read_reach(private_key_b64="not-base64!!", app_id="1", installation_id="2")
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-key-unusable"


@pytest.mark.parametrize("status", [401, 404, 500, None])
def test_every_unreadable_installation_is_a_reason(rsa_key_b64, monkeypatch, status):
    """401 and 404 are deliberately the SAME answer.

    404 is returned both for an app id this build has wrong and for an App that
    has been uninstalled, and the response cannot tell them apart. Guessing
    between them would put a verdict on a repository that has no defect.
    """
    monkeypatch.setattr(dispatch_app, "_api", _api([(status, None)]))
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-installation-unreadable"


def test_an_installation_with_no_readable_permissions_is_a_reason(rsa_key_b64, monkeypatch):
    monkeypatch.setattr(
        dispatch_app, "_api", _api([(200, {"repository_selection": "all", "permissions": None})])
    )
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-installation-unreadable"


def test_an_all_installation_is_read_with_no_token_minted(rsa_key_b64, monkeypatch):
    """The live shape, and the design property: one read, nothing minted."""
    fake = _api([(200, _INSTALLATION)])
    monkeypatch.setattr(dispatch_app, "_api", fake)
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppReach)
    assert answer.repository_selection == "all"
    assert answer.repositories is None
    assert answer.suspended is False
    assert [method for method, _ in fake.calls] == ["GET"]


def test_a_suspended_installation_is_read_and_reported(rsa_key_b64, monkeypatch):
    monkeypatch.setattr(
        dispatch_app,
        "_api",
        _api([(200, {**_INSTALLATION, "suspended_at": "2026-09-01T00:00:00Z"})]),
    )
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppReach)
    assert answer.suspended is True


# --------------------------------------------------------------------------
# the `selected` path — mints, and always revokes
# --------------------------------------------------------------------------

_SELECTED = {**_INSTALLATION, "repository_selection": "selected"}


def test_a_selected_installation_mints_a_metadata_only_token_and_revokes_it(
    rsa_key_b64, monkeypatch
):
    """The whole of the extra capability this check takes on, in one test.

    The token is DOWN-SCOPED at mint: nothing but `metadata: read`, which
    reaches this listing and nothing else. Measured against the live API
    2026-09-11 — the down-scoped token answers 403 to a private repository's
    `actions/runs` where the full installation token answers 200.
    """
    bodies = []

    def fake(path, bearer, method="GET", body=None):
        bodies.append((method, path, body))
        if method == "POST":
            return 201, {"token": "ghs_x"}
        if method == "DELETE":
            return 204, None
        if path.startswith("/installation/repositories"):
            return 200, {
                "total_count": 1,
                "repositories": [{"full_name": "AlobarQuest/Orchestrator"}],
            }
        return 200, _SELECTED

    monkeypatch.setattr(dispatch_app, "_api", fake)
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppReach)
    # lower-cased on the way in, so a slug's case cannot decide reach
    assert answer.repositories == frozenset({"alobarquest/orchestrator"})
    mint = next(b for m, _p, b in bodies if m == "POST")
    assert mint == {"permissions": {"metadata": "read"}}
    assert ("DELETE", "/installation/token", None) in bodies


def test_the_minted_token_is_revoked_even_when_the_listing_fails(rsa_key_b64, monkeypatch):
    """A failure part-way through must not leave a live credential behind."""
    calls = []

    def fake(path, bearer, method="GET", body=None):
        calls.append((method, path))
        if method == "POST":
            return 201, {"token": "ghs_x"}
        if method == "DELETE":
            return 204, None
        if path.startswith("/installation/repositories"):
            return 500, None
        return 200, _SELECTED

    monkeypatch.setattr(dispatch_app, "_api", fake)
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-repositories-unreadable"
    assert ("DELETE", "/installation/token") in calls


def test_a_mint_that_fails_is_a_reason_and_revokes_nothing(rsa_key_b64, monkeypatch):
    calls = []

    def fake(path, bearer, method="GET", body=None):
        calls.append((method, path))
        if method == "POST":
            return 403, None
        return 200, _SELECTED

    monkeypatch.setattr(dispatch_app, "_api", fake)
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-token-unmintable"
    assert not any(method == "DELETE" for method, _ in calls)


def test_a_selected_listing_follows_pages(rsa_key_b64, monkeypatch):
    pages = {1: [{"full_name": f"o/r{i}"} for i in range(100)], 2: [{"full_name": "o/last"}]}

    def fake(path, bearer, method="GET", body=None):
        if method == "POST":
            return 201, {"token": "ghs_x"}
        if method == "DELETE":
            return 204, None
        if path.startswith("/installation/repositories"):
            page = int(path.rsplit("page=", 1)[1])
            return 200, {"total_count": 101, "repositories": pages.get(page, [])}
        return 200, _SELECTED

    monkeypatch.setattr(dispatch_app, "_api", fake)
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppReach)
    assert answer.repositories is not None
    assert len(answer.repositories) == 101
    assert "o/last" in answer.repositories


def test_a_listing_shorter_than_the_stated_total_is_a_reason_not_a_shorter_grant(
    rsa_key_b64, monkeypatch
):
    """A SHORT LIST IS NOT A SHORTER GRANT, and the caller turns a missing entry into
    `violation` — which is the one thing a measurement problem must never become.

    GitHub states `total_count`, so a listing that stopped early, a page bound that
    was hit, or a name this build could not read is DETECTABLE rather than assumed.
    """

    def fake(path, bearer, method="GET", body=None):
        if method == "POST":
            return 201, {"token": "ghs_x"}
        if method == "DELETE":
            return 204, None
        if path.startswith("/installation/repositories"):
            return 200, {"total_count": 9, "repositories": [{"full_name": "o/only"}]}
        return 200, _SELECTED

    monkeypatch.setattr(dispatch_app, "_api", fake)
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-repositories-incomplete"


def test_a_listing_with_no_stated_total_is_a_reason(rsa_key_b64, monkeypatch):
    """Without the count there is nothing to check the listing against, so the
    listing cannot be believed."""

    def fake(path, bearer, method="GET", body=None):
        if method == "POST":
            return 201, {"token": "ghs_x"}
        if method == "DELETE":
            return 204, None
        if path.startswith("/installation/repositories"):
            return 200, {"repositories": [{"full_name": "o/only"}]}
        return 200, _SELECTED

    monkeypatch.setattr(dispatch_app, "_api", fake)
    answer = read_reach(private_key_b64=rsa_key_b64, app_id="1", installation_id="2")
    assert isinstance(answer, AppUnreadable)
    assert answer.detail_id == "factory.app-repositories-incomplete"


# --------------------------------------------------------------------------
# memoization
# --------------------------------------------------------------------------


def test_the_reach_is_read_once_for_a_whole_sweep():
    calls = []
    reach = memoizing_reach(read=lambda: calls.append(1) or AppReach({}, "all", False, None))
    for _ in range(6):
        reach()
    assert len(calls) == 1


def test_a_failure_is_not_cached():
    """A cached failure turns one transient blip into every repository in the
    sweep reporting `unknown` for the rest of the night — the defect
    `memoizing_gh` already carries a note about."""
    calls = []
    reach = memoizing_reach(
        read=lambda: calls.append(1) or AppUnreadable("factory.app-x", "m", "f")
    )
    for _ in range(3):
        assert isinstance(reach(), AppUnreadable)
    assert len(calls) == 3
