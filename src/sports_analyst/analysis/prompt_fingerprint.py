"""A fingerprint of the prompt text, so runs and saved reports name the prompts that produced them.

It hashes every text literal compiled into the modules that write model prompts: contracts, sport and
domain guidance, voice guides, agent and planner instructions, and tool descriptions. Any wording change
there changes the fingerprint; nobody has to remember to bump a number. Non-prompt text in those modules,
such as log messages, also counts, so the fingerprint can change without a prompt changing, never the reverse.
It is stable for a given Python version; docstring handling differs between versions.
"""
from __future__ import annotations

import hashlib
import inspect
from collections.abc import Iterator
from functools import lru_cache
from types import CodeType, ModuleType
from typing import Any

PROMPT_MODULES = (
    "sports_analyst.analysis.instructions",
    "sports_analyst.analysis.agents",
    "sports_analyst.analysis.calculations",
)


def _code_strings(code: CodeType) -> Iterator[str]:
    for constant in code.co_consts:
        if isinstance(constant, str):
            yield constant
        elif isinstance(constant, CodeType):
            # Nested functions, tools, lambdas and comprehensions carry their own literals.
            yield from _code_strings(constant)


def _value_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _value_strings(key)
            yield from _value_strings(item)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _value_strings(item)


def _function_code(value: Any) -> CodeType | None:
    function = getattr(value, "__func__", value)  # staticmethod / classmethod
    function = getattr(function, "fget", function)  # property
    code = getattr(inspect.unwrap(function), "__code__", None) if callable(function) else None
    return code if isinstance(code, CodeType) else None


def _module_strings(module: ModuleType) -> Iterator[str]:
    for value in vars(module).values():
        if inspect.isclass(value) and value.__module__ == module.__name__:
            for member in vars(value).values():
                if code := _function_code(member):
                    yield from _code_strings(code)
        elif inspect.isfunction(value) and value.__module__ == module.__name__:
            yield from _code_strings(value.__code__)
        else:
            yield from _value_strings(value)


@lru_cache(maxsize=1)
def prompt_fingerprint() -> str:
    """Computed once per process from the loaded prompt modules."""
    from importlib import import_module

    strings = {text for name in PROMPT_MODULES for text in _module_strings(import_module(name))}
    digest = hashlib.sha256("\0".join(sorted(strings)).encode("utf-8")).hexdigest()
    return f"prompts-{digest[:12]}"
