# agent-usage

Read how much of each AI provider's usage limit is left,
when it resets, and which provider still has headroom.
Supports Claude, Codex, Kimi, and Grok from one
command, one HTTP surface, and one agent skill.

It answers from measured readings and declines when it
cannot. A provider that did not respond is reported as not
responding, never as zero usage, and a forecast with too
little history returns a reason instead of a number.

## Quick start

Requires Python 3.11 or newer and no third party packages.

```sh
python3 -m agent_usage.cli collect
python3 -m agent_usage.cli report
python3 -m agent_usage.cli forecast claude
python3 -m agent_usage.cli doctor
```

`collect` reads the providers and records what they said.
`report` prints a Markdown block. `forecast` says when a
limit runs out, or why that is unknown. `doctor` shows which
credentials are present without printing any of them.

Serve the same answers over HTTP on loopback:

```sh
python3 -m agent_usage.cli serve
curl -s http://127.0.0.1:8787/api/v1/snapshot
curl -s http://127.0.0.1:8787/api/v1/report.md
```

## Demo

```text
$ agent-usage report
## Provider usage

| Provider | Window | Used | Resets in | Credits |
| --- | --- | --- | --- | --- |
| claude | 5-hour | 40.0% | 30m | unavailable |
| codex | 5-hour | 12.5% | 1h 0m | unavailable |

- grok: no answer (no_credential)
- kimi: no answer (no_credential)

Read by agent-usage. 2 of 4 providers answered.
```

Both providers are named as not answering rather than shown
at zero, and the code says why. Asking for a forecast on the
same data reports a measured burn rate, a projected
exhaustion, and `resets_before_exhausted`, meaning the
window resets before that pace would spend it.

That session is `evidence/transcripts/demo-session.txt`,
produced by `scripts/demo.sh`. **Every number in it is
synthetic.** No provider account was contacted and no real
quota appears, because publishing a real transcript would
publish the operator's account usage.
`evidence/demo-manifest.json` records the commit, the source
digests, and that the transcript was not edited,
`scripts/verify_demo.py` re-checks all of it, and
`tests/test_evidence.py` tampers with a copy seven ways to
prove the verifier fails when it should.

## What it reads

Credentials are found where the client you already use
stores them on this machine. That is usually the provider's
own tool. They are sent nowhere except to the provider they
belong to, and no command prints one. Run `doctor` to see
which were found.

One credential is written. Claude's access token lasts eight
hours, and on a machine where no Claude client runs there is
nothing else to renew it, so this tool renews it and stores
the result in the same file the client uses. That provider
rotates the refresh token on every use, which means a renewal
that is not stored locks the account out, so storing it is
part of doing it at all. Nothing else is ever written.

Three collectors. The first party HTTP API is what `collect`
uses. `collect --browser` adds a headless browser fallback
for providers that publish usage on a page. The headful
browser runs only under `login`, because OAuth needs a
visible window.

State lives in one configurable directory, resolved from
`AGENT_USAGE_STATE_DIR`, then `XDG_STATE_HOME`, then
`~/.local/state/agent-usage`.

## Screenshots are off by default

`collect --browser --screenshots` saves the latest portal
image, one file per provider, overwritten each run, under
the state directory. Nothing older is kept.

A screenshot of a signed in usage page shows the account
email, the plan, and any organisation name the page renders.
It is written outside this repository and is served only on
loopback. Turn it on when you are debugging a page that
changed shape, not as a matter of course.

## What it does not do

It does not send prompts, proxy a provider, buy credits, or
change anything on your account. Every route that touches a
provider is a read.

