"""What a stored reading loses on the way back out.

`report` does not re-read a provider; it rebuilds the last
stored reading and renders that. So every field the renderer
acts on has to survive the round trip, and the ones that
decide something -- which window governs, where the number
came from, whether it is still current -- are the ones whose
loss is invisible, because the defaults are plausible.
"""

from __future__ import annotations

from agent_usage import cli, contract


A_CODEX_ROW = {
    "collected_at": 1000.0,
    "answered": True,
    "source": contract.SOURCE_BROWSER_INGEST,
    "freshness": contract.FRESHNESS_STALE,
    "windows": [
        {
            "label": "overall 1-week",
            "used_percent": 7.0,
            "scope": contract.SCOPE_ACCOUNT,
        },
        {
            "label": "GPT-5.3-Codex-Spark 1-week",
            "used_percent": 100.0,
            "scope": contract.SCOPE_FEATURE,
        },
    ],
}


class TestWhatSurvivesTheRoundTrip:
    def test_the_account_pool_still_binds_after_rehydration(self):
        # The whole point of scope. Losing it on the way back
        # out puts a spent per-feature pool in charge of a
        # provider it does not govern, and the report says a
        # provider is finished when it is at seven percent.
        reading = cli._rehydrate("codex", A_CODEX_ROW)
        binding = reading.binding_window()
        assert binding is not None
        assert binding.label == "overall 1-week"
        assert binding.used_percent == 7.0

    def test_a_window_keeps_its_limit_and_remaining(self):
        row = {
            "collected_at": 1.0,
            "windows": [
                {
                    "label": "grok-4 2-hour",
                    "used_percent": 25.0,
                    "remaining": 105.0,
                    "limit": 140.0,
                    "scope": contract.SCOPE_FEATURE,
                }
            ],
        }
        window = cli._rehydrate("grok", row).windows[0]
        assert window.limit == 140.0
        assert window.remaining == 105.0
        assert window.scope == contract.SCOPE_FEATURE

    def test_an_ingested_reading_does_not_claim_it_was_fetched(self):
        # Provenance is the reader's only way to tell a number
        # someone handed in from one this tool went and got.
        reading = cli._rehydrate("codex", A_CODEX_ROW)
        assert reading.source == contract.SOURCE_BROWSER_INGEST

    def test_a_stale_reading_does_not_come_back_live(self):
        reading = cli._rehydrate("codex", A_CODEX_ROW)
        assert reading.freshness == contract.FRESHNESS_STALE

    def test_a_row_written_before_scope_existed_reads_as_account(self):
        # Every adapter emitted account-wide windows then, so
        # that is what an absent scope meant.
        row = {
            "collected_at": 1.0,
            "windows": [{"label": "5-hour", "used_percent": 4.0}],
        }
        assert cli._rehydrate("claude", row).windows[0].scope == contract.SCOPE_ACCOUNT

    def test_a_value_outside_the_closed_set_is_not_carried(self):
        # An unknown value would fail validation on the way
        # back out, taking the whole report with it.
        row = {
            "collected_at": 1.0,
            "source": "invented",
            "freshness": "invented",
            "windows": [{"label": "5-hour", "used_percent": 4.0, "scope": "invented"}],
        }
        reading = cli._rehydrate("claude", row)
        assert reading.source == contract.SOURCE_API
        assert reading.freshness == contract.FRESHNESS_LIVE
        assert reading.windows[0].scope == contract.SCOPE_ACCOUNT
        # And it is still a reading the contract accepts.
        reading.validate()
