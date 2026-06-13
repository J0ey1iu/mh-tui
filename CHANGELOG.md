# Change log

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
