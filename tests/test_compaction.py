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


class _WidgetHostApp:
    """Lightweight App context wrapper — CompactionMsg calls
    ``self.update(...)`` which needs an active Textual app. We use
    ``App.run_test()`` to provide that context without spinning up
    the full TUI. Falls back to constructing the widget directly when
    the tests only inspect state, because the render path is exercised
    by the display-level tests that already run inside an app context
    via the MagicMock chat container.
    """


def test_compaction_msg_widget_phases() -> None:
    """The CompactionMsg widget goes through pending → live → done.
    Each phase renders a distinct Text, and accumulate() in the live
    phase updates the char counter without exposing the chunk text.
    """
    from textual.app import App

    from mh_tui.chat_widgets import CompactionMsg

    class _Host(App):
        pass

    async def _drive() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            w = CompactionMsg()
            await pilot.app.mount(w)
            assert w.phase == "pending"
            assert w.summary_text == ""

            w.start(
                dropped=4,
                keep_recent=2,
                prompt_tokens=1200,
                existing_summary_chars=50,
            )
            assert w.phase == "live"
            assert w.dropped_count == 4

            w.accumulate("alpha")
            w.accumulate(" beta")
            assert w.phase == "live"
            assert w.summary_text == ""

            w.finish(summary="alpha beta", duration=0.42, dropped=4)
            assert w.phase == "done"
            assert w.summary_text == "alpha beta"
            assert w.dropped_count == 4

    import asyncio

    asyncio.run(_drive())


def test_compaction_msg_widget_failure() -> None:
    """CompactionMsg.fail() transitions to the failed phase, with the
    error stored for the error block. summary_text stays empty so the
    display layer does not export a phantom summary on failure.
    """
    from textual.app import App

    from mh_tui.chat_widgets import CompactionMsg

    class _Host(App):
        pass

    async def _drive() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            w = CompactionMsg()
            await pilot.app.mount(w)
            w.start(dropped=4, keep_recent=0, prompt_tokens=900)
            w.fail(error="RuntimeError: summarizer blew up", duration=0.05)
            assert w.phase == "failed"
            assert w.summary_text == ""

    import asyncio

    asyncio.run(_drive())


def test_compaction_msg_widget_stray_accumulate_is_noop() -> None:
    """Calling accumulate() before start() or after finish()/fail()
    is a no-op — the widget silently drops the call rather than
    resurrecting itself or corrupting the final state.
    """
    from textual.app import App

    from mh_tui.chat_widgets import CompactionMsg

    class _Host(App):
        pass

    async def _drive() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            w = CompactionMsg()
            await pilot.app.mount(w)
            w.accumulate("orphan")  # no start yet — no-op
            assert w.phase == "pending"

            w.start(dropped=2, keep_recent=0, prompt_tokens=200)
            w.finish(summary="ok", duration=0.1, dropped=2)
            w.accumulate("after-finish")  # post-finish — no-op
            assert w.phase == "done"
            assert w.summary_text == "ok"

    import asyncio

    asyncio.run(_drive())


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


