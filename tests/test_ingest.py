"""The one route that writes, and what it refuses.

A reading that arrives is not a reading that was fetched. The
cases here are mostly about what a caller must not be able to
talk this route into: a provenance it did not earn, a time it
chose, a window that says nothing, or a route that was never
opened at all.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_usage import api, config, contract, ingest, store


def _state():
    directory = tempfile.mkdtemp()
    return directory, {"environ": {config.STATE_ENV: directory}}


def _serve(kwargs):
    server = api.build_server(
        "127.0.0.1",
        0,
        database_path=config.database_path(**kwargs),
        state_kwargs=kwargs,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _post(port, document, token="", origin=None, raw=None):
    body = raw if raw is not None else json.dumps(document).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:%d/api/v1/ingest" % port,
        data=body,
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    if origin:
        request.add_header("Origin", origin)
    return urllib.request.urlopen(request)


A_READING = {
    "provider": "grok",
    "answered": True,
    "windows": [{"label": "2-hour", "used_percent": 25.0, "remaining": 105.0, "limit": 140.0}],
}


class TestTheToken:
    def test_a_missing_token_file_leaves_the_route_closed(self):
        _, kwargs = _state()
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            with pytest.raises(urllib.error.HTTPError) as failure:
                _post(port, A_READING, token="anything")
            # Not 401: there is no credential that would work,
            # and saying "unauthorised" would invite guessing.
            assert failure.value.code == 503
        finally:
            server.shutdown()
            server.server_close()

    def test_a_wrong_token_is_refused(self):
        _, kwargs = _state()
        ingest.create_token(**kwargs)
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            with pytest.raises(urllib.error.HTTPError) as failure:
                _post(port, A_READING, token="not-the-token")
            assert failure.value.code == 401
            with pytest.raises(urllib.error.HTTPError) as absent:
                _post(port, A_READING)
            assert absent.value.code == 401
        finally:
            server.shutdown()
            server.server_close()

    def test_the_token_file_is_private_and_rotates(self):
        _, kwargs = _state()
        first = ingest.create_token(**kwargs)
        path = config.ingest_token_path(**kwargs)
        assert (path.stat().st_mode & 0o777) == 0o600
        assert ingest.read_token(**kwargs) == first
        second = ingest.create_token(**kwargs)
        assert second != first
        # Rotation is revocation: the old secret stops working.
        assert not ingest.authorised("Bearer " + first, ingest.read_token(**kwargs))
        assert ingest.authorised("Bearer " + second, ingest.read_token(**kwargs))

    def test_a_malformed_authorization_header_is_not_authorised(self):
        assert not ingest.authorised("Basic abc", "abc")
        assert not ingest.authorised("Bearer ", "abc")
        assert not ingest.authorised(None, "abc")
        assert not ingest.authorised("Bearer abc", None)


class TestWhatItRefusesToBelieve:
    def test_an_ingested_reading_cannot_claim_it_came_from_the_api(self):
        document = dict(A_READING, source=contract.SOURCE_API)
        reading = ingest.observation(document)
        assert reading.source == contract.SOURCE_BROWSER_INGEST

    def test_a_caller_cannot_choose_when_the_reading_was_taken(self):
        # Backdating would drop a reading into a gap in the
        # history; postdating would outrank a real fetch.
        document = dict(A_READING, collected_at=1.0)
        reading = ingest.observation(document, now=5000.0)
        assert reading.collected_at == 5000.0

    def test_an_unknown_provider_is_refused(self):
        with pytest.raises(ingest.Refused) as refusal:
            ingest.observation(dict(A_READING, provider="nope"))
        assert refusal.value.status == 404

    def test_answered_without_a_window_is_refused(self):
        # Missing is never zero. An answered reading carrying no
        # window is not a provider at zero percent.
        with pytest.raises(ingest.Refused):
            ingest.observation(dict(A_READING, windows=[]))
        with pytest.raises(ingest.Refused):
            ingest.observation({"provider": "grok", "answered": True})

    def test_a_free_text_error_is_refused(self):
        with pytest.raises(ingest.Refused):
            ingest.observation({"provider": "grok", "answered": False, "error": "it did not work"})

    def test_a_closed_error_code_is_accepted_and_carries_this_source(self):
        reading = ingest.observation(
            {
                "provider": "grok",
                "answered": False,
                "error": contract.ERROR_BROWSER_SESSION_MISSING,
            }
        )
        assert not reading.answered
        assert reading.error == contract.ERROR_BROWSER_SESSION_MISSING
        assert reading.source == contract.SOURCE_BROWSER_INGEST
        assert reading.windows == ()

    @pytest.mark.parametrize(
        "window",
        [
            {"label": "", "used_percent": 1.0},
            {"label": "2-hour"},
            {"label": "2-hour", "used_percent": "lots"},
            {"label": "2-hour", "used_percent": True},
            {"label": "2-hour", "used_percent": float("inf")},
            {"label": "2-hour", "used_percent": 1.0, "scope": "invented"},
        ],
    )
    def test_a_window_outside_the_contract_is_refused(self, window):
        with pytest.raises(ingest.Refused):
            ingest.observation(dict(A_READING, windows=[window]))

    def test_a_reading_survives_with_every_field_it_carried(self):
        reading = ingest.observation(A_READING)
        window = reading.windows[0]
        assert window.label == "2-hour"
        assert window.used_percent == 25.0
        assert window.remaining == 105.0
        assert window.limit == 140.0
        assert window.scope == contract.SCOPE_ACCOUNT


class TestTheRoute:
    def test_a_posted_reading_is_stored_and_readable(self):
        _, kwargs = _state()
        token = ingest.create_token(**kwargs)
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            with _post(port, A_READING, token=token) as response:
                assert response.status == 202
            connection = store.connect(**kwargs)
            document = store.latest(connection, "grok")
            connection.close()
            assert document["answered"]
            assert document["source"] == contract.SOURCE_BROWSER_INGEST
            assert document["windows"][0]["limit"] == 140.0
        finally:
            server.shutdown()
            server.server_close()

    def test_an_oversized_body_is_refused_before_it_is_parsed(self):
        _, kwargs = _state()
        token = ingest.create_token(**kwargs)
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            with pytest.raises(urllib.error.HTTPError) as failure:
                _post(port, None, token=token, raw=b"x" * (ingest.MAX_BODY_BYTES + 1))
            assert failure.value.code == 413
        finally:
            server.shutdown()
            server.server_close()

    def test_a_second_reading_moments_later_is_refused(self):
        _, kwargs = _state()
        token = ingest.create_token(**kwargs)
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            with _post(port, A_READING, token=token) as response:
                assert response.status == 202
            with pytest.raises(urllib.error.HTTPError) as failure:
                _post(port, A_READING, token=token)
            assert failure.value.code == 429
        finally:
            server.shutdown()
            server.server_close()

    def test_malformed_json_is_refused(self):
        _, kwargs = _state()
        token = ingest.create_token(**kwargs)
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            with pytest.raises(urllib.error.HTTPError) as failure:
                _post(port, None, token=token, raw=b"{not json")
            assert failure.value.code == 400
        finally:
            server.shutdown()
            server.server_close()

    def test_no_other_path_accepts_a_post(self):
        _, kwargs = _state()
        ingest.create_token(**kwargs)
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            request = urllib.request.Request(
                "http://127.0.0.1:%d/api/v1/snapshot" % port, data=b"{}", method="POST"
            )
            with pytest.raises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(request)
            assert failure.value.code == 404
        finally:
            server.shutdown()
            server.server_close()


class TestTheOriginAllowlist:
    def test_no_origin_is_allowed_by_default(self):
        assert ingest.allowed_origins({}) == ()

    def test_only_a_named_origin_is_answered(self):
        environ = {"AGENT_USAGE_INGEST_ORIGINS": "https://grok.com, https://x.ai"}
        assert ingest.allowed_origins(environ) == ("https://grok.com", "https://x.ai")

    def test_a_preflight_from_an_unnamed_origin_is_refused(self):
        directory, kwargs = _state()
        kwargs["environ"]["AGENT_USAGE_INGEST_ORIGINS"] = "https://grok.com"
        ingest.create_token(**kwargs)
        server = _serve(kwargs)
        port = server.server_address[1]
        try:
            allowed = urllib.request.Request(
                "http://127.0.0.1:%d/api/v1/ingest" % port, method="OPTIONS"
            )
            allowed.add_header("Origin", "https://grok.com")
            with urllib.request.urlopen(allowed) as response:
                assert response.status == 204
                assert response.headers.get("Access-Control-Allow-Origin") == "https://grok.com"
            # A wildcard here would let any page the operator
            # visits post a reading.
            other = urllib.request.Request(
                "http://127.0.0.1:%d/api/v1/ingest" % port, method="OPTIONS"
            )
            other.add_header("Origin", "https://evil.example")
            with pytest.raises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(other)
            assert failure.value.code == 403
            assert failure.value.headers.get("Access-Control-Allow-Origin") is None
        finally:
            server.shutdown()
            server.server_close()


class TestTheBookmarklet:
    def _source(self):
        return (
            Path(__file__).resolve().parent.parent / "scripts" / "bookmarklet_grok.js"
        ).read_text(encoding="utf-8")

    def test_it_carries_no_secret(self):
        source = self._source()
        assert "__DASHBOARD__" in source
        # The fragment hand-off exists so this script needs no
        # credential of its own. If a token ever appears here it
        # is a secret living in a bookmark, which is the thing
        # the design avoids.
        assert "Bearer" not in source
        assert "TOKEN" not in source
        assert "authorization" not in source.lower()

    def test_it_hands_over_by_fragment_rather_than_posting(self):
        source = self._source()
        # The only fetch is the same origin read of the
        # provider's own endpoint.
        assert source.count("fetch(") == 1
        assert "/rest/rate-limits" in source
        assert "#reading=" in source

    def test_it_reports_a_signed_out_session_rather_than_its_allowance(self):
        source = self._source()
        # Signed out, grok answers with a small anonymous
        # allowance. Carrying that over would report it as the
        # account's.
        assert "browser_session_missing" in source

    def test_building_it_substitutes_the_dashboard(self):
        import sys

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "scripts"))
        import make_bookmarklet

        built = make_bookmarklet.build(
            'const D="__DASHBOARD__";', "https://usage.example/"
        )
        assert built.startswith("javascript:")
        assert "__DASHBOARD__" not in built
        # The trailing slash is dropped so the fragment is not
        # appended to a doubled path.
        assert "https%3A//usage.example%22" in built or "usage.example" in built

    def test_a_relative_dashboard_is_refused(self):
        import sys

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "scripts"))
        import make_bookmarklet

        with pytest.raises(SystemExit):
            make_bookmarklet.main(["--dashboard", "usage.example"])


def test_the_source_vocabulary_stayed_closed():
    # A quiet addition to the sources is a quiet addition to
    # what a reader is being asked to trust.
    assert contract.SOURCES == (
        contract.SOURCE_API,
        contract.SOURCE_BROWSER_JSON,
        contract.SOURCE_BROWSER_TEXT,
        contract.SOURCE_BROWSER_INGEST,
    )
