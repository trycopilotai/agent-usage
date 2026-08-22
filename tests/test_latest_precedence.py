"""Which reading is the current one when two routes disagree.

A provider can be read more than one way, and the routes do
not agree. Grok publishes subscription usage only to a signed
in browser; the API route that also runs against it answers
`no_allowance` every sixty seconds. Newest-wins made the
non-answer the winner every time, so a reading a person took
by hand was gone within a minute of arriving.
"""

from __future__ import annotations

import tempfile

from agent_usage import config, contract, store


def _kwargs():
    return {"environ": {config.STATE_ENV: tempfile.mkdtemp()}}


def _answered(moment: float) -> contract.Observation:
    return contract.Observation(
        provider="grok",
        collected_at=moment,
        source=contract.SOURCE_BROWSER_INGEST,
        windows=(
            contract.Window(
                label="grok-4 2-hour",
                used_percent=25.0,
                limit=140.0,
                scope=contract.SCOPE_FEATURE,
            ),
        ),
    )


def _unanswered(moment: float) -> contract.Observation:
    return contract.Observation(
        provider="grok",
        collected_at=moment,
        error=contract.ERROR_NO_ALLOWANCE,
    )


class TestWhichReadingIsCurrent:
    def test_a_non_answer_does_not_bury_a_live_measurement(self):
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            store.record(connection, _answered(1000.0))
            # The sampler, one minute later, reading the route
            # that cannot see a subscription.
            store.record(connection, _unanswered(1060.0))

            document = store.latest(connection, "grok", now=1070.0)
            assert document is not None
            assert document["answered"]
            assert document["windows"][0]["limit"] == 140.0
        finally:
            connection.close()

    def test_the_measurement_outlives_the_live_window(self):
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            store.record(connection, _answered(1000.0))
            store.record(connection, _unanswered(1060.0))

            # Twenty minutes on. The reading is no longer live,
            # but this tool would still show it and call it
            # cached, and a reading it would still show beats a
            # route that cannot see the subscription at all.
            document = store.latest(connection, "grok", now=1000.0 + 20 * 60)
            assert document is not None
            assert document["answered"]
        finally:
            connection.close()

    def test_a_measurement_this_tool_would_call_stale_stops_winning(self):
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            store.record(connection, _answered(1000.0))
            store.record(connection, _unanswered(1060.0))

            # Past the cached window the measurement is no
            # longer something this tool vouches for at all, so
            # hiding a current failure behind it would be the
            # worse lie.
            moment = 1000.0 + store.CACHED_SECONDS + 1.0
            document = store.latest(connection, "grok", now=moment)
            assert document is not None
            assert not document["answered"]
        finally:
            connection.close()

    def test_precedence_ends_exactly_where_this_tool_stops_vouching(self):
        # Stated against freshness_of rather than against the
        # number, so the two cannot drift apart: everything the
        # precedence rule lets through is something this tool
        # would still put a freshness label on other than stale.
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            store.record(connection, _answered(1000.0))
            store.record(connection, _unanswered(1060.0))

            for offset in (0.0, 60.0, 20 * 60.0, store.CACHED_SECONDS):
                moment = 1000.0 + offset
                document = store.latest(connection, "grok", now=moment)
                assert document is not None
                assert document["answered"], offset
                assert (
                    store.freshness_of(document, now=moment)
                    != contract.FRESHNESS_STALE
                ), offset
        finally:
            connection.close()

    def test_a_remembered_reading_is_not_served_as_live(self):
        # The reading wins on precedence long after it stopped
        # being live. Whoever serves it must say so, or this
        # change would have bought grok a number at the cost of
        # the rule that stale never appears live.
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            store.record(connection, _answered(1000.0))
            store.record(connection, _unanswered(1060.0))

            moment = 1000.0 + 20 * 60
            document = store.latest(connection, "grok", now=moment)
            assert document is not None
            assert store.freshness_of(document, now=moment) == (
                contract.FRESHNESS_CACHED
            )
        finally:
            connection.close()

    def test_a_newer_answer_always_wins(self):
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            store.record(connection, _unanswered(1000.0))
            store.record(connection, _answered(1060.0))

            document = store.latest(connection, "grok", now=1070.0)
            assert document is not None
            assert document["answered"]
        finally:
            connection.close()

    def test_a_provider_that_only_ever_failed_still_reports_failing(self):
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            store.record(connection, _unanswered(1000.0))

            document = store.latest(connection, "grok", now=1010.0)
            assert document is not None
            assert not document["answered"]
            assert document["error"] == contract.ERROR_NO_ALLOWANCE
        finally:
            connection.close()

    def test_no_reading_at_all_is_still_none(self):
        kwargs = _kwargs()
        connection = store.connect(**kwargs)
        try:
            assert store.latest(connection, "grok", now=1.0) is None
        finally:
            connection.close()
