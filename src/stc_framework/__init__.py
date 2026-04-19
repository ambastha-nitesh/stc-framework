"""STC Framework — Stalwart · Trainer · Critic.

Public entrypoints:

- :class:`stc_framework.STCSystem`: orchestrates the three personas.
- :mod:`stc_framework.errors`: typed error taxonomy.
- :mod:`stc_framework.spec`: declarative specification loader and models.

Example:
-------
>>> from stc_framework import STCSystem
>>> system = STCSystem.from_spec("spec-examples/financial_qa.yaml")
>>> result = system.query("What was FY2024 revenue?")
>>> result.response
'...'

"""

from __future__ import annotations

from stc_framework._version import __version__
from stc_framework.errors import STCError

__all__ = ["STCError", "STCSystem", "__version__"]


def __getattr__(name: str) -> object:  # pragma: no cover - lazy import shim
    # Lazy import of STCSystem so `import stc_framework` is cheap and does not
    # require optional dependencies.
    if name == "STCSystem":
        from stc_framework.system import STCSystem

        return STCSystem
    raise AttributeError(f"module 'stc_framework' has no attribute {name!r}")
