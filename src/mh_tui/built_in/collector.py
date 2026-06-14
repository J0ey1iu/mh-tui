from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from minimal_harness.tool.external_loader import load_external_tools

from mh_tui.built_in.registry import collect_builtin_tools

if TYPE_CHECKING:
    from minimal_harness.tool.registry import ToolRegistry


async def collect_tools(
    config: dict[str, Any],
    registry: "ToolRegistry",
) -> None:
    """Aggregate tools into the registry.

    Loads external tools from a directory (if ``tools_path`` is set in
    *config*), then registers the built-in tools. Warns if an external
    tool shadows a built-in.
    """
    if path := config.get("tools_path", "").strip():
        await load_external_tools(path, registry)
    existing = {t.name for t in await registry.get_all()}
    builtin_names = await collect_builtin_tools(registry)
    for name in existing & builtin_names:
        warnings.warn(
            f"External tool '{name}' overwrites built-in tool of the same name."
        )
