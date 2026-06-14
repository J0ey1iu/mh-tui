from __future__ import annotations

from typing import TYPE_CHECKING

from minimal_harness.tool.base import Tool
from minimal_harness.types import LocalToolBinding, ToolMetadata

import mh_tui.built_in.bash
import mh_tui.built_in.local_file_operation

if TYPE_CHECKING:
    from minimal_harness.tool.registry import ToolRegistryProtocol


def _getter_modules() -> tuple:
    """Return the modules whose ``get_tools`` to iterate.

    Looking up the modules lazily (not capturing the bound functions at
    import time) so that ``mock.patch("mh_tui.built_in.bash.get_tools")``
    is honoured by tests.
    """
    return (mh_tui.built_in.bash, mh_tui.built_in.local_file_operation)


def get_tools() -> dict[str, Tool]:
    """Return all built-in tool instances keyed by name."""
    tools: dict[str, Tool] = {}
    for mod in _getter_modules():
        tools.update(mod.get_tools())
    return tools


def get_builtin_tool_names() -> set[str]:
    """Return the set of built-in tool names (without registering them)."""
    names: set[str] = set()
    for mod in _getter_modules():
        names.update(mod.get_tools().keys())
    return names


async def collect_builtin_tools(registry: "ToolRegistryProtocol") -> set[str]:
    """Register all built-in tools into the given registry.

    Returns the set of built-in tool names that were registered.
    """
    names: set[str] = set()
    for mod in _getter_modules():
        for name, tool in mod.get_tools().items():
            await registry.register(
                ToolMetadata(
                    name=tool.name,
                    display_name=tool.display_name,
                    description=tool.description,
                    parameters=tool.parameters,
                    display_name_locale=tool.display_name_locale,
                    description_locale=tool.description_locale,
                    binding=LocalToolBinding(fn=getattr(tool, "fn", None)),
                    metadata_id=tool.name,
                )
            )
            names.add(name)
    return names
