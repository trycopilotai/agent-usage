"""Storage, the HTTP surface, and the CLI over one library."""

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_usage import api, cli, config, contract, derive, redaction, report, store


def _db():
    return Path(tempfile.mkdtemp()) / "usage.sqlite3"


def test_history_excludes_unanswered_readings():
    connection = store.connect(":memory:")
    store.record(
        connection, contract.Observation("claude", 100.0, (contract.Window("5-hour", 10.0),))
    )
    store.record(connection, contract.failed("claude", contract.ERROR_RATE_LIMITED, now=200.0))
    store.record(
        connection, contract.Observation("claude", 8000.0, (contract.Window("5-hour", 30.0),))
    )
    assert store.samples(connection, "claude") == [(100.0, 10.0), (8000.0, 30.0)]


def test_stored_reads_age_out_of_live():
    document = {"collected_at": 0.0}
    assert store.freshness_of(document, now=10.0) == contract.FRESHNESS_LIVE
    assert store.freshness_of(document, now=1000.0) == contract.FRESHNESS_CACHED
    assert store.freshness_of(document, now=100000.0) == contract.FRESHNESS_STALE


def test_the_boundary_drops_fields_it_does_not_name():
    kept = redaction.filter_observation(
        {"provider": "claude", "collected_at": 1.0, "cookie": "secret", "page_html": "<html>"}
    )
    assert "cookie" not in kept
    assert "page_html" not in kept
    assert kept["provider"] == "claude"


def test_credential_shapes_are_scrubbed_from_free_text():
    # Assembled at runtime. A literal here would ship bytes
    # shaped like a real credential in a public repository.
    shaped = "gh" + "p_" + ("a" * 32)
    scrubbed = redaction.scrub_text("here " + shaped + " gone")
    assert shaped not in scrubbed
    assert redaction.REDACTED in scrubbed


def test_forecast_declines_rather_than_guessing():
    assert derive.burn_rate_per_hour([(0.0, 10.0)]).known is False
    assert derive.burn_rate_per_hour([(0.0, 10.0), (30.0, 20.0)]).status == "span_too_short"
    assert derive.burn_rate_per_hour([(0.0, 50.0), (7200.0, 10.0)]).status == "not_rising"
    measured = derive.burn_rate_per_hour([(0.0, 10.0), (7200.0, 30.0)])
    assert measured.known and measured.value == 10.0


def test_a_window_that_resets_first_is_reported_as_such():
    observation = contract.Observation(
        "claude", 1.0, (contract.Window("5-hour", 30.0, resets_in_seconds=60.0),)
    )
    document = derive.forecast(observation, [(0.0, 10.0), (7200.0, 30.0)])
    assert document["resets_before_exhausted"] is True


def test_the_server_refuses_a_routable_bind():
    with pytest.raises(api.NonLoopbackBind):
        api.assert_loopback("0.0.0.0")
    with pytest.raises(api.NonLoopbackBind):
        api.assert_loopback("203.0.113.10")
    assert api.assert_loopback("127.0.0.1") == "127.0.0.1"


