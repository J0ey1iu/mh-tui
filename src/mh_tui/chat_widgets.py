"""Chat message widgets that natively wrap to container width."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.widgets import Static


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds as ``H h M m S.SSs``.

    Mirrors the helper in ``display.py`` — kept here so the widget
    module has no display-coupling.
    """
    import math

    hours = math.floor(seconds / 3600)
    minutes = math.floor((seconds % 3600) / 60)
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {secs:.0f}s"
    if minutes > 0:
        return f"{minutes}m {secs:.0f}s"
    return f"{secs:.2f}s"


class ChatMsg(Static):
    """Base class for all chat messages. Handles text wrapping natively."""

    def __init__(
        self,
        content: Any = "",
        *,
        id: str | None = None,
    ) -> None:
        if isinstance(content, str):
            content = Text(content, no_wrap=False, overflow="fold")
        elif isinstance(content, Text):
            content.no_wrap = False
            content.overflow = "fold"
        super().__init__(content, id=id)

    def update(self, content: Any = "", *, layout: bool = True) -> None:
        if isinstance(content, str):
            content = Text(content, no_wrap=False, overflow="fold")
        elif isinstance(content, Text):
            content.no_wrap = False
            content.overflow = "fold"
        super().update(content, layout=layout)


class UserMsg(ChatMsg):
    """User input message."""


class ReasoningMsg(ChatMsg):
    """Thinking/reasoning content."""


class ToolCallMsg(ChatMsg):
    """Tool call display."""


class ToolResultMsg(ChatMsg):
    """Tool result display."""


class AssistantMsg(ChatMsg):
    """Assistant answer content (streaming or committed)."""


class CompactionMsg(ChatMsg):
    """Single widget representing one in-flight or completed compaction.

    Owns its own three-phase lifecycle:

    * ``pending`` — created but not yet started; renders blank.
    * ``live`` — ``start()`` was called; renders a status line that
      updates in place on every ``accumulate()`` (just the character
      count and elapsed time — the streaming chunk text is NOT shown
      here, to avoid the "every chunk prints the cumulative text"
      ugliness).
    * ``done`` — ``finish()`` was called; renders the final summary
      once (heading + body, plain text).
    * ``failed`` — ``fail()`` was called; renders the error in red.

    The widget's ``summary_text`` property exposes the final summary
    content (or ``""`` if not yet done / failed) so the display layer
    can persist it via the export/session-replay path.
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("", id=id)
        self._phase: str = "pending"
        self._dropped: int = 0
        self._keep_recent: int = 0
        self._prompt_tokens: int = 0
        self._accumulated_chars: int = 0
        self._started_at: float = 0.0
        self._duration: float = 0.0
        self._summary: str = ""
        self._error: str | None = None
        self._existing_summary_chars: int = 0

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def summary_text(self) -> str:
        """Final summary content, or ``""`` if not yet finished."""
        return self._summary if self._phase == "done" else ""

    @property
    def dropped_count(self) -> int:
        return self._dropped

    def start(
        self,
        dropped: int,
        keep_recent: int,
        prompt_tokens: int,
        existing_summary_chars: int = 0,
    ) -> None:
        """Begin a compaction. Renders the live status line."""
        self._phase = "live"
        self._dropped = dropped
        self._keep_recent = keep_recent
        self._prompt_tokens = prompt_tokens
        self._existing_summary_chars = existing_summary_chars
        self._accumulated_chars = 0
        self._started_at = time.monotonic()
        self._summary = ""
        self._error = None
        self._refresh()

    def accumulate(self, delta: str) -> None:
        """Record a streaming chunk from the summarizer. The widget
        only updates the character count, not the actual text — the
        full text is rendered exactly once, in ``finish()``.
        """
        if self._phase != "live":
            return
        self._accumulated_chars += len(delta)
        self._refresh()

    def finish(
        self,
        summary: str,
        duration: float,
        dropped: int,
    ) -> None:
        """Mark compaction as successful. Renders the final summary
        block (heading + body) once.
        """
        self._phase = "done"
        self._summary = summary
        self._duration = duration
        self._dropped = dropped
        self._accumulated_chars = len(summary)
        self._refresh()

    def fail(self, error: str, duration: float) -> None:
        """Mark compaction as failed. Renders an error block."""
        self._phase = "failed"
        self._error = error
        self._duration = duration
        self._refresh()

    def _refresh(self) -> None:
        text = self._build_text()
        if text is None:
            return
        if not self.is_mounted:
            return
        self.update(text)

    def _build_text(self) -> Text | None:
        if self._phase == "pending":
            return Text("")

        if self._phase == "live":
            elapsed = time.monotonic() - self._started_at
            text = Text()
            text.append("\U0001f5dc Compressing ", style="bold bright_cyan")
            text.append(f"{self._dropped}", style="bright_cyan")
            text.append(" messages → keep last ", style="bold bright_cyan")
            text.append(f"{self._keep_recent}", style="bright_cyan")
            text.append(f"  ({self._prompt_tokens} prompt tokens)\n", style="dim")
            text.append("  ▌ ", style="bright_cyan")
            text.append(f"{self._accumulated_chars} chars", style="dim cyan")
            if self._existing_summary_chars:
                text.append(
                    f"  (prior {self._existing_summary_chars} chars)",
                    style="dim",
                )
            text.append(f"  ⏱ {_format_duration(elapsed)}", style="dim")
            return text

        if self._phase == "done":
            text = Text()
            text.append("\U0001f4dc Folded summary", style="bold bright_cyan")
            text.append(
                f"  {self._dropped} msgs → {len(self._summary)} chars",
                style="dim",
            )
            text.append(
                f"  ⏱ {_format_duration(self._duration)}\n",
                style="dim",
            )
            # Indent the body so it visually nests under the heading.
            for line in self._summary.splitlines() or [""]:
                text.append("    ", style="dim")
                text.append(line, style="not italic")
                text.append("\n", style="")
            return text

        if self._phase == "failed":
            text = Text()
            text.append("\u26a0 Compaction failed", style="bold #f38ba8")
            text.append(f"  ⏱ {_format_duration(self._duration)}\n", style="dim")
            if self._error:
                text.append("    ", style="dim")
                text.append(self._error, style="#f38ba8")
            return text

        return None

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh)
