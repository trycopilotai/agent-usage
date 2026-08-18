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

from . import api, config, contract, derive, report, store
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
    windows = tuple(
        contract.Window(
            label=entry.get("label", ""),
            used_percent=float(entry.get("used_percent", 0.0)),
            resets_in_seconds=entry.get("resets_in_seconds"),
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
    )


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
