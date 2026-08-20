"""What renewal must do, and what it must refuse to do.

The refresh token is rotated on use, so most of these pin the
failure paths. A renewal that half works is the one outcome
that cannot be recovered from without a human signing in
again.
"""

import json
import os
import stat
import urllib.error

import pytest

from agent_usage import contract
from agent_usage.providers import claude, credentials, renewal

NOW = 1_700_000_000.0
HOUR_MS = 3_600_000
# 2100-01-01, so a credential written as renewed reads as
# renewed against the real clock the finder consults.
FAR_FUTURE_MS = 4_102_444_800_000


def write_credential(
    home, *, access="old-access", refresh="old-refresh", expires_at=None, refresh_expires_at=None
):
    path = home / ".claude" / ".credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    oauth = {"accessToken": access, "refreshToken": refresh}
    if expires_at is not None:
        oauth["expiresAt"] = expires_at
    if refresh_expires_at is not None:
        oauth["refreshTokenExpiresAt"] = refresh_expires_at
    document = {"claudeAiOauth": oauth, "somethingElse": {"keep": True}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)
    os.chmod(path, 0o600)
    return path


def read_credential(home):
    path = home / ".claude" / ".credentials.json"
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_returning(payload, seen=None):
    def opener(request, timeout=None):
        if seen is not None:
            seen.append(request)
        return FakeResponse(payload)

    return opener


def opener_failing(error=None):
    def opener(request, timeout=None):
        raise error or urllib.error.URLError("nope")

    return opener


def test_a_renewal_stores_the_rotated_refresh_token(tmp_path):
    # The token that bought this answer is already dead. If the
    # new one is not written, the account cannot renew again.
    write_credential(tmp_path, expires_at=int((NOW - 60) * 1000))
    opener = opener_returning(
        {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 28800,
            "refresh_token_expires_in": 2_592_000,
        }
    )

    assert renewal.renew_claude(home=tmp_path, opener=opener, now=NOW) is True

    stored = read_credential(tmp_path)["claudeAiOauth"]
    assert stored["accessToken"] == "new-access"
    assert stored["refreshToken"] == "new-refresh"
    assert stored["expiresAt"] == int((NOW + 28800) * 1000)
    assert stored["refreshTokenExpiresAt"] == int((NOW + 2_592_000) * 1000)


def test_unrelated_keys_survive_a_renewal(tmp_path):
    write_credential(tmp_path)
    opener = opener_returning({"access_token": "new-access"})

    assert renewal.renew_claude(home=tmp_path, opener=opener, now=NOW) is True
    assert read_credential(tmp_path)["somethingElse"] == {"keep": True}


def test_the_renewed_file_is_no_more_readable_than_the_old_one(tmp_path):
    path = write_credential(tmp_path)
    opener = opener_returning({"access_token": "new-access"})

    renewal.renew_claude(home=tmp_path, opener=opener, now=NOW)

    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_a_failed_endpoint_leaves_the_credential_untouched(tmp_path):
    write_credential(tmp_path)
    before = read_credential(tmp_path)

    assert renewal.renew_claude(home=tmp_path, opener=opener_failing(), now=NOW) is False
    assert read_credential(tmp_path) == before


def test_an_answer_without_an_access_token_changes_nothing(tmp_path):
    write_credential(tmp_path)
    before = read_credential(tmp_path)
    opener = opener_returning({"refresh_token": "new-refresh"})

    assert renewal.renew_claude(home=tmp_path, opener=opener, now=NOW) is False
    # Storing the rotated token without the access token it came
    # with would leave a credential that cannot read anything.
    assert read_credential(tmp_path) == before


def test_a_missing_refresh_token_is_not_an_attempt(tmp_path):
    path = tmp_path / ".claude" / ".credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"claudeAiOauth": {"accessToken": "only-access"}}, handle)

    calls = []
    assert renewal.renew_claude(home=tmp_path, opener=opener_returning({}, calls), now=NOW) is False
    assert calls == []


