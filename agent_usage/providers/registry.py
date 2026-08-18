"""The provider registry, which fails closed.

An unknown provider name is refused rather than skipped. A
run that silently collects four of five providers reads as a
complete answer, and the missing one is exactly the provider
a reader needed to know about.
"""

from __future__ import annotations

from typing import Any, Callable

from .. import contract
from . import claude, codex, grok, kimi, zai

ADAPTERS: dict[str, Any] = {
    "claude": claude,
    "codex": codex,
    "grok": grok,
    "kimi": kimi,
    "zai": zai,
}

PROVIDERS = tuple(sorted(ADAPTERS))


class UnknownProvider(KeyError):
    """A provider name outside the registry."""


def adapter(name: str) -> Any:
    if name not in ADAPTERS:
        raise UnknownProvider(name)
    return ADAPTERS[name]


def collect(name: str, **kwargs: Any) -> contract.Observation:
    return adapter(name).collect(**kwargs)


def collect_all(names: tuple[str, ...] | None = None, **kwargs: Any) -> list[contract.Observation]:
    selected = PROVIDERS if names is None else tuple(names)
    for name in selected:
        if name not in ADAPTERS:
            raise UnknownProvider(name)
    return [collect(name, **kwargs) for name in selected]
