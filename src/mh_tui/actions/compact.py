"""Compact action — triggers a manual compaction on the current session.

This is the merged /compact path: it uses the same
``CompactionStart / CompactionChunk / CompactionEnd`` event stream
and the same ``CompactionMsg`` widget as the auto-compaction in
``CompactionAgent``. There is no longer a "submit a prompt that
asks the LLM to summarise" hack — the runtime drives the
summarizer, and the buffer is folded atomically by
``Memory.compact()``.

The action is only valid when the session is IDLE; calling it
while the agent is in flight would race with the loop's
``add_message`` calls and corrupt the buffer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mh_tui.runtime_session import SessionStatus

if TYPE_CHECKING:
    from mh_tui.app import TUIApp

logger = logging.getLogger(__name__)


async def action_compact(app: TUIApp) -> None:
    sess = app._ctrl.current_session
    if sess is None:
        app.notify("No active session to compact", severity="warning")
        return

    sid = sess.session.memory_id
    if app._ctrl.get_session_status(sid) == SessionStatus.RUNNING:
        app.notify("Cannot compact while agent is running", severity="warning")
        return

    if app._chat_display is None:
        app.notify("Display not ready", severity="warning")
        return

    if not hasattr(app._runtime, "compact_session"):
        app.notify("Runtime does not support manual compaction", severity="error")
        return

    logger.info("tui.compact.manual.start session=%s", sid)
    buf = app._ctrl.get_buf(sid)
    d = app._chat_display

    # Drive the same event stream the auto-compaction produces.
    # The display layer already understands
    # CompactionStart/CompactionChunk/CompactionEnd and the
    # trailing MessageEvent(role="compaction") for replay.
    summary = ""
    error_msg: str | None = None
    try:
        from minimal_harness.types import CompactionEnd

        async for evt in app._runtime.compact_session(sid):
            d.handle_event(evt, buf=buf)
            if isinstance(evt, CompactionEnd):
                summary = evt.summary
                error_msg = evt.error
    except Exception as exc:
        logger.exception("tui.compact.manual.error session=%s", sid)
        app.notify(f"Compaction failed: {exc}", severity="error")
        return

    # Replay the persisted summary message in the same flow as the
    # agent's own CompactionAgent path. The display layer already
    # de-duplicates the live widget vs. the trailing MessageEvent,
    # so emitting it here is safe.
    if summary and error_msg is None:
        from minimal_harness.types import MessageEvent

        d.handle_event(
            MessageEvent(
                message={
                    "role": "compaction",
                    "content": summary,
                    "meta": {"source": "manual"},
                }
            ),
            buf=buf,
        )
    elif error_msg:
        app.notify(f"Compaction failed: {error_msg}", severity="error")
        return

    logger.info("tui.compact.manual.end session=%s chars=%d", sid, len(summary))
    if summary:
        app.notify("Compaction complete", severity="information")
