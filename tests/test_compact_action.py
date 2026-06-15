"""Tests for the merged ``/compact`` slash action.

The slash command must drive the same ``compact_session`` runtime
method that backs the auto-compaction path — same
``CompactionStart / Chunk / End`` event stream, same
``CompactionMsg`` widget. The legacy "submit a prompt that asks
the LLM to summarise" hack is gone.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest
from mh_tui.actions.compact import action_compact
from mh_tui.runtime_session import SessionStatus


def _make_app(
    *,
    has_session: bool = True,
    is_running: bool = False,
    has_compact_session: bool = True,
    compact_events: list[Any] | None = None,
) -> MagicMock:
    """Build a minimal stand-in for TUIApp.

    Only the attributes touched by :func:`action_compact` are wired
    up. The compact event stream is a queue that the test controls.
    """
    app = MagicMock()

    # Ctrl side
    sess = MagicMock() if has_session else None
    if has_session:
        sess.session.memory_id = "sid-1"
    app._ctrl.current_session = sess
    app._ctrl.get_session_status = MagicMock(
        return_value=SessionStatus.RUNNING if is_running else SessionStatus.IDLE
    )
    app._ctrl.get_buf = MagicMock(return_value=MagicMock())

    # Display
    app._chat_display = MagicMock()
    app._chat_display.handle_event = MagicMock()

    # Runtime — compact_session is an async generator. Build a stub
    # that yields the events the test wants and records calls.
    events = compact_events if compact_events is not None else []

    async def _gen() -> AsyncIterator[Any]:
        for evt in events:
            yield evt

    runtime = MagicMock()
    if has_compact_session:
        runtime.compact_session = MagicMock(return_value=_gen())
    else:
        del runtime.compact_session
    app._runtime = runtime
    return app


@pytest.mark.asyncio
async def test_compact_action_uses_runtime_compact_session() -> None:
    """The slash action must call ``runtime.compact_session(sid)`` and
    forward every event to the display's ``handle_event`` — the same
    path the auto-compaction uses.
    """
    from minimal_harness.types import CompactionEnd, CompactionStart

    start = CompactionStart(
        dropped_message_count=4,
        existing_summary=None,
        keep_recent=2,
        prompt_tokens=9000,
    )
    end = CompactionEnd(
        summary="manual fold",
        dropped_message_count=4,
        new_offset=0,
        duration=0.1,
        error=None,
    )
    app = _make_app(compact_events=[start, end])

    await action_compact(app)

    app._runtime.compact_session.assert_called_once_with("sid-1")
    # Start, End, then the trailing MessageEvent(role="compaction")
    # that persists the synthetic summary — same trio the
    # auto-compaction path produces.
    from minimal_harness.types import MessageEvent

    msg_events = [
        c.args[0]
        for c in app._chat_display.handle_event.call_args_list
        if isinstance(c.args[0], MessageEvent)
    ]
    assert len(msg_events) == 1
    assert msg_events[0].message["role"] == "compaction"
    assert msg_events[0].message["content"] == "manual fold"


@pytest.mark.asyncio
async def test_compact_action_refuses_when_no_session() -> None:
    """Without an active session, the action must notify and return
    without touching the runtime or the display.
    """
    app = _make_app(has_session=False)
    await action_compact(app)

    app.notify.assert_called_once()
    app._runtime.compact_session.assert_not_called()
    app._chat_display.handle_event.assert_not_called()


@pytest.mark.asyncio
async def test_compact_action_refuses_while_agent_is_running() -> None:
    """Compacting while the agent loop is in flight would race with
    the loop's ``add_message`` calls — refuse with a warning.
    """
    app = _make_app(is_running=True)
    await action_compact(app)

    app.notify.assert_called_once()
    app._runtime.compact_session.assert_not_called()


@pytest.mark.asyncio
async def test_compact_action_surfaces_compaction_failure() -> None:
    """When the runtime reports an error, the action must notify the
    user and NOT emit a phantom ``MessageEvent(role="compaction")``.
    """
    from minimal_harness.types import CompactionEnd, CompactionStart, MessageEvent

    start = CompactionStart(
        dropped_message_count=4,
        existing_summary=None,
        keep_recent=2,
        prompt_tokens=9000,
    )
    end = CompactionEnd(
        summary="",  # partial fold discarded
        dropped_message_count=0,
        new_offset=0,
        duration=0.05,
        error="RuntimeError: summarizer down",
    )
    app = _make_app(compact_events=[start, end])

    await action_compact(app)

    msg_events = [
        c.args[0]
        for c in app._chat_display.handle_event.call_args_list
        if isinstance(c.args[0], MessageEvent)
    ]
    assert msg_events == []
    # The error was surfaced via app.notify (any severity=error call).
    error_calls = [
        c for c in app.notify.call_args_list if c.kwargs.get("severity") == "error"
    ]
    assert error_calls
    assert "summarizer down" in str(error_calls[0])


@pytest.mark.asyncio
async def test_compact_action_refuses_when_runtime_lacks_method() -> None:
    """If the runtime is an older version that doesn't support
    ``compact_session``, refuse with an error notification rather
    than crashing.
    """
    app = _make_app(has_compact_session=False)
    await action_compact(app)

    app.notify.assert_called_once()
    error_calls = [
        c for c in app.notify.call_args_list if c.kwargs.get("severity") == "error"
    ]
    assert error_calls
