---
name: agent-usage
description: >-
  Read how much of each AI provider's usage limit is left,
  when it resets, and which provider to route work to. Use
  when the user asks how much Claude, Codex, Grok, Kimi, or
  z.ai quota remains, when a limit resets, how fast they are
  burning through one, whether they will run out before a
  reset, or which provider has headroom right now. Also use
  before starting long or expensive work that could hit a
  limit part way through.
---

# agent-usage

Answer usage questions from measured readings, never from a
guess. If the data does not support an answer, say which
reading is missing instead of estimating one.

## Decide what is being asked

Four questions, four commands. Read the state before
collecting: a reading from a minute ago answers most
questions and costs nothing.

| The user asks                            | Run                   |
| ---------------------------------------- | --------------------- |
| How much is left right now               | `snapshot`            |
| Get a fresh reading                      | `collect`             |
| When will I run out                      | `forecast <provider>` |
| Something to paste into a PR or an issue | `report`              |

## Run it

From the repository root:

```sh
python3 -m agent_usage.cli snapshot
python3 -m agent_usage.cli collect
python3 -m agent_usage.cli forecast claude
python3 -m agent_usage.cli report
```

`snapshot` reads what is already stored. `collect` goes to
the providers, which takes a few seconds. `collect` and
`login` are the commands that reach the network, and `login`
opens a provider page in a visible browser.

For `collect`, `snapshot`, and `report`, exit status 0 means
at least one provider answered and 1 means none did, which
is a real answer and not an error to retry blindly.
`forecast` exits 1 when it cannot produce a rate, even
though a provider answered, because the forecast was the
question asked.

## Read the output honestly

Every provider entry carries `answered`. When it is false,
the provider did not report, and that is not the same as
zero usage. Say "claude did not report" rather than "claude
is at 0%".

`freshness` is `live`, `cached`, or `stale`. Never describe
a stale reading as current. If the user needs current data
and the reading is stale, run `collect` first.

`source` is `api`, `browser_json`, or `browser_text`. A
`browser_text` reading was scraped from rendered page text
and is the least precise. Mention that when it is what you
are quoting.

`binding_window` is the window closest to running out. It is
the one to quote when the user asks a single question like
"how much is left". Do not average windows of different
durations together.

## Forecasts decline on purpose

Read the top level `status`. `projected` means a forecast
exists: a rate was measured from the stored readings and the
time to exhaustion was extrapolated from it. Say so in those
terms. It is an extrapolation, not an observation, and it
assumes the current pace continues.

Any other value names why there is no forecast, and there is
then nothing to report but that reason. Never convert a
declined forecast into an estimate, and never present one as
a number with a caveat. A `used_percent` may still appear
next to a declined status; that is the current reading, not
a forecast.

To get a forecast, run `collect`, wait, and run it again.
Two readings at least a minute apart are the minimum, and
they must be from the same window: if the limit reset in
between, the clock starts over.

When `resets_before_exhausted` is true, the window resets
before the current pace would spend it, so the honest answer
is that they will not run out on this pace.

## Credit state is a closed set

`unavailable` means the provider was not asked or did not
say. `off` means it said there is none engaged. Those are
different, and `unavailable` must never be reported as
`off`.

`available` means credit exists but is not being consumed.

`active` means paid overage is being consumed right now.
Flag it, because it means money is going out.

`exhausted` means the overage allowance is used up. Money
was spent, but spending has stopped, and the useful warning
is the opposite one: there is nothing left to fall back on,
so work may stop when the limit is reached.

Only Claude and Grok report credit at all. The other three
always read `unavailable`, which means they were not asked
and did not say. Do not present that as "no credit engaged".

## When a provider does not answer

The `error` field carries a short code. Report it verbatim
rather than paraphrasing it, and do not treat an unfamiliar
one as a provider outage.

Three have an action worth suggesting:

- `no_credential`: that client is not signed in on this
  machine.
- `credential_expired`: signed in once, needs refreshing.
- `browser_session_missing`: the browser reached the page
  and found no usage on it. Usually the profile is not
  signed in, so suggest `login <provider>`, but a page that
  changed shape looks the same from here.

Run `doctor` to see which credentials are present. It
reports presence, expiry, and which location the credential
came from, never a token.

## The browser fallback is opt in

`collect --browser` falls back to a browser when a
provider's API declines. It is slower, visible to the
provider, and limited to one attempt per provider per
fifteen minutes. Do not add it to routine reads.

`--screenshots` additionally saves the latest portal image.
A screenshot of a signed in account page shows the account
email and plan. Do not turn it on for someone without
telling them what it captures.

## Choosing a provider

When asked where to route work, compare
`binding_window.used_percent` across providers that
answered. Prefer the lowest. Exclude any provider whose
credits are `exhausted`, and mention when a provider was
excluded because it did not answer rather than because it
was busy.

## Never do these

Do not report a missing reading as zero usage. Do not
present a stale reading as live. Do not turn a declined
forecast into an estimate. Do not read or echo a credential;
`doctor` reports shape. Do not bind the server to anything
but loopback; it has no authentication and it will refuse
anyway.