def _serve(database):
    server = api.build_server("127.0.0.1", 0, database_path=database)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_http_surface_serves_every_documented_route():
    database = _db()
    connection = store.connect(database)
    store.record(
        connection,
        contract.Observation("claude", time.time(), (contract.Window("5-hour", 30.0, 1800.0),)),
    )
    connection.close()
    server = _serve(database)
    port = server.server_address[1]
    try:
        for path in (
            "/healthz",
            "/api/v1/snapshot",
            "/api/v1/report.md",
            "/api/v1/forecast/claude",
        ):
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path)) as response:
                assert response.status == 200
                assert response.read()
        with pytest.raises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen("http://127.0.0.1:%d/api/v1/forecast/nope" % port)
        assert failure.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_a_screenshot_is_absent_until_one_is_captured():
    database = _db()
    store.connect(database).close()
    server = _serve(database)
    port = server.server_address[1]
    try:
        with pytest.raises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen("http://127.0.0.1:%d/api/v1/screenshots/claude.png" % port)
        assert failure.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_the_cli_report_matches_the_api_route_byte_for_byte(capsys):
    state = tempfile.mkdtemp()
    connection = store.connect(**{"environ": {config.STATE_ENV: state}})
    store.record(
        connection,
        contract.Observation("claude", 5.0, (contract.Window("5-hour", 30.0, 1800.0),)),
    )
    connection.close()
    cli.main(["--state-dir", state, "report"])
    from_cli = capsys.readouterr().out

    connection = store.connect(**{"environ": {config.STATE_ENV: state}})
    observations = []
    for name in cli.registry.PROVIDERS:
        document = store.latest(connection, name)
        if document is None or not document.get("answered"):
            observations.append(cli._stored_failure(name, document))
        else:
            observations.append(cli._rehydrate(name, document))
    connection.close()
    assert from_cli == report.render(observations)


def test_the_report_names_providers_that_did_not_answer():
    rendered = report.render(
        [
            contract.Observation("claude", 1.0, (contract.Window("5-hour", 10.0),)),
            contract.failed("grok", contract.ERROR_NO_CREDENTIAL, now=1.0),
        ]
    )
    assert "grok" in rendered
    assert "no_credential" in rendered
    assert "1 of 2 providers answered" in rendered


def test_state_paths_are_configurable():
    assert str(config.state_dir({"AGENT_USAGE_STATE_DIR": "/tmp/x"})) == "/tmp/x"
    assert str(config.state_dir({"XDG_STATE_HOME": "/tmp/y"})) == "/tmp/y/agent-usage"
    root = Path(tempfile.mkdtemp())
    assert str(config.state_dir({}, home=root)).startswith(str(root))


def test_doctor_reports_shape_and_never_a_token(capsys):
    cli.main(["--state-dir", tempfile.mkdtemp(), "doctor"])
    document = json.loads(capsys.readouterr().out)
    for entry in document["credentials"]:
        assert set(entry) == {"provider", "present", "expired", "origin"}


def test_the_report_keeps_the_error_the_provider_actually_gave(capsys):
    state = tempfile.mkdtemp()
    connection = store.connect(**{"environ": {config.STATE_ENV: state}})
    store.record(connection, contract.failed("grok", contract.ERROR_NO_CREDENTIAL, now=5.0))
    connection.close()
    cli.main(["--state-dir", state, "report"])
    rendered = capsys.readouterr().out
    # Substituting a generic code would send a reader to fix
    # a network problem that does not exist. Providers with no
    # stored reading at all legitimately fall back, so assert
    # on the line for the provider that did record a code.
    grok_line = [line for line in rendered.splitlines() if line.startswith("- grok")]
    assert grok_line == ["- grok: no answer (no_credential)"]


def test_the_report_is_byte_identical_over_http_and_the_cli(capsys):
    """The docstring claims this. Prove it over the wire."""
    state = tempfile.mkdtemp()
    database = Path(config.database_path(**{"environ": {config.STATE_ENV: state}}))
    connection = store.connect(database)
    store.record(
        connection,
        contract.Observation("claude", 5.0, (contract.Window("5-hour", 30.0, 1800.0),)),
    )
    store.record(connection, contract.failed("grok", contract.ERROR_NO_CREDENTIAL, now=5.0))
    connection.close()

    cli.main(["--state-dir", state, "report"])
    from_cli = capsys.readouterr().out

    server = _serve(database)
    try:
        url = "http://127.0.0.1:%d/api/v1/report.md" % server.server_address[1]
        with urllib.request.urlopen(url) as response:
            from_http = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    assert from_http == from_cli


