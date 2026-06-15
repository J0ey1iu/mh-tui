# Change log

## 0.2.0 (unreleased)

- refactor(compact): merge `/compact` slash command with the
  `CompactionAgent` auto-compaction path. The legacy "submit a
  prompt that asks the LLM to summarise, then truncate by setting
  `_forward_offset`" hack is gone. `/compact` now drives
  `AgentRuntime.compact_session(memory_id)` and surfaces the same
  `CompactionStart / CompactionChunk / CompactionEnd` event stream
  the auto-compaction produces — same `CompactionMsg` widget, same
  Widget states, same persistence. The fold is now done by
  `Memory.compact()` (atomic with the buffer) rather than the LLM
  generating a freeform summary, so there is no more "summary-as-
  assistant-message" ambiguity in the chat log.
- refactor(compact): drop the now-unused `app._pending_compact` /
  `app._finalize_compact` plumbing. Compaction finalisation is
  driven by the runtime's event stream directly.
- refactor(compact): `AgentMetadata.compaction` is now a typed
  `CompactionSettings` TypedDict (the SDK rejected the untyped
  `dict[str, Any]` after the 0.7.0 refactor). The TUI factory uses
  `compaction_settings_or_defaults()` for fallback handling.

## 0.1.0

- **Initial release** — TUI extracted from `minimal-harness` 0.6.x.
- Carries over all features that previously lived in
  `minimal_harness.client.built_in`:
  - `TUIApp`, `AppContext`, `StreamBuffer`, `ChatDisplay`
  - Slash command handlers (`/config`, `/tools`, `/new`, `/sessions`,
    `/share`, `/compact`, `/dump`, `/team`, `/quit`)
  - `@`-file picker
  - 21 textual themes, daily-rotating logs
  - `handoff` and `discover_agents` runtime tools
  - `JsonlSessionStore` (per-session JSON files under
    `~/.minimal_harness/sessions/`)
  - `register_runtime_tools()` helper for `AgentRuntime` consumers
- **CLI**: `mhc` command is preserved (now maps to `mh_tui.app:main`).
- **Config dir**: `~/.minimal_harness/` is preserved verbatim (no
  migration needed from pre-0.7.0 installations).
- **Package rename**: `from minimal_harness.client.built_in import TUIApp`
  becomes `from mh_tui import TUIApp`. Hard break — no compat shim.
