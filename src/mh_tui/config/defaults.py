"""Shared default configuration data.

All modules in the config subpackage import defaults from here to avoid
circular imports. This module has zero internal dependencies.

Defaults are read from ``MH_*`` env vars (the same names the SDK used
to expose via ``Settings``). When the env var is unset, hard-coded
fallbacks are used.
"""

from __future__ import annotations

import os
from typing import Any


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val else default


DEFAULT_BASE_URL: str = _env("MH_BASE_URL", "https://aihubmix.com/v1")
DEFAULT_MODEL: str = _env("MH_MODEL", "deepseek-v4-flash")
DEFAULT_THEME: str = _env("MH_THEME", "tokyo-night")
DEFAULT_MAX_ITERATIONS: int = _env_int("MH_MAX_ITERATIONS", 100)


DEFAULT_CONFIG: dict[str, Any] = {
    "base_url": DEFAULT_BASE_URL,
    "api_key": _env("MH_API_KEY", ""),
    "model": DEFAULT_MODEL,
    "tools_path": "",
    "theme": DEFAULT_THEME,
    "provider": "openai",
    "reasoning_effort": None,
    "default_agent": "general_assistant",
}

DEFAULT_AGENTS: list[dict[str, Any]] = [
    {
        "name": "general_assistant",
        "display_name": "General Assistant",
        "description": "General-purpose assistant for everyday tasks, Q&A, and conversation",
        "system_prompt": "general_assistant.md",
        "default_tools": ["handoff", "discover_agents"],
    },
    {
        "name": "code_assistant",
        "display_name": "Code Assistant",
        "description": "Specialized in software development, debugging, code review, and architecture",
        "system_prompt": "code_assistant.md",
        "default_tools": ["handoff", "discover_agents"],
    },
    {
        "name": "research_assistant",
        "display_name": "Research Assistant",
        "description": "Focused on deep research, analysis, fact-checking, and information synthesis",
        "system_prompt": "research_assistant.md",
        "default_tools": ["handoff", "discover_agents"],
    },
    {
        "name": "compacting_assistant",
        "display_name": "Compacting Assistant",
        "description": (
            "Long-running assistant that auto-folds older messages into a "
            "summary when the prompt grows large. Use for multi-hour "
            "conversations where the simple agent would run out of context."
        ),
        "system_prompt": "general_assistant.md",
        "default_tools": ["handoff", "discover_agents"],
        "agent_type": "compacting",
        "compaction": {
            "prompt_token_threshold": 8000,
            "keep_recent": 6,
        },
    },
]

AGENT_PROMPTS: dict[str, str] = {
    "general_assistant.md": (
        "You are a versatile general-purpose assistant. "
        "You excel at handling everyday tasks, answering questions, "
        "engaging in conversation, and helping with a wide variety of topics. "
        "Be helpful, friendly, and thorough in your responses."
    ),
    "code_assistant.md": (
        "You are a specialized coding assistant with deep expertise "
        "in software development. You excel at writing, debugging, "
        "reviewing, and refactoring code across multiple programming "
        "languages. Provide clear explanations, best practices, "
        "and well-structured code examples."
    ),
    "research_assistant.md": (
        "You are a research-focused assistant specialized in deep analysis "
        "and information synthesis. You excel at breaking down complex topics, "
        "verifying facts, connecting ideas across domains, and presenting "
        "well-structured findings. Be thorough, precise, and cite your reasoning."
    ),
}