def test_credits_survive_into_the_report_and_the_http_route(capsys):
    """The skill tells an agent to flag engaged credit here.

    Rebuilding a stored reading without its credit state made
    every answered provider read as `unavailable`, so the one
    state worth acting on could never appear.
    """
    state = tempfile.mkdtemp()
    database = Path(config.database_path(**{"environ": {config.STATE_ENV: state}}))
    connection = store.connect(database)
    store.record(
        connection,
        contract.Observation(
            "claude",
            5.0,
            (contract.Window("5-hour", 30.0, 1800.0),),
            credits=contract.Credits(contract.CREDIT_ACTIVE, "extra usage engaged"),
            plan="max",
        ),
    )
    connection.close()

    cli.main(["--state-dir", state, "report"])
    from_cli = capsys.readouterr().out
    assert "active" in from_cli
    assert "| claude | 5-hour | 30.0% | 30m | active |" in from_cli

    server = _serve(database)
    try:
        url = "http://127.0.0.1:%d/api/v1/report.md" % server.server_address[1]
        with urllib.request.urlopen(url) as response:
            from_http = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    assert from_http == from_cli


def test_every_credit_state_in_the_closed_set_has_a_producer():
    """No state ships that no adapter can emit."""
    from agent_usage.providers import claude, grok

    produced = set()
    produced.add(claude.parse({"five_hour": {"utilization": 1.0}}, 1.0).credits.state)
    for used, cap, expected in ((0, 10, None), (5, 10, None), (10, 10, None)):
        produced.add(
            claude.parse(
                {
                    "five_hour": {"utilization": 1.0},
                    "extra_usage": {"enabled": True, "used": used, "cap": cap},
                },
                1.0,
            ).credits.state
        )
    produced.add(
        claude.parse(
            {"five_hour": {"utilization": 1.0}, "extra_usage": {"enabled": False}}, 1.0
        ).credits.state
    )
    assert produced == set(contract.CREDIT_STATES)


def test_exit_status_says_whether_anyone_answered(capsys):
    state = tempfile.mkdtemp()
    # Nothing stored at all.
    assert cli.main(["--state-dir", state, "snapshot"]) == cli.EXIT_NO_ANSWER
    assert cli.main(["--state-dir", state, "report"]) == cli.EXIT_NO_ANSWER
    capsys.readouterr()

    connection = store.connect(**{"environ": {config.STATE_ENV: state}})
    store.record(
        connection,
        contract.Observation("claude", 5.0, (contract.Window("5-hour", 30.0),)),
    )
    connection.close()
    assert cli.main(["--state-dir", state, "snapshot"]) == cli.EXIT_OK
    assert cli.main(["--state-dir", state, "report"]) == cli.EXIT_OK
    # One reading answers the question "how much is left" but
    # cannot answer "when do I run out".
    assert cli.main(["--state-dir", state, "forecast", "claude"]) == cli.EXIT_NO_ANSWER
    capsys.readouterr()


def test_the_same_gap_reports_one_code_everywhere(capsys):
    """A provider with no reading must not have two names."""
    state = tempfile.mkdtemp()
    cli.main(["--state-dir", state, "snapshot"])
    snapshot = json.loads(capsys.readouterr().out)
    assert {entry["error"] for entry in snapshot["providers"]} == {contract.ERROR_NO_READING}

    cli.main(["--state-dir", state, "report"])
    rendered = capsys.readouterr().out
    assert contract.ERROR_NO_READING in rendered
    assert "endpoint_unavailable" not in rendered


def test_the_storage_allowlist_membership_is_pinned():
    """A quiet addition to the boundary fails here."""
    assert redaction.OBSERVATION_FIELDS == frozenset(
        {
            "provider",
            "collected_at",
            "source",
            "freshness",
            "plan",
            "adapter_version",
            "windows",
            "credits",
            "answered",
            "error",
            "binding_window",
        }
    )
    assert redaction.WINDOW_FIELDS == frozenset(
        {"label", "used_percent", "resets_in_seconds", "remaining", "limit"}
    )
    assert redaction.CREDIT_FIELDS == frozenset({"state", "detail"})


