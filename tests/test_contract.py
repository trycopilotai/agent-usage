"""The three rules the whole package depends on."""

import pytest

from agent_usage import contract


def test_missing_is_never_zero():
    """A provider that did not answer has no window at all."""
    failed = contract.failed("claude", contract.ERROR_NO_CREDENTIAL, now=1.0)
    assert failed.windows == ()
    assert failed.answered is False
    # An observation with no windows is unanswered even with
    # no error, which is what stops a silent gap reading as 0.
    empty = contract.Observation(provider="claude", collected_at=1.0)
    assert empty.answered is False


def test_a_failed_observation_may_not_carry_windows():
    bad = contract.Observation(
        provider="claude",
        collected_at=1.0,
        windows=(contract.Window("5-hour", 10.0),),
        error=contract.ERROR_RATE_LIMITED,
    )
    with pytest.raises(contract.ContractError):
        bad.validate()


def test_binding_window_is_the_highest_and_breaks_ties_by_label():
    observation = contract.Observation(
        provider="claude",
        collected_at=1.0,
        windows=(
            contract.Window("7-day", 61.0),
            contract.Window("5-hour", 42.0),
        ),
    )
    assert observation.binding_window().label == "7-day"
    tied = contract.Observation(
        provider="claude",
        collected_at=1.0,
        windows=(contract.Window("weekly", 50.0), contract.Window("5-hour", 50.0)),
    )
    assert tied.binding_window().label == "5-hour"
    assert tied.binding_window().label == "5-hour"


def test_percent_bounds_and_bool_rejection():
    with pytest.raises(contract.ContractError):
        contract.Window("5-hour", 101.0).validate()
    with pytest.raises(contract.ContractError):
        contract.Window("5-hour", -1.0).validate()
    with pytest.raises(contract.ContractError):
        # bool is an int subclass and must not pass as a number.
        contract.Window("5-hour", True).validate()


def test_closed_sets_are_enforced():
    with pytest.raises(contract.ContractError):
        contract.Credits("engaged-ish").validate()
    with pytest.raises(contract.ContractError):
        contract.Observation("claude", 1.0, source="telepathy").validate()
    with pytest.raises(contract.ContractError):
        contract.failed("claude", "made_up_code")


def test_snapshot_counts_answers_not_providers():
    document = contract.snapshot(
        [
            contract.Observation("claude", 1.0, (contract.Window("5-hour", 5.0),)),
            contract.failed("grok", contract.ERROR_NO_CREDENTIAL, now=1.0),
        ]
    )
    assert document["requested"] == 2
    assert document["answered"] == 1
    assert document["schema"] == contract.SCHEMA
