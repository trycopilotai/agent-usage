# Security

## Reporting

Report a vulnerability privately through the repository's
Security tab. Please do not open a public issue containing a
credential, a token, or an account identifier.

## What this tool touches

It reads credentials that other clients already stored on
this machine, and it sends each one only to the provider it
belongs to. It never writes, refreshes, or relays a
credential, and no command prints one. `doctor` reports
presence, expiry, and which location a credential came from.

A storage allowlist decides what may be persisted. Page
HTML, cookies, headers, DOM snapshots, prompt text, and
transcripts are outside it, so a provider that begins
returning a new field cannot leak it by default.

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
