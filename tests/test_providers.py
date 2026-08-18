"""Each adapter quirk, pinned so a rewrite cannot lose it."""

from agent_usage import contract
from agent_usage.providers import base, claude, codex, grok, kimi, registry, zai

NOW = 1755000000.0


def test_claude_hides_untouched_per_model_windows_but_keeps_overall_zero():
    body = {
        "five_hour": {"utilization": 0.0},
        "seven_day": {"utilization": 12.0},
        "seven_day_opus": {"utilization": 0.0},
        "seven_day_sonnet": {"utilization": 3.0},
    }
    labels = [window.label for window in claude.parse(body, NOW).windows]
    # Zero on a per model pool means untouched, not measured.
    assert "7-day opus" not in labels
    # Zero on an overall pool is a measurement and stays.
    assert "5-hour" in labels
    assert "7-day sonnet" in labels


def test_codex_reset_is_a_duration_not_an_instant():
    body = {"rate_limit": {"primary_window": {"used_percent": 10, "reset_after_seconds": 900}}}
    window = codex.parse(body, NOW).windows[0]
    # Treating this as a timestamp would put the reset in 1970.
    assert window.resets_in_seconds == 900.0


def test_kimi_derives_percent_from_strings_and_names_by_duration():
    body = {
        "limits": [
            {
                "window": {"timeUnit": "TIME_UNIT_MINUTE", "duration": 300},
                "detail": {"limit": "100", "remaining": "40"},
            }
        ]
    }
    window = kimi.parse(body, NOW).windows[0]
    assert window.used_percent == 60.0
    assert window.label == "5-hour"


def test_kimi_ignores_windows_in_other_units():
    body = {"limits": [{"window": {"timeUnit": "TIME_UNIT_DAY", "duration": 1}, "detail": {}}]}
    assert kimi.parse(body, NOW).answered is False


def test_zai_usage_field_is_the_limit_not_the_usage():
    body = {
        "success": True,
        "data": {"limits": [{"unit": 3, "number": 5, "usage": 1000, "currentValue": 250}]},
    }
    window = zai.parse(body, NOW).windows[0]
    # Reading the names at face value would report 75 percent
    # remaining as 75 percent used, inverting the answer.
    assert window.used_percent == 25.0
    assert window.limit == 1000.0


def test_zai_reset_is_epoch_milliseconds():
    body = {
        "success": True,
        "data": {
            "limits": [
                {
                    "unit": 3,
                    "number": 1,
                    "usage": 10,
                    "currentValue": 1,
                    "nextResetTime": (NOW + 3600) * 1000,
                }
            ]
        },
    }
    assert round(zai.parse(body, NOW).windows[0].resets_in_seconds) == 3600


def test_zai_skips_unknown_unit_codes_rather_than_guessing():
    assert zai.window_label(99, 1) is None
    assert zai.window_label(6, 1) == "weekly"
    assert zai.window_label(3, 5) == "5-hour"


def test_zai_reports_failure_carried_in_a_success_body():
    assert zai.parse({"success": False, "msg": "nope"}, NOW).error == contract.ERROR_UNAVAILABLE


def test_grok_accepts_numbers_strings_and_wrapped_values():
    body = {"config": {"monthlyLimit": {"val": "100"}, "used": "25"}}
    assert grok.parse(body, NOW).windows[0].used_percent == 25.0


def test_grok_reports_one_window_and_invents_no_others():
    body = {"config": {"monthlyLimit": 100, "used": 10}}
    windows = grok.parse(body, NOW).windows
    assert len(windows) == 1
    assert windows[0].label == "monthly"


def test_number_coercion_rejects_bool():
    assert base.number(True) is None
    assert base.number("12.5") == 12.5
    assert base.number({"val": 3}) == 3.0


def test_percent_from_used_and_limit_refuses_zero_limit():
    assert base.percent_from_used_and_limit(1, 0) is None


def test_registry_fails_closed_on_an_unknown_provider():
    import pytest

    with pytest.raises(registry.UnknownProvider):
        registry.adapter("nope")
    with pytest.raises(registry.UnknownProvider):
        registry.collect_all(("claude", "nope"))


def test_malformed_bodies_never_produce_windows():
    for parse in (claude.parse, codex.parse, kimi.parse, zai.parse, grok.parse):
        observation = parse({"unexpected": True}, NOW)
        assert observation.answered is False
        assert observation.windows == ()