def test_a_provider_with_no_window_declines_the_forecast():
    empty = contract.Observation("claude", 1.0)
    document = derive.forecast(empty, [(0.0, 10.0), (7200.0, 30.0)])
    assert document["burn_rate_per_hour"]["status"] == "no_binding_window"


def test_a_spent_window_is_not_called_exhausted():
    """That word is reserved for paid overage being consumed.

    Reusing it for a window with nothing left would tell an
    agent following the credit section that money is being
    spent when work has merely stopped.
    """
    rate = derive.burn_rate_per_hour([(0.0, 10.0), (7200.0, 30.0)])
    spent = derive.seconds_until_exhausted(100.0, rate)
    assert spent.status == "window_spent"
    assert spent.status not in contract.CREDIT_STATES


def test_a_forecast_on_a_failed_reading_says_what_failed():
    """Not "the provider reported no window"."""
    database = _db()
    connection = store.connect(database)
    store.record(connection, contract.failed("grok", contract.ERROR_NO_CREDENTIAL, now=5.0))
    document = api.forecast_document(connection, "grok")
    connection.close()
    assert document["status"] == contract.ERROR_NO_CREDENTIAL

    empty = store.connect(_db())
    assert api.forecast_document(empty, "grok")["status"] == contract.ERROR_NO_READING
    empty.close()


def test_a_window_that_reset_mid_span_does_not_average_across_it():
    """80, then 10, then 90 is net rising and must not be a rate.

    Comparing only the first and last reading reported a slope
    for a window that was never consumed that way. Only the
    readings after the last fall belong to the live window.
    """
    rate = derive.burn_rate_per_hour([(0.0, 80.0), (3600.0, 10.0), (7200.0, 90.0)])
    assert rate.known is True
    # 10 to 90 over one hour, not 80 to 90 over two.
    assert rate.value == 80.0

    # A reset with too little after it declines rather than
    # reporting the pre-reset window.
    assert derive.burn_rate_per_hour([(0.0, 80.0), (7200.0, 10.0)]).status == "not_rising"


def test_a_forecast_carries_one_status_at_the_top_level():
    """An agent must be able to read a single field."""
    observation = contract.Observation(
        "claude", 1.0, (contract.Window("5-hour", 30.0, resets_in_seconds=1800.0),)
    )
    declined = derive.forecast(observation, [(0.0, 10.0)])
    assert declined["status"] == "insufficient_samples"

    measured = derive.forecast(observation, [(0.0, 10.0), (7200.0, 30.0)])
    assert measured["status"] == "projected"

    no_window = derive.forecast(contract.Observation("claude", 1.0), [])
    assert no_window["status"] == "no_binding_window"


def test_every_forecast_shape_has_a_status(capsys):
    """Including the ones that come from a failed reading."""
    database = _db()
    connection = store.connect(database)
    store.record(connection, contract.failed("grok", contract.ERROR_NO_CREDENTIAL, now=5.0))
    store.record(
        connection,
        contract.Observation("claude", 5.0, (contract.Window("5-hour", 30.0),)),
    )
    try:
        for provider in ("grok", "claude", "kimi"):
            document = api.forecast_document(connection, provider)
            assert "status" in document, provider
    finally:
        connection.close()


def test_the_forecast_status_describes_the_forecast_not_the_rate():
    """A measured rate still only yields a projection.

    Reporting "measured" beside an extrapolated exhaustion
    time tells a reader an estimate was an observation.
    """
    observation = contract.Observation(
        "claude", 1.0, (contract.Window("5-hour", 30.0, resets_in_seconds=1800.0),)
    )
    document = derive.forecast(observation, [(0.0, 10.0), (7200.0, 30.0)])
    assert document["status"] == "projected"
    assert document["burn_rate_per_hour"]["status"] == "measured"
    assert document["seconds_until_exhausted"]["status"] == "projected"

    declined = derive.forecast(observation, [(0.0, 10.0)])
    assert declined["status"] == "insufficient_samples"
