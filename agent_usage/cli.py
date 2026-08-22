"""The command surface, over the same library the API uses.

`snapshot`, `report`, and `forecast` call the same functions
the HTTP surface calls, so those two views cannot drift. A
test fetches the report route over HTTP and asserts it is
byte identical to what this command prints. `collect`,
`login`, `doctor`, and `serve` have no HTTP equivalent.

Options are few and named. The state directory is the only
setting this package reads from the environment; a provider
credential may also come from the environment, but that is
the provider client's own convention rather than this
tool's.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from . import api, config, contract, derive, ingest, report, store
from .browser import collector as browser_collector
from .browser import extract as browser_extract
from .providers import credentials, registry

EXIT_OK = 0
EXIT_NO_ANSWER = 1
EXIT_USAGE = 2


def _state_kwargs(arguments: argparse.Namespace) -> dict[str, Any]:
    if getattr(arguments, "state_dir", None):
        return {"environ": {config.STATE_ENV: str(arguments.state_dir)}}
    return {}


def _providers(arguments: argparse.Namespace) -> tuple[str, ...]:
    chosen = getattr(arguments, "provider", None)
    if not chosen:
        return registry.PROVIDERS
    return (chosen,)


def command_collect(arguments: argparse.Namespace) -> int:
    """Read providers now and record what they said."""
    kwargs = _state_kwargs(arguments)
    connection = store.connect(**kwargs)
    observations: list[contract.Observation] = []
    try:
        for name in _providers(arguments):
            observation = registry.collect(name)
            if not observation.answered and arguments.browser:
                if name in browser_extract.BROWSER_PROVIDERS:
                    observation = browser_collector.collect(
                        name,
                        capture_screenshot=arguments.screenshots,
                        **kwargs,
                    )
            store.record(connection, observation)
            observations.append(observation)
    finally:
        connection.close()
    _emit(arguments, contract.snapshot(observations))
    return EXIT_OK if any(item.answered for item in observations) else EXIT_NO_ANSWER


def command_snapshot(arguments: argparse.Namespace) -> int:
    """Show the latest stored reading for every provider."""
    kwargs = _state_kwargs(arguments)
    connection = store.connect(**kwargs)
    try:
        document = api.snapshot_document(connection)
    finally:
        connection.close()
    _emit(arguments, document)
    return EXIT_OK if document["answered"] else EXIT_NO_ANSWER


def command_report(arguments: argparse.Namespace) -> int:
    """Print the Markdown block, identical to the API route."""
    kwargs = _state_kwargs(arguments)
    connection = store.connect(**kwargs)
    observations: list[contract.Observation] = []
    try:
        for name in registry.PROVIDERS:
            document = store.latest(connection, name)
            if document is None or not document.get("answered"):
                observations.append(_stored_failure(name, document))
                continue
            observations.append(_rehydrate(name, document))
    finally:
        connection.close()
    sys.stdout.write(report.render(observations))
    return EXIT_OK if any(item.answered for item in observations) else EXIT_NO_ANSWER


def _stored_failure(name: str, document: dict[str, Any] | None) -> contract.Observation:
    """Rebuild an unanswered reading, keeping its own code.

    Substituting a generic code here would tell a reader the
    endpoint was unreachable when the truth may be that no
    credential was ever present, which is a different fix.
    """
    code = None
    if isinstance(document, dict):
        candidate = document.get("error")
        if candidate in contract.ERROR_CODES:
            code = candidate
    collected = float(document.get("collected_at", 0.0)) if isinstance(document, dict) else 0.0
    return contract.failed(
        name,
        code or contract.ERROR_NO_READING,
        now=collected or time.time(),
    )


def _rehydrate(name: str, document: dict[str, Any]) -> contract.Observation:
    """Rebuild a stored reading without quietly losing half of it.

    Every field a reader could act on has to survive the round
    trip, because the defaults are not neutral. A window
    rebuilt without its scope becomes account scope, and
    account scope is what decides which limit governs -- so
    dropping it puts an exhausted per-feature pool back in
    charge of the provider it does not govern. A reading
    rebuilt without its source claims it was fetched from the
    API when a browser handed it in, and one rebuilt without
    its freshness claims to be live when it has aged out.
    Missing is never zero, and unknown is never live.
    """
    windows = tuple(
        contract.Window(
            label=entry.get("label", ""),
            used_percent=float(entry.get("used_percent", 0.0)),
            resets_in_seconds=entry.get("resets_in_seconds"),
            remaining=entry.get("remaining"),
            limit=entry.get("limit"),
            scope=_stored_scope(entry),
        )
        for entry in document.get("windows", [])
        if isinstance(entry, dict) and entry.get("label")
    )
    credits = document.get("credits")
    if isinstance(credits, dict) and credits.get("state") in contract.CREDIT_STATES:
        restored = contract.Credits(credits["state"], credits.get("detail", ""))
    else:
        restored = contract.Credits()
    plan = document.get("plan")
    return contract.Observation(
        provider=name,
        collected_at=float(document.get("collected_at", 0.0)),
        windows=windows,
        credits=restored,
        plan=plan if isinstance(plan, str) else "",
        source=_stored_choice(document, "source", contract.SOURCES, contract.SOURCE_API),
        freshness=_stored_choice(
            document, "freshness", contract.FRESHNESS_STATES, contract.FRESHNESS_LIVE
        ),
    )


def _stored_choice(
    document: dict[str, Any], field: str, allowed: tuple[str, ...], fallback: str
) -> str:
    """Return a stored value only when it is one this contract knows.

    A stored row can predate a vocabulary, and a value from
    outside the closed set would fail validation on the way
    back out. Falling back keeps an old row readable rather
    than making the whole report unprintable.
    """
    value = document.get(field)
    return value if isinstance(value, str) and value in allowed else fallback


def _stored_scope(entry: dict[str, Any]) -> str:
    """Return a window's stored scope, defaulting to account.

    Account is the right default for a row written before
    scope existed: every adapter emitted account-wide windows
    then, so reading one as account-wide is what it meant.
    """
    return _stored_choice(entry, "scope", contract.SCOPES, contract.SCOPE_ACCOUNT)


def command_forecast(arguments: argparse.Namespace) -> int:
    """Say when a limit runs out, or why that is unknown."""
    kwargs = _state_kwargs(arguments)
    connection = store.connect(**kwargs)
    try:
        document = api.forecast_document(connection, arguments.provider)
    finally:
        connection.close()
    _emit(arguments, document)
    burn = document.get("burn_rate_per_hour", {})
    return EXIT_OK if isinstance(burn, dict) and "value" in burn else EXIT_NO_ANSWER


def command_login(arguments: argparse.Namespace) -> int:
    """Open a visible browser so a provider can be signed in."""
    kwargs = _state_kwargs(arguments)
    observation = browser_collector.login(arguments.provider, **kwargs)
    _emit(arguments, observation.to_dict())
    return EXIT_OK if observation.answered else EXIT_NO_ANSWER


def command_doctor(arguments: argparse.Namespace) -> int:
    """Report what is installed here, without printing a secret.

    Local state only. It does not contact a provider, so a
    credential it reports as present may still be rejected.
    """
    kwargs = _state_kwargs(arguments)
    document = {
        "schema": "trycopilotai/agent-usage/doctor/v1",
        "state_dir": str(config.state_dir(**kwargs)),
        "providers": list(registry.PROVIDERS),
        "browser_providers": list(browser_extract.BROWSER_PROVIDERS),
        "credentials": credentials.describe_all(),
        "browser_available": _browser_available(),
    }
    _emit(arguments, document)
    return EXIT_OK


def _browser_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def command_ingest_token(arguments: argparse.Namespace) -> int:
    """Mint the secret a browser presents to hand in a reading.

    Prints the token, because a secret nobody can read is not
    usable and this one has to be pasted into a bookmarklet.
    It is the only command here that prints one, and it prints
    a secret this tool minted rather than a provider
    credential it found.

    Running it again replaces the token, which is how it is
    revoked: the bookmarklet holding the old one stops being
    accepted.
    """
    kwargs = _state_kwargs(arguments)
    existing = ingest.read_token(**kwargs)
    if existing and not arguments.rotate:
        _emit(
            arguments,
            {
                "schema": "trycopilotai/agent-usage/ingest-token/v1",
                "status": "already_configured",
                "path": ingest.token_file_note(**kwargs),
                "hint": "pass --rotate to replace it and revoke the old one",
            },
        )
        return EXIT_OK
    token = ingest.create_token(**kwargs)
    _emit(
        arguments,
        {
            "schema": "trycopilotai/agent-usage/ingest-token/v1",
            "status": "rotated" if existing else "created",
            "path": ingest.token_file_note(**kwargs),
            "token": token,
        },
    )
    return EXIT_OK


def command_serve(arguments: argparse.Namespace) -> int:
    """Serve the read only surface on loopback."""
    kwargs = _state_kwargs(arguments)
    try:
        server = api.build_server(
            arguments.host,
            arguments.port,
            database_path=config.database_path(**kwargs),
            state_kwargs=kwargs,
            allow_any_host=arguments.allow_any_host,
        )
    except api.NonLoopbackBind as error:
        sys.stderr.write(str(error) + "\n")
        return EXIT_USAGE
    sys.stderr.write(
        "agent-usage listening on http://"
        + str(server.server_address[0])
        + ":"
        + str(server.server_address[1])
        + "\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return EXIT_OK


def _emit(arguments: argparse.Namespace, document: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(document, sort_keys=True, indent=2) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-usage",
        description="Read how much of each AI provider's usage limit is left.",
    )
    parser.add_argument("--state-dir", default=None, help="override where state is kept")
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="read providers now and record the result")
    collect.add_argument("--provider", choices=registry.PROVIDERS, default=None)
    collect.add_argument(
        "--browser",
        action="store_true",
        help="fall back to a browser when the API declines",
    )
    collect.add_argument(
        "--screenshots",
        action="store_true",
        help="save the latest portal screenshot; see the README first",
    )
    collect.set_defaults(handler=command_collect)

    snapshot = commands.add_parser("snapshot", help="show the latest stored reading")
    snapshot.set_defaults(handler=command_snapshot)

    markdown = commands.add_parser("report", help="print the Markdown usage block")
    markdown.set_defaults(handler=command_report)

    forecast = commands.add_parser("forecast", help="say when a limit runs out")
    forecast.add_argument("provider", choices=registry.PROVIDERS)
    forecast.set_defaults(handler=command_forecast)

    login = commands.add_parser("login", help="sign in to a provider in a visible browser")
    login.add_argument("provider", choices=browser_extract.BROWSER_PROVIDERS)
    login.set_defaults(handler=command_login)

    doctor = commands.add_parser("doctor", help="report local credentials and browser")
    doctor.set_defaults(handler=command_doctor)

    ingest_token = commands.add_parser(
        "ingest-token", help="mint the secret a browser presents to hand in a reading"
    )
    ingest_token.add_argument(
        "--rotate",
        action="store_true",
        help="replace an existing token, revoking the old one",
    )
    ingest_token.set_defaults(handler=command_ingest_token)

    serve = commands.add_parser("serve", help="serve the read only API on loopback")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=api.DEFAULT_PORT)
    serve.add_argument(
        "--allow-any-host",
        action="store_true",
        help="bind a routable address; for containers only, adds no authentication",
    )
    serve.set_defaults(handler=command_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return int(arguments.handler(arguments))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
