# mh-tui

**Terminal UI client for [minimal-harness](https://github.com/J0ey1iu/minimal-harness).**

A local-running, single-user counterpart to
[mh-orchestration-service](https://github.com/J0ey1iu/mh-orchestration-service)
(cloud-distributed, multi-tenant). Both consume the same `minimal-harness`
SDK and share the same Agent / Tool / Memory / Event abstractions.

## What This Is

`mh-tui` is the official Textual-based TUI front-end for the `minimal-harness`
agent SDK. It provides:

- **Streaming chat** with markdown rendering, reasoning display, and live tool
  call/result cards.
- **Multi-agent support** — switch between agents at runtime, handoff tasks
  to other agents, discover available agents.
- **Persistent sessions** — every conversation is auto-saved to local JSONL
  files; resume from the `/sessions` picker.
- **Tool picker** — toggle built-in tools (`bash`, `local_file_operation`)
  and external user-defined tools via `/tools`.
- **Mid-run interrupt** — press `Esc` to gracefully stop LLM streaming and
  tool execution.
- **Slash commands** — `/config`, `/tools`, `/new`, `/sessions`, `/share`,
  `/compact`, `/dump`, `/quit`, etc.
- **`@` file picker** — type `@` to fuzzy-match files in the current
  working directory and insert a path into the input.
- **Configurable themes** — 21 textual themes including `tokyo-night`,
  `catppuccin-*`, `rose-pine-*`, `solarized-*`, etc.

## Installation

```bash
pip install mh-tui
```

This pulls in `minimal-harness` as a dependency.

## Run

```bash
mhc                       # launch the TUI
mhc --help                # (planned) CLI flags
MH_CONFIG_DIR=/path/to/dir mhc   # override config directory
```

On first launch the TUI will create `~/.minimal_harness/` containing:

- `config.json` — base_url, api_key, model, default_agent, theme
- `agents.json` — registered preset agents
- `models.json` — model history (for the model picker)
- `system-prompts/*.md` — system prompt files
- `sessions/*.json` — conversation history
- `log/tui.log`, `log/error.log` — daily-rotated logs

> **Note:** The directory is intentionally named `~/.minimal_harness/` (not
> `~/.mh_tui/`) for backward compatibility with pre-0.7.0 installations.
> Your existing data carries over without migration.

## Keybindings

| Key | Action |
|---|---|
| `Enter` | Send message |
| `Ctrl+Enter` | Newline in input |
| `Esc` | Interrupt the running agent |
| `Ctrl+O` | Open config screen |
| `Ctrl+T` | Open tool picker |
| `Ctrl+Y` | Copy last assistant response |
| `Ctrl+D` | Dump runtime state (debug) |
| `Ctrl+C` | Quit (with confirmation) |
| `↑` / `↓` | Navigate input history |
| `/` | Open slash command menu |
| `@` | Open file/directory picker |

## Project Structure

```
src/mh_tui/
├── app.py               # TUIApp + main()
├── context.py           # AppContext (config + registry + session store)
├── session_controller.py
├── session_factory.py
├── session_replayer.py
├── runtime_session.py   # ConversationSession (TUI's per-run binding)
├── runtime_tools.py     # handoff + discover_agents (application glue)
├── logging_setup.py     # TUI-mode file logging
├── config/              # ~/.minimal_harness/ JSON files
├── actions/             # Slash-command action handlers
├── widgets/             # Textual widgets
└── app.tcss             # Textual CSS
```

## Architecture

`mh-tui` is a **Layer 3 application** that consumes the Layer 1/2 abstractions
exposed by `minimal-harness`. It never instantiates Layer 1 types directly
(`SimpleAgent`, `Tool`); instead it composes Layer 2 services
(`AgentRuntime`, `AgentRegistry`, `ToolRegistry`, session store).

```
Layer 3: mh-tui (this repo)
   TUIApp → SessionController → Display / Modals
   ↓ uses
Layer 2: minimal_harness.{agent,tool,llm,session}.runtime
   AgentRuntime · Registry<> · SessionStore
   ↓ uses
Layer 1: minimal_harness.types / protocols
   Agent · Tool · Memory · LLMProvider · Events
```

## Extending

`mh-tui` discovers tools from `ToolRegistry`. To register a custom tool
before launching the TUI:

```python
import asyncio
from mh_tui import TUIApp
from minimal_harness.tool.registry import ToolRegistry
from minimal_harness.types import LocalToolBinding, ToolMetadata

async def setup(registry: ToolRegistry) -> None:
    await registry.register(
        ToolMetadata(
            name="my_tool",
            display_name="My Tool",
            description="Does something useful",
            parameters={"type": "object", "properties": {}, "required": []},
            binding=LocalToolBinding(fn=my_tool_fn),
        )
    )

registry = ToolRegistry()
asyncio.run(setup(registry))
TUIApp(registry=registry).run()
```

See `examples/dev-with-mh/example_use_tui.py` for a complete runnable demo.

## Migration from minimal-harness ≤ 0.6.x

The TUI was previously shipped as `minimal_harness.client.built_in`. If you
have existing code that does:

```python
from minimal_harness.client.built_in import TUIApp
```

Change it to:

```python
from mh_tui import TUIApp
```

`mhc` remains the CLI command name — it now resolves to `mh_tui.app:main`.

## License

Same as minimal-harness.