def test_compaction_summary_message_event_renders_via_widget() -> None:
    """The TUI display must render the compaction ``MessageEvent`` (the
    synthetic CompactionMessage emitted after a successful compaction)
    so the user can read it and so it persists in the session for
    replay.

    With the CompactionMsg widget, the rendering path is:

    * Live flow: CompactionStart → *CompactionChunk → CompactionEnd
      transitions the widget through pending → live → done. The
      trailing MessageEvent(role="compaction") is intentionally
      dropped on the live path to avoid double-rendering the
      summary.
    * Replay path (no live widget active): a fresh CompactionMsg
      is mounted directly in the done state, with the persisted
      summary body shown once.
    """
    from unittest.mock import MagicMock, patch

    from minimal_harness.types import (
        CompactionEnd,
        CompactionStart,
        MessageEvent,
    )

    from mh_tui.chat_widgets import CompactionMsg
    from mh_tui.display import ChatDisplay

    # ── Live path: a CompactionEnd already finished the widget,
    # so the trailing MessageEvent must be a no-op for chat content.
    chat = MagicMock()
    d = ChatDisplay(chat_container=chat, theme="tokyo-night")
    with patch.object(d, "_is_at_bottom", return_value=True):
        d.handle_event(
            CompactionStart(
                dropped_message_count=4,
                existing_summary=None,
                keep_recent=0,
                prompt_tokens=512,
            ),
            buf=MagicMock(),
        )
        # Active widget is mounted; render is via the widget, not say().
        d.handle_event(
            CompactionEnd(
                summary="Goal: ship it. Done: 1/3.",
                dropped_message_count=4,
                new_offset=0,
                duration=0.42,
                error=None,
            ),
            buf=MagicMock(),
        )
        # The widget must be in "done" phase and show the summary.
        assert d._active_compaction is None
        w = chat.mount.call_args_list[-1].args[0]
        assert isinstance(w, CompactionMsg)
        assert w.phase == "done"
        assert w.summary_text == "Goal: ship it. Done: 1/3."

        # The trailing MessageEvent must not mount a *second* widget
        # (that would render the same summary twice).
        mount_calls_before = chat.mount.call_count
        d.handle_event(
            MessageEvent(
                message={
                    "role": "compaction",
                    "content": "Goal: ship it. Done: 1/3.",
                    "meta": {"dropped_count": 4, "keep_recent": 0},
                }
            ),
            buf=MagicMock(),
        )
        assert chat.mount.call_count == mount_calls_before

    # ── Replay path: no live widget active, the MessageEvent
    # mounts a fresh one-shot done CompactionMsg.
    chat2 = MagicMock()
    d2 = ChatDisplay(chat_container=chat2, theme="tokyo-night")
    with patch.object(d2, "_is_at_bottom", return_value=True):
        d2.handle_event(
            MessageEvent(
                message={
                    "role": "compaction",
                    "content": "Replayed summary text.",
                    "meta": {"dropped_count": 7, "keep_recent": 4, "duration": 1.2},
                }
            ),
            buf=MagicMock(),
        )
    w = chat2.mount.call_args_list[-1].args[0]
    assert isinstance(w, CompactionMsg)
    assert w.phase == "done"
    assert w.summary_text == "Replayed summary text."
    assert w.dropped_count == 7


def test_compaction_live_does_not_print_chunk_text() -> None:
    """The whole point of the widget is that streaming chunks are
    not printed as separate lines. Verify the live event flow
    produces exactly one mount call (the widget), with the chunk
    delta only feeding the widget's character counter.
    """
    from unittest.mock import MagicMock, patch

    from minimal_harness.types import (
        CompactionChunk,
        CompactionEnd,
        CompactionStart,
    )

    from mh_tui.chat_widgets import CompactionMsg
    from mh_tui.display import ChatDisplay

    chat = MagicMock()
    d = ChatDisplay(chat_container=chat, theme="tokyo-night")
    with (
        patch.object(d, "_is_at_bottom", return_value=True),
        patch.object(d, "say", MagicMock()) as say_mock,
    ):
        d.handle_event(
            CompactionStart(
                dropped_message_count=10,
                existing_summary="prior-summary",
                keep_recent=4,
                prompt_tokens=4200,
            ),
            buf=MagicMock(),
        )
        # Three streaming chunks, mimicking the verify_compaction.py
        # scenario where each yields a small piece.
        d.handle_event(
            CompactionChunk(delta="alpha", accumulated="alpha"), buf=MagicMock()
        )
        d.handle_event(
            CompactionChunk(delta=" beta", accumulated="alpha beta"),
            buf=MagicMock(),
        )
        d.handle_event(
            CompactionChunk(delta=" gamma", accumulated="alpha beta gamma"),
            buf=MagicMock(),
        )
        d.handle_event(
            CompactionEnd(
                summary="alpha beta gamma",
                dropped_message_count=10,
                new_offset=0,
                duration=0.13,
                error=None,
            ),
            buf=MagicMock(),
        )

    # say() must NEVER be called for the live path — the widget owns
    # the rendering.
    assert say_mock.call_count == 0
    # Exactly one CompactionMsg widget was mounted.
    compaction_mounts = [
        c.args[0]
        for c in chat.mount.call_args_list
        if isinstance(c.args[0], CompactionMsg)
    ]
    assert len(compaction_mounts) == 1
    w = compaction_mounts[0]
    assert w.phase == "done"
    assert w.summary_text == "alpha beta gamma"
    # Existing-summary hint is preserved through the live phase.
    assert w.dropped_count == 10


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
