# Agent coding guide

## Must do

1. When you need to start the project in any way, use python interpreter in
   `./.venv/bin/python` (created by `uv sync`).
2. After editing code, run:
   ```bash
   uv run ruff check --fix <path>
   uv run ruff check --select I --fix <path>
   uv run ruff format <path>
   uv run pyright <path>
   ```
   Fix all errors and warnings.
3. Run `uv run pytest tests -v` to verify the test suite.

## Package layout

- `src/mh_tui/` — the TUI application package
  - `app.py` — `TUIApp` and the `main()` entry point
  - `runtime_session.py` — `ConversationSession`, `SessionStatus`
  - `runtime_tools.py` — `register_runtime_tools()`,
    `make_handoff_tool()`, `make_discover_agents_tool()`
  - `logging_setup.py` — TUI-mode `setup_logging()`
  - `config/` — JSON config + system prompts + tools discovery
  - `actions/` — slash-command action handlers
- `tests/` — pytest suite (moved verbatim from
  `minimal-harness/test/tui/`)
- `examples/dev-with-mh/` — runnable examples

## Imports

The TUI is a **Layer 3 application** on top of `minimal-harness`. Import the
SDK like any other library:

```python
from minimal_harness.agent.runtime import AgentRuntime
from minimal_harness.types import AgentMetadata
from minimal_harness.tool.registry import ToolRegistry
```

Import the TUI's own modules either with absolute paths or as siblings
within `mh_tui/`:

```python
from mh_tui import TUIApp
from mh_tui.runtime_session import ConversationSession
from mh_tui.config import DEFAULT_CONFIG
```

Prefer absolute imports for cross-module references (matches the style of
the original `minimal_harness.client.built_in` code).

## Must NOT do

1. Don't ever commit anything without a user asking you to.
2. Don't add `textual`-specific abstractions to the SDK package — keep the
   boundary clean. The SDK is in the sibling `minimal-harness` repo.
