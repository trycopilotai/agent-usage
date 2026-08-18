"""The browser tier, exercised without launching a browser."""

import json
import tempfile
from pathlib import Path

from agent_usage import contract
from agent_usage.browser import child, collector, extract

NOW = 1755000000.0


def _env():
    return {"AGENT_USAGE_STATE_DIR": tempfile.mkdtemp()}


def test_text_extraction_reads_only_what_the_page_states():
    text = "5 hour limit 42% used\nResets in 3 hours\n7 day limit 61.5% used"
    windows = extract.windows_from_text(text)
    assert [(w.label, w.used_percent) for w in windows] == [
        ("5-hour", 42.0),
        ("7-day", 61.5),
    ]
    assert windows[0].resets_in_seconds == 10800.0


def test_a_page_with_no_numbers_produces_no_windows():
    assert extract.windows_from_text("Loading your usage...") == ()
    observation = extract.observation_from_text("claude", "", NOW)
    assert observation.answered is False
    assert observation.error == contract.ERROR_BROWSER_SESSION_MISSING


def test_scraped_reads_are_labelled_as_scraped():
    observation = extract.observation_from_text("claude", "5 hour limit 10% used", NOW)
    assert observation.source == contract.SOURCE_BROWSER_TEXT


def test_percentages_outside_the_range_are_ignored():
    assert extract.windows_from_text("5 hour limit 900% used") == ()


def test_screenshot_flag_is_absent_unless_requested():
    argv = collector.child_argv(
        "claude", Path("/tmp/p"), headed=False, wait_for_login=False, screenshot=None
    )
    assert "--screenshot" not in argv
    argv = collector.child_argv(
        "claude", Path("/tmp/p"), headed=False, wait_for_login=False, screenshot=Path("/tmp/s.png")
    )
    assert "--screenshot" in argv


def test_login_asks_for_a_visible_window():
    argv = collector.child_argv(
        "claude", Path("/tmp/p"), headed=True, wait_for_login=True, screenshot=None
    )
    assert "--headed" in argv and "--wait-for-login" in argv


def test_a_dead_child_is_a_failed_read_not_a_partial_one():
    assert collector.interpret("claude", "", NOW).error == contract.ERROR_BROWSER_UNAVAILABLE
    assert collector.interpret("claude", "{oops", NOW).error == contract.ERROR_MALFORMED
    assert collector.interpret("claude", "[]", NOW).error == contract.ERROR_MALFORMED
    for raw in ("", "{oops", "[]"):
        assert collector.interpret("claude", raw, NOW).windows == ()


def test_child_errors_outside_the_vocabulary_become_malformed():
    raw = json.dumps({"error": "something new"})
    assert collector.interpret("claude", raw, NOW).error == contract.ERROR_MALFORMED


def test_cooldown_allows_one_read_then_declines():
    env = _env()
    line = json.dumps({"windows": [{"label": "5-hour", "used_percent": 40.0}]})

    def runner(argv, timeout):
        return line + "\n"

    first = collector.collect("claude", now=1.0, environ=env, runner=runner)
    assert first.answered is True
    second = collector.collect("claude", now=2.0, environ=env, runner=runner)
    assert second.error == contract.ERROR_COOLING_DOWN
    later = collector.collect(
        "claude", now=2.0 + collector.COOLDOWN_SECONDS, environ=env, runner=runner
    )
    assert later.answered is True


def test_unsupported_provider_is_refused_before_launching_anything():
    def explode(argv, timeout):  # pragma: no cover
        raise AssertionError("must not launch")

    result = collector.collect("nope", now=1.0, environ=_env(), runner=explode)
    assert result.error == contract.ERROR_UNSUPPORTED


def test_a_missing_browser_is_reported_as_a_missing_browser():
    """Not as an unreachable provider.

    Accepting either code let the wrong one ship: a reader
    told the endpoint was unreachable debugs their network,
    when the fix is to install the browser.
    """
    result = child.run("claude", Path(tempfile.mkdtemp()) / "profile")
    assert result["error"] == contract.ERROR_BROWSER_UNAVAILABLE


def test_child_emit_signals_unanswered_with_exit_one():
    assert child.emit({"error": contract.ERROR_BROWSER_UNAVAILABLE}) == 1
    assert child.emit({"windows": [{"label": "5-hour", "used_percent": 1.0}]}) == 0


def test_login_is_not_blocked_by_the_fallback_cooldown():
    """The documented fix has to be runnable when suggested.

    A failed browser read tells the reader to run `login`. If
    login shared the fallback's cap, that instruction would be
    refused for fifteen minutes.
    """
    env = _env()
    line = json.dumps({"windows": [{"label": "5-hour", "used_percent": 40.0}]})

    def runner(argv, timeout):
        return line + "\n"

    first = collector.collect("claude", now=1.0, environ=env, runner=runner)
    assert first.answered is True
    assert collector.collect("claude", now=2.0, environ=env, runner=runner).error == (
        contract.ERROR_COOLING_DOWN
    )
    assert collector.login("claude", now=2.0, environ=env, runner=runner).answered is True


def test_login_does_not_start_a_cooldown_of_its_own():
    env = _env()
    line = json.dumps({"windows": [{"label": "5-hour", "used_percent": 1.0}]})

    def runner(argv, timeout):
        return line + "\n"

    collector.login("claude", now=1.0, environ=env, runner=runner)
    assert collector.collect("claude", now=2.0, environ=env, runner=runner).answered is True


def test_a_scraped_first_party_reading_keeps_its_credit_state():
    """The child parses credits. The parent used to drop them.

    A page whose own JSON reported engaged credit came back
    saying the provider never mentioned credit at all.
    """
    raw = json.dumps(
        {
            "windows": [{"label": "5-hour", "used_percent": 10.0}],
            "credits": {"state": contract.CREDIT_ACTIVE, "detail": "extra usage engaged"},
            "source": contract.SOURCE_BROWSER_JSON,
        }
    )
    observation = collector.interpret("claude", raw, NOW)
    assert observation.credits.state == contract.CREDIT_ACTIVE
    assert observation.credits.engaged is True


def test_login_waits_for_usage_rather_than_for_any_cookie():
    """Navigating a signed out page sets cookies too.

    Returning on the first cookie closed the window before the
    operator could sign in, so the documented fix for
    browser_session_missing never populated the profile.
    """
    import inspect

    source = inspect.getsource(child._wait_for_login)
    assert "_signed_in" in source
    assert "cookies" not in source

    signal = inspect.getsource(child._signed_in)
    assert "_result" in signal and "windows" in signal


def test_a_headed_login_outlasts_the_child_it_waits_on():
    """The parent must not kill a window someone is using."""
    from agent_usage.browser import child as child_module

    assert collector.LOGIN_TIMEOUT_SECONDS > child_module.LOGIN_POLL_SECONDS

    seen = {}

    def runner(argv, timeout):
        seen["timeout"] = timeout
        return json.dumps({"windows": [{"label": "5-hour", "used_percent": 1.0}]}) + "\n"

    env = _env()
    collector.collect("claude", now=1.0, environ=env, runner=runner)
    assert seen["timeout"] == collector.CHILD_TIMEOUT_SECONDS

    collector.login("claude", now=2.0, environ=env, runner=runner)
    assert seen["timeout"] == collector.LOGIN_TIMEOUT_SECONDS
