"""Prompt registry adapters."""

from stc_framework.adapters.prompts.base import PromptRecord, PromptRegistry
from stc_framework.adapters.prompts.file_registry import FilePromptRegistry

__all__ = ["FilePromptRegistry", "PromptRecord", "PromptRegistry"]