def test_zai_retries_once_with_the_raw_key_after_a_rejection(monkeypatch):
    """The one retry in the package, and the reason for it."""
    seen = []

    def fake_get_json(url, headers):
        seen.append(headers["Authorization"])
        if len(seen) == 1:
            raise base.HttpFailure(contract.ERROR_UNAUTHORIZED)
        return {
            "success": True,
            "data": {"limits": [{"unit": 3, "number": 5, "usage": 100, "currentValue": 10}]},
        }

    monkeypatch.setattr(base, "get_json", fake_get_json)
    monkeypatch.setattr(
        zai.credentials,
        "zai",
        lambda **kwargs: zai.credentials.Credential("zai", present=True, token="KEY"),
    )
    observation = zai.collect(now=NOW)
    assert observation.answered is True
    # First as a bearer, then the raw key. Community tools
    # disagree about which the endpoint accepts.
    assert seen == ["Bearer KEY", "KEY"]


def test_zai_does_not_retry_other_failures(monkeypatch):
    seen = []

    def fake_get_json(url, headers):
        seen.append(headers["Authorization"])
        raise base.HttpFailure(contract.ERROR_RATE_LIMITED)

    monkeypatch.setattr(base, "get_json", fake_get_json)
    monkeypatch.setattr(
        zai.credentials,
        "zai",
        lambda **kwargs: zai.credentials.Credential("zai", present=True, token="KEY"),
    )
    assert zai.collect(now=NOW).error == contract.ERROR_RATE_LIMITED
    assert len(seen) == 1


def test_credit_states_the_adapters_actually_emit():
    """Every state the skill documents has a producer."""
    enabled_unused = claude.parse(
        {"five_hour": {"utilization": 1.0}, "extra_usage": {"enabled": True, "used": 0, "cap": 10}},
        NOW,
    )
    assert enabled_unused.credits.state == contract.CREDIT_AVAILABLE

    engaged = claude.parse(
        {"five_hour": {"utilization": 1.0}, "extra_usage": {"enabled": True, "used": 5, "cap": 10}},
        NOW,
    )
    assert engaged.credits.state == contract.CREDIT_ACTIVE
    assert engaged.credits.engaged is True

    spent = claude.parse(
        {
            "five_hour": {"utilization": 1.0},
            "extra_usage": {"enabled": True, "used": 10, "cap": 10},
        },
        NOW,
    )
    assert spent.credits.state == contract.CREDIT_EXHAUSTED

    off = claude.parse({"five_hour": {"utilization": 1.0}, "extra_usage": {"enabled": False}}, NOW)
    assert off.credits.state == contract.CREDIT_OFF
    assert off.credits.engaged is False

    grok_off = grok.parse({"config": {"monthlyLimit": 10, "used": 1, "onDemandCap": 0}}, NOW)
    assert grok_off.credits.state == contract.CREDIT_OFF
    grok_active = grok.parse(
        {"config": {"monthlyLimit": 10, "used": 1, "onDemandCap": 5, "onDemandUsed": 2}}, NOW
    )
    assert grok_active.credits.state == contract.CREDIT_ACTIVE


def test_providers_without_a_credit_field_say_unavailable():
    """Silence is not an assertion either way.

    Reusing "exhausted" for an empty quota would borrow a word
    that belongs to the paid overage allowance for a fact
    about a usage limit, and "off" would be an answer the
    provider never gave.
    """
    empty_pool = kimi.parse(
        {
            "limits": [
                {
                    "window": {"timeUnit": "TIME_UNIT_MINUTE", "duration": 300},
                    "detail": {"limit": "100", "remaining": "0"},
                }
            ],
            "usage": {"limit": "100", "remaining": "0"},
        },
        NOW,
    )
    assert empty_pool.answered is True
    assert empty_pool.credits.state == contract.CREDIT_UNAVAILABLE
    assert empty_pool.credits.engaged is False

    quota = zai.parse(
        {
            "success": True,
            "data": {"limits": [{"unit": 3, "number": 5, "usage": 100, "currentValue": 10}]},
        },
        NOW,
    )
    assert quota.credits.state == contract.CREDIT_UNAVAILABLE


def test_credential_discovery_finds_each_client_where_it_writes(tmp_path):
    import json as _json

    from agent_usage.providers import credentials

    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text(
        _json.dumps({"tokens": {"access_token": "t", "account_id": "acct"}})
    )
    codex_credential = credentials.codex(home=tmp_path)
    assert codex_credential.present and codex_credential.account == "acct"

    (tmp_path / ".grok").mkdir()
    (tmp_path / ".grok" / "auth.json").write_text(_json.dumps({"whoever": {"key": "k"}}))
    assert credentials.grok(home=tmp_path).present is True

    # The documented environment fallback, which belongs to
    # that client's own convention rather than to this tool.
    assert credentials.zai(home=tmp_path, environ={}).present is False
    assert credentials.zai(home=tmp_path, environ={"ZAI_API_KEY": "k"}).origin == "environment"

    assert credentials.claude(home=tmp_path, runner=lambda *a, **k: None).present is False
    for described in credentials.describe_all(home=tmp_path, environ={}):
        assert set(described) == {"provider", "present", "expired", "origin"}
