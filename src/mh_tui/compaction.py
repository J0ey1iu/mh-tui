"""CompactionAgent support — streaming LLM summarizer + TUI factory.

When a TUI agent is registered with ``agent_type="compacting"``, the
runtime needs a :class:`CompactionConfig` carrying a streaming
summarizer. This module provides:

- :func:`make_llm_summarizer` — builds a streaming summarizer that
  drives the given LLM provider
- :class:`TUICompactingAgentFactory` — :class:`LocalAgentFactory` that
  builds a :class:`CompactionAgent` using the TUI's summarizer, reading
  the per-agent threshold / keep_recent from ``AgentMetadata.compaction``

Compaction events (``CompactionStart`` / ``CompactionChunk`` /
``CompactionEnd``) flow back through the runtime's event queue. The
TUI display layer subscribes to them in :mod:`mh_tui.display`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, AsyncIterator, Sequence

from minimal_harness.memory import Message
from minimal_harness.types import (
    CompactionConfig,
    CompactionSettings,
    CompactionSummarizer,
)

if TYPE_CHECKING:
    from minimal_harness.agent.middleware import Middleware
    from minimal_harness.llm.llm import LLMProvider
    from minimal_harness.types import AgentMetadata

_SUMMARIZER_SYSTEM_PROMPT = (
    "You are a conversation compressor. You receive the recent "
    "conversation transcript and a prior summary (if any). Your job is "
    "to produce a single, dense summary that preserves:\n"
    "  1. The user's original goal and any updated goals.\n"
    "  2. Concrete facts, decisions, and outcomes (file paths, "
    "commands, identifiers, errors).\n"
    "  3. The current state of any in-progress work.\n"
    "Be terse. Use bullet points. Do not include pleasantries."
)


def _format_messages_for_summary(
    messages: list[Message], existing_summary: str | None
) -> str:
    """Render the to-fold slice + optional prior summary as a single
    user-turn payload. JSON to keep the LLM's structure-aware parsing
    happy regardless of provider quirks.
    """
    payload: dict[str, Any] = {}
    if existing_summary:
        payload["prior_summary"] = existing_summary
    payload["messages_to_fold"] = [
        {"role": m.get("role", "?"), "content": m.get("content", "")} for m in messages
    ]
    return (
        "Fold the following into an updated summary. "
        "Return only the new summary text — no preamble, no labels.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def make_llm_summarizer(
    llm_provider: LLMProvider,
) -> CompactionSummarizer:
    """Return a streaming summarizer that drives the given LLM provider.

    The returned callable matches :data:`CompactionSummarizer`. Each
    call:

    1. Builds a two-turn chat (system: summarizer instructions;
       user: the to-fold messages + optional prior summary).
    2. Calls ``llm_provider.chat(messages=...)``.
    3. Yields each ``LLMChunkDelta.content`` as it arrives.

    The provider is captured by closure; the same LLM instance serves
    both the agent's main loop and the summarization calls. They are
    sequential (compaction only runs after a completed LLM turn), so
    no concurrency hazard.
    """

    async def summarizer(
        messages: list[Message], existing_summary: str | None
    ) -> AsyncIterator[str]:
        payload = _format_messages_for_summary(messages, existing_summary)
        # Wrap the payload in the standard ``UserMessage`` content-part
        # shape (``[{"type": "text", "text": "..."}]``) so the
        # downstream ``_convert_messages`` in the OpenAI / Anthropic
        # provider can iterate ``msg["content"]`` as a list of dicts.
        # Passing a raw string here iterates the string's characters
        # and crashes with "string indices must be integers".
        chat_messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SUMMARIZER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [{"type": "text", "text": payload}],
            },
        ]
        stream = await llm_provider.chat(messages=chat_messages, tools=[])
        async for chunk in stream:
            if chunk.content:
                yield chunk.content

    return summarizer


_DEFAULT_THRESHOLD = 8000
_DEFAULT_KEEP_RECENT = 6


def compaction_settings_or_defaults(
    settings: CompactionSettings | None,
) -> CompactionSettings:
    """Return ``settings`` with defaults filled in for any missing key.

    Reads from the optional ``CompactionSettings`` TypedDict and
    produces a fully populated copy. Used by the TUI factory and the
    ``/compact`` slash action to keep their default-handling in one
    place.
    """
    if settings is None:
        return {
            "prompt_token_threshold": _DEFAULT_THRESHOLD,
            "keep_recent": _DEFAULT_KEEP_RECENT,
        }
    return {
        "prompt_token_threshold": int(
            settings.get("prompt_token_threshold", _DEFAULT_THRESHOLD)
        ),
        "keep_recent": int(settings.get("keep_recent", _DEFAULT_KEEP_RECENT)),
    }


class TUICompactingAgentFactory:
    """LocalAgentFactory for ``agent_type="compacting"`` agents.

    Reads per-agent parameters from ``AgentMetadata.compaction`` (a
    :class:`CompactionSettings` TypedDict with optional
    ``prompt_token_threshold`` and ``keep_recent`` keys) and builds a
    :class:`CompactionConfig` using :func:`make_llm_summarizer`
    against the LLM provider supplied at agent-creation time.

    Register with the TUI runtime either at construction time
    (``AgentRuntime(local_agent_factories={"compacting": TUICompactingAgentFactory()})``)
    or after the fact (``runtime.register_local_agent_factory("compacting", ...)``).
    """

    def create(
        self,
        metadata: "AgentMetadata",
        llm_provider: "LLMProvider",
        middleware: Sequence["Middleware"],
        **kwargs: Any,
    ) -> Any:
        from minimal_harness.agent.compacting import CompactionAgent

        config: CompactionConfig | None = kwargs.get("compaction_config")
        if config is not None:
            threshold = config.prompt_token_threshold
            keep_recent = config.keep_recent
            summarizer = config.summarizer
        else:
            settings = compaction_settings_or_defaults(metadata.compaction)
            threshold = int(settings.get("prompt_token_threshold", 8000))
            keep_recent = int(settings.get("keep_recent", 6))
            summarizer = make_llm_summarizer(llm_provider)

        return CompactionAgent(
            llm_provider=llm_provider,
            summarizer=summarizer,
            prompt_token_threshold=threshold,
            keep_recent=keep_recent,
            max_iterations=kwargs.get("max_iterations", 100),
            middleware=middleware,
            emit_message_events=kwargs.get("emit_message_events", True),
        )
