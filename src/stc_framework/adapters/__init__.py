"""Adapter Protocols and default implementations.

Every external integration is expressed as a :class:`typing.Protocol` in a
``base.py`` module. Default, in-process implementations live alongside the
Protocol so the library works zero-install; optional adapters that talk to
real infrastructure (Qdrant, Ollama, LiteLLM, Langfuse, ...) are guarded by
extras in ``pyproject.toml``.
"""