def test_an_expired_refresh_token_is_not_spent(tmp_path):
    # Asking anyway costs a request to be told what the file
    # already says.
    write_credential(tmp_path, refresh_expires_at=int((NOW - 1) * 1000))

    calls = []
    assert (
        renewal.renew_claude(
            home=tmp_path, opener=opener_returning({"access_token": "x"}, calls), now=NOW
        )
        is False
    )
    assert calls == []


def test_a_missing_file_is_not_an_error(tmp_path):
    assert renewal.renew_claude(home=tmp_path, opener=opener_failing(), now=NOW) is False


def test_the_second_endpoint_is_tried_when_the_first_refuses(tmp_path):
    write_credential(tmp_path)
    seen = []

    def opener(request, timeout=None):
        seen.append(request.full_url)
        if len(seen) == 1:
            raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)
        return FakeResponse({"access_token": "new-access"})

    assert renewal.renew_claude(home=tmp_path, opener=opener, now=NOW) is True
    assert seen == list(renewal.TOKEN_URLS)


def test_the_request_names_itself(tmp_path):
    # The endpoint sits behind a filter that rejects the default
    # Python user agent with a 403 that looks like a credential
    # failure and is not one.
    write_credential(tmp_path)
    seen = []
    renewal.renew_claude(
        home=tmp_path, opener=opener_returning({"access_token": "a"}, seen), now=NOW
    )

    agent = seen[0].get_header("User-agent")
    assert agent and "Python-urllib" not in agent


def test_the_grant_is_a_refresh_grant(tmp_path):
    write_credential(tmp_path, refresh="the-refresh")
    seen = []
    renewal.renew_claude(
        home=tmp_path, opener=opener_returning({"access_token": "a"}, seen), now=NOW
    )

    sent = json.loads(seen[0].data.decode("utf-8"))
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "the-refresh"
    assert sent["client_id"] == renewal.CLIENT_ID


def test_an_expired_credential_is_renewed_before_it_is_reported(tmp_path, monkeypatch):
    write_credential(tmp_path, expires_at=int((NOW - 60) * 1000))

    def renew(home=None, now=None):
        # The finder reads the wall clock rather than the moment
        # passed to collect, so a renewal has to land in the
        # future of the real clock to read as renewed.
        write_credential(home, access="fresh", expires_at=FAR_FUTURE_MS)
        return True

    monkeypatch.setattr(renewal, "renew_claude", renew)
    monkeypatch.setattr(
        claude.base,
        "get_json",
        lambda url, headers: {"five_hour": {"utilization": 12.0}},
    )

    observation = claude.collect(now=NOW, home=tmp_path, runner=lambda *a, **k: None)

    assert observation.error is None
    assert observation.windows[0].used_percent == 12.0


def test_a_credential_that_cannot_be_renewed_is_still_reported_expired(tmp_path, monkeypatch):
    write_credential(tmp_path, expires_at=int((NOW - 60) * 1000))
    monkeypatch.setattr(renewal, "renew_claude", lambda home=None, now=None: False)

    observation = claude.collect(now=NOW, home=tmp_path, runner=lambda *a, **k: None)

    assert observation.error == contract.ERROR_CREDENTIAL_EXPIRED


def test_a_keychain_credential_is_never_renewed_from_a_file(monkeypatch, tmp_path):
    # The file this could write is not the store the client
    # reads back, so a renewal here would report success and
    # change nothing the client sees.
    calls = []
    monkeypatch.setattr(
        renewal, "renew_claude", lambda home=None, now=None: calls.append(1) or True
    )
    keychain = credentials.Credential(
        "claude", present=True, expired=True, token="t", origin="keychain"
    )

    result = claude._renewed(keychain, NOW, home=tmp_path)

    assert result is keychain
    assert calls == []


@pytest.mark.parametrize("payload", [None, [], "text", 12])
def test_an_answer_of_the_wrong_shape_changes_nothing(tmp_path, payload):
    write_credential(tmp_path)
    before = read_credential(tmp_path)

    assert renewal.renew_claude(home=tmp_path, opener=opener_returning(payload), now=NOW) is False
    assert read_credential(tmp_path) == before