One route writes, and only to this tool's own store: `POST
/api/v1/ingest` accepts a reading a browser took. It is closed
until you mint a token, and it is described under "Handing in a
reading from your own browser".

It never stores or serves page HTML, cookies, headers, DOM
snapshots, prompt text, or transcripts. An allowlist decides
what may be stored, so a provider that starts returning a
new field cannot leak it by default.

The browser tier uses its own profile directory and an
explicit `login` step. It never opens or copies the browser
profile you use, because a usage reader that copies a live
profile is holding every cookie you own.

The read routes have no authentication and the server refuses
to bind anything but loopback. The one write route requires a
bearer token and answers a browser only from an origin you
named.

## Handing in a reading from your own browser

Some providers keep subscription usage behind a session an API
token cannot hold. Grok is the example: its rate-limit endpoint
answers an API token with "Action cannot be performed by OAuth2
token users", and the automated browser this tool would
otherwise drive is refused by bot protection at the sign in
domain. The measurement is real and reachable, but only from a
browser you are already signed in to.

So you can hand it in, with a bookmarklet — a bookmark whose
URL is JavaScript, so clicking it runs that code on the page
you are looking at.

```sh
python3 scripts/make_bookmarklet.py --dashboard https://your-dashboard
```

Save the printed line as a bookmark. Both Safari and Chrome
strip a `javascript:` URL typed into the address bar, so it has
to be saved rather than pasted.

On grok.com, signed in, click it. The script reads
`/rest/rate-limits` — same origin, so your session cookie
applies and CORS never enters into it — and sends you to the
dashboard with the reading in the **URL fragment**. A fragment
is never transmitted to a server, so nothing crosses an origin
and the bookmarklet holds no secret. The dashboard, behind
whatever sign in it already has, posts the reading onward with
your session and clears the fragment.

The reading is only as fresh as your last click. There is no
polling: a provider that hides usage behind an interactive
session cannot be read on a timer.

### Serving the route directly

A deployment that exposes `/api/v1/ingest` without a sign in
front of it needs its own authentication, so the route stays
closed until you mint a token:

```sh
python3 -m agent_usage.cli ingest-token
export AGENT_USAGE_INGEST_ORIGINS=https://grok.com
```

What arrives is not trusted the way a fetch is:

- the reading is stored as `browser_ingest`, never `api`, so a
  reader can see it arrived rather than being collected
- the time is this machine's clock, so a caller cannot backdate
  a reading into a gap or postdate one to outrank a real fetch
- windows must satisfy the same contract every adapter
  satisfies, and an unanswered reading must carry a code from
  the closed set rather than a sentence
- signed out, the bookmarklet reports
  `browser_session_missing` rather than handing in the
  anonymous allowance as though it were the account's

The route stays closed until the token file exists, so a
deployment that never wanted it does not have to turn it off.
Rotate with `ingest-token --rotate`, which revokes the old
secret.

## The interface

```sh
python3 -m agent_usage.cli serve
```

Then open <http://127.0.0.1:8787/ui/>. It shows the governing
limit for every provider, all windows, when each resets,
credit state, a history line per provider, a forecast or the
reason there is not one, and a collection health table.

It carries the same rules the library does. A provider that
did not answer is drawn as not answering with its error
code, never as a bar at zero. A reading that has aged out of
the live window is labelled rather than redrawn. Headroom
ranking excludes providers that did not answer and says so,
because that is unknown headroom rather than full headroom.

The built interface is committed under `web/dist`, so the
service serves it with no Node toolchain present. Rebuild it
with `npm --prefix web ci && npm --prefix web run build`.

## Docker

Published images are at `ghcr.io/trycopilotai/agent-usage`,
tagged by release and `latest`.

```sh
docker run --rm -p 8787:8787 \
  -v agent-usage-state:/data/state \
  -v "$HOME/.claude:/data/.claude:ro" \
  ghcr.io/trycopilotai/agent-usage:v0.2.1
```

To build it yourself instead:

```sh
docker build -t agent-usage .
docker run --rm -p 8787:8787 \
  -v agent-usage-state:/data/state \
  -v "$HOME/.claude:/data/.claude:ro" \
  agent-usage
```

An image is pushed only after a container built from it has
answered for both halves: the API under its own schema, and
the interface document with both of its assets.

The image runs unprivileged and carries no build toolchain.
Mount whichever provider credential directories you want it
to read, read only; it needs none of them to start.

Inside the container the service binds a routable address,
which it refuses to do anywhere else. That needs
`--allow-any-host`, which the image passes explicitly. It
adds no authentication: publishing the port is what exposes
this account's usage, so publish it deliberately.

## Install

Both product installs pin `v0.2.1`. Each block can be run
twice with the same result.

### Claude Code

```sh
release=v0.2.1
checkout="$HOME/.claude/plugins/agent-usage-$release"
discovery="$HOME/.claude/skills/agent-usage"
mkdir -p "$(dirname "$checkout")" "$(dirname "$discovery")"
if [ -d "$checkout/.git" ]; then
  git -C "$checkout" fetch --quiet --depth 1 origin tag \
    "$release"
else
  git clone --quiet --depth 1 --branch "$release" \
    https://github.com/trycopilotai/agent-usage \
    "$checkout"
fi
git -C "$checkout" checkout --quiet --detach "$release"
if [ -e "$discovery" ] && [ ! -L "$discovery" ]; then
  echo "Refusing to replace non-symlink: $discovery" >&2
  exit 1
fi
ln -sfn "$checkout/skill" "$discovery"
```

Then invoke the standalone skill:

```text
/agent-usage how much Claude quota is left?
```

Installed through a marketplace, plugin skills are
namespaced:

```text
/agent-usage:agent-usage how much quota is left?
```

### Codex

```sh
release=v0.2.1
checkout="$HOME/.codex/plugins/agent-usage-$release"
discovery="$HOME/.agents/skills/agent-usage"
mkdir -p "$(dirname "$checkout")" "$(dirname "$discovery")"
if [ -d "$checkout/.git" ]; then
  git -C "$checkout" fetch --quiet --depth 1 origin tag \
    "$release"
else
  git clone --quiet --depth 1 --branch "$release" \
    https://github.com/trycopilotai/agent-usage \
    "$checkout"
fi
git -C "$checkout" checkout --quiet --detach "$release"
if [ -e "$discovery" ] && [ ! -L "$discovery" ]; then
  echo "Refusing to replace non-symlink: $discovery" >&2
  exit 1
fi
ln -sfn "$checkout/skill" "$discovery"
```

Then invoke it:

```text
$agent-usage how much quota is left?
```

Installed through a Codex marketplace, use `@agent-usage`.

## Development

```sh
make test
make check
```

The suite runs without a browser installed and without any
provider credential. The browser tier is covered by parsing
and process level tests rather than by launching Chromium,
so a contributor with no provider account can still change
it safely.

## Limitations

The browser tier needs Playwright and a Chromium download,
neither of which this package installs. Without them the
browser collectors decline, and the rest of the tool carries
on.

No live browser capture is recorded in this repository's
evidence. The parsing and process behaviour is tested, the
end to end scrape against a signed in account is not.

Rate and cost figures are not provided. This reports the
limits providers publish about themselves, and a price table
would go stale silently.
