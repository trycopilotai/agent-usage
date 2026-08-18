# Contributing

Changes should preserve three behaviours, each of which has
a test:

Missing is never zero. A provider that did not answer must
produce no window rather than a window at zero percent.

Stale never appears live. Every reading carries when it was
collected and what produced it.

A declined answer stays declined. Derivations return a
status rather than inventing a number from too little
evidence.

Before opening a pull request:

```sh
make test
make check
```

Add a focused regression test for every behaviour change. A
provider quirk without a test will be lost in the next
rewrite, and the quirks are the reason this package exists.

Provider adapters return closed error codes, never free
text. The string form of an HTTP error routinely carries the
URL it came from, and these URLs routinely carry an account
identifier.

Widening what may be stored means editing the allowlist in
`agent_usage/redaction.py` on purpose, and adding a test.
