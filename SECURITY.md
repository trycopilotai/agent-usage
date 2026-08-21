# Security

## Reporting

Report a vulnerability privately through the repository's
Security tab. Please do not open a public issue containing a
credential, a token, or an account identifier.

## What this tool touches

It reads credentials that other clients already stored on
this machine, and it sends each one only to the provider it
belongs to. It never relays a credential, and no command
prints one. `doctor` reports presence, expiry, and which
location a credential came from.

It writes exactly one credential. An expired Claude access
token is renewed against the provider's own token endpoint
and the result replaces the file the Claude client already
uses, atomically and at mode 600. The provider rotates the
refresh token on every use, so a renewal that is not stored
would leave the account holding a spent token; every failure
path leaves the file untouched. A credential held in the
macOS keychain is never renewed this way, because the file
this tool could write is not the store the client reads.

A storage allowlist decides what may be persisted. Page
HTML, cookies, headers, DOM snapshots, prompt text, and
transcripts are outside it, so a provider that begins
returning a new field cannot leak it by default.

## The one route that writes

`POST /api/v1/ingest` accepts a usage reading taken by a
browser you are signed in to, for a provider whose allowance an
API token cannot reach. It is the only route that writes, and
the only one with authentication.

It is closed until `ingest-token` creates the secret, which is
written at mode 600 the way every other file here is. The
secret is compared in constant time. Rotating it revokes the
previous one.

A reading that arrives is not a reading that was fetched, and
it is not stored as though it were. Its source is forced to
`browser_ingest`, its timestamp comes from this machine's
clock rather than the caller's, and its windows must satisfy
the same contract every adapter satisfies. An unanswered
reading must carry a code from the closed set. The body is
capped before it is parsed.

Cross origin requests are answered only for an origin named in
`AGENT_USAGE_INGEST_ORIGINS`, which is empty by default. There
is no wildcard: a wildcard would let any page you visit post a
reading, which is what the token exists to prevent.

The secret is a capability to write usage numbers into your own
store, and nothing else. It reaches no provider and carries no
account identifier. It does end up inside a bookmarklet, which
is a URL in your bookmarks, so treat it as you would any local
secret and rotate it if you share the bookmark.

## The browser tier

The browser collectors run as a separate short lived process
under a deadline, and the parent kills the whole process
group if that deadline passes. The child prints exactly one
JSON object and nothing else.

It uses a profile directory belonging to this tool. It does
not read, copy, or open the browser profile you use.

## Screenshots

Screenshot capture is off by default. When enabled it writes
one image per provider, overwritten each run, into the
configurable state directory and never into this repository.
An image of a signed in usage page can show the account
email, the plan, and an organisation name. The endpoint that
serves it is loopback only.

## The HTTP surface

There is no authentication. Startup refuses any address that
is not loopback, and every route is a read.
