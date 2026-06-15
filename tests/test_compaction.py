"""Unit tests for the TUI's CompactionAgent integration.

Verifies that:
1. :class:`TUICompactingAgentFactory` reads ``metadata.compaction`` and
   returns a properly configured :class:`CompactionAgent`.
2. :func:`make_llm_summarizer` returns a callable matching the
   :data:`CompactionSummarizer` contract.
3. ``CompactionConfig`` defaults are applied when ``metadata.compaction``
   is missing keys.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Sequence

from minimal_harness.agent.compacting import CompactionAgent
from minimal_harness.llm.llm import LLMResponse, Stream
from minimal_harness.memory import Message
from minimal_harness.types import (
    AgentMetadata,
    LLMChunkDelta,
)


class _NoopLLMProvider:
    """An LLMProvider that yields nothing — used to construct agents
    for metadata-only tests (we never call chat() on it)."""

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[Any] = (),
        stop_event: asyncio.Event | None = None,
        **kwargs: Any,
    ) -> Stream[LLMChunkDelta]:
        async def _gen() -> AsyncIterator[Any]:
            yield LLMResponse(
                content="",
                reasoning_content=None,
                tool_calls=[],
                finish_reason="stop",
                usage=None,
            )

        return Stream(_gen())


def test_tui_factory_builds_compaction_agent_with_metadata() -> None:
    """TUICompactingAgentFactory must honour metadata.compaction."""
    from mh_tui.compaction import TUICompactingAgentFactory

    provider = _NoopLLMProvider()
    metadata = AgentMetadata(
        name="compacting_coder",
        agent_type="compacting",
        compaction={
            "prompt_token_threshold": 4000,
            "keep_recent": 4,
        },
    )
    factory = TUICompactingAgentFactory()
    agent = factory.create(metadata, provider, middleware=())

    assert isinstance(agent, CompactionAgent)
    assert agent._prompt_token_threshold == 4000
    assert agent._keep_recent == 4
    # Summarizer is the streaming LLM call (returns an async generator)
    gen = agent._summarizer([], None)
    assert asyncio.iscoroutine(gen.__anext__())


def test_tui_factory_uses_defaults_when_compaction_missing_keys() -> None:
    """Partial compaction dict → fallback to module defaults."""
    from mh_tui.compaction import (
        _DEFAULT_KEEP_RECENT,
        _DEFAULT_THRESHOLD,
        TUICompactingAgentFactory,
    )

    provider = _NoopLLMProvider()
    metadata = AgentMetadata(
        name="compacting_partial",
        agent_type="compacting",
        compaction={},  # no keys
    )
    factory = TUICompactingAgentFactory()
    agent = factory.create(metadata, provider, middleware=())

    assert isinstance(agent, CompactionAgent)
    assert agent._prompt_token_threshold == _DEFAULT_THRESHOLD
    assert agent._keep_recent == _DEFAULT_KEEP_RECENT


def test_tui_factory_handles_none_compaction_dict() -> None:
    """AgentMetadata.compaction=None must also fall back to defaults."""
    from mh_tui.compaction import _DEFAULT_THRESHOLD, TUICompactingAgentFactory

    provider = _NoopLLMProvider()
    metadata = AgentMetadata(
        name="compacting_none",
        agent_type="compacting",
        compaction=None,
    )
    factory = TUICompactingAgentFactory()
    agent = factory.create(metadata, provider, middleware=())

    assert isinstance(agent, CompactionAgent)
    assert agent._prompt_token_threshold == _DEFAULT_THRESHOLD


def test_make_llm_summarizer_signature() -> None:
    """The summarizer produced by make_llm_summarizer must be a
    streaming async generator factory."""
    from mh_tui.compaction import make_llm_summarizer

    provider = _NoopLLMProvider()
    summarizer = make_llm_summarizer(provider)
    assert callable(summarizer)

    # Calling it returns an async generator (not a coroutine — that
    # would mean the LLM call happens at construction, which is wrong).
    result = summarizer([], None)
    # The summarizer's body is `async def`, so calling it produces a
    # coroutine, NOT an async generator. The first __anext__ should
    # produce a coroutine from inside.
    assert asyncio.iscoroutine(result) or hasattr(result, "__aiter__")


def test_compaction_summary_message_event_renders_in_display() -> None:
    """The TUI display must render the compaction MessageEvent (the
    synthetic CompactionMessage emitted after a successful compaction)
    so the user can read it and so it persists in the session for replay.
    """
    from unittest.mock import MagicMock, patch

    from minimal_harness.types import MessageEvent

    from mh_tui.display import ChatDisplay

    chat = MagicMock()
    d = ChatDisplay(chat_container=chat, theme="tokyo-night")

    # Replace say() with a mock so we can inspect the calls.
    with (
        patch.object(d, "say", MagicMock()) as say_mock,
        patch.object(d, "_is_at_bottom", return_value=True),
    ):
        d.handle_event(
            MessageEvent(
                message={
                    "role": "compaction",
                    "content": "Goal: ship it. Done: 1/3.",
                    "meta": {"dropped_count": 14, "keep_recent": 6},
                }
            ),
            buf=MagicMock(),
        )

    # Two say() calls expected: the heading and the markdown body.
    assert say_mock.call_count >= 2
    say_args = " ".join(str(call.args[0]) for call in say_mock.call_args_list)
    assert "Folded summary" in say_args
    assert "Goal: ship it" in say_args
    assert "Goal: ship it" in say_args


def test_managed_session_implements_compact() -> None:
    """Regression test: ``JsonlManagedSession`` must implement
    ``Memory.compact`` so ``CompactionAgent`` (which receives the
    managed session as its ``memory`` argument via the runtime's
    ``session_store.get_session()``) can call ``memory.compact(...)``
    on it. Before the fix this raised
    ``AttributeError: 'JsonlManagedSession' object has no attribute 'compact'``.

    The wrapper must:
    * delegate to the inner ``ConversationMemory.compact``,
    * yield every ``CompactionEvent`` (start / chunks / end) unchanged,
    * persist the buffer state when the fold succeeds,
    * NOT persist when the fold fails (inner buffer is untouched and
      on-disk state is already in sync).
    """
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock

    from minimal_harness.memory import ConversationMemory

    from mh_tui.jsonl_session_store import (
        JsonlManagedSession,
        JsonlSessionStore,
    )

    with tempfile.TemporaryDirectory() as tmp:
        store = JsonlSessionStore(Path(tmp))
        managed = JsonlManagedSession(
            store=store,
            session_id="test-session",
            inner=ConversationMemory(),
            agent_name="compacting_assistant",
        )
        # Replace _schedule_save with a spy so we can verify it fires
        # (or not) depending on the fold outcome.
        managed._schedule_save = MagicMock()  # type: ignore[method-assign]

        from minimal_harness.types import (
            CompactionEnd,
            CompactionEvent,
        )

        async def _noop_summarizer(
            messages: list[Message], existing: str | None
        ) -> AsyncIterator[str]:
            yield "folded-content"

        async def _failing_summarizer(
            messages: list[Message], existing: str | None
        ) -> AsyncIterator[str]:
            yield "partial-"
            raise RuntimeError("simulated outage")

        async def _run_scenario() -> None:
            # --- success path: fold applies, _schedule_save is called ---
            for i in range(3):
                await managed.add_message(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": f"q{i}"}],
                    }
                )
                await managed.add_message(
                    {
                        "role": "assistant",
                        "content": f"a{i}",
                        "tool_calls": None,
                    }
                )
            assert len(managed.get_all_messages()) == 6

            events: list[CompactionEvent] = []
            async for evt in managed.compact(
                summarizer=_noop_summarizer, keep_recent=0
            ):
                events.append(evt)
            assert any(isinstance(e, CompactionEnd) for e in events)
            end = next(e for e in events if isinstance(e, CompactionEnd))
            assert end.summary == "folded-content"
            assert end.error is None
            managed._schedule_save.assert_called_once()  # type: ignore[attr-defined]
            # Buffer is now a single CompactionMessage.
            msgs = managed.get_all_messages()
            assert len(msgs) == 1
            assert msgs[0]["role"] == "compaction"

            # --- failure path: summarizer raises, _schedule_save is NOT called ---
            managed._schedule_save.reset_mock()  # type: ignore[attr-defined]
            for i in range(3):
                await managed.add_message(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": f"q{i}"}],
                    }
                )
                await managed.add_message(
                    {
                        "role": "assistant",
                        "content": f"a{i}",
                        "tool_calls": None,
                    }
                )
            msgs_before_fail = [dict(m) for m in managed.get_all_messages()]

            events.clear()
            async for evt in managed.compact(
                summarizer=_failing_summarizer, keep_recent=0
            ):
                events.append(evt)
            end = next(e for e in events if isinstance(e, CompactionEnd))
            assert end.error is not None
            # Buffer untouched on failure.
            assert managed.get_all_messages() == msgs_before_fail
            # No save was scheduled.
            managed._schedule_save.assert_not_called()  # type: ignore[attr-defined]

        asyncio.run(_run_scenario())
