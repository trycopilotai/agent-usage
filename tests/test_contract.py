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


def test_an_account_pool_binds_even_when_a_feature_pool_is_fuller():
    """The whole point of the scope field."""
    observation = contract.Observation(
        provider="codex",
        collected_at=1.0,
        windows=(
            contract.Window("overall 1-week", 0.0),
            contract.Window("Spark 1-week", 100.0, scope=contract.SCOPE_FEATURE),
        ),
    )
    assert observation.binding_window().label == "overall 1-week"
    assert [w.label for w in observation.spent_features()] == ["Spark 1-week"]


def test_a_provider_with_only_feature_pools_still_binds_one():
    """Some answer beats none.

    A provider that reports nothing but feature pools has told
    us what limits it has. Returning None there would read as
    "no windows", which is how an unanswered provider reads.
    """
    observation = contract.Observation(
        provider="codex",
        collected_at=1.0,
        windows=(
            contract.Window("a", 10.0, scope=contract.SCOPE_FEATURE),
            contract.Window("b", 80.0, scope=contract.SCOPE_FEATURE),
        ),
    )
    assert observation.binding_window().label == "b"


def test_a_feature_pool_short_of_full_is_not_reported_as_spent():
    observation = contract.Observation(
        provider="codex",
        collected_at=1.0,
        windows=(contract.Window("nearly", 99.9, scope=contract.SCOPE_FEATURE),),
    )
    assert observation.spent_features() == ()


def test_a_window_scope_outside_the_closed_set_is_refused():
    import pytest

    with pytest.raises(contract.ContractError):
        contract.Window("x", 1.0, scope="invented").validate()


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
