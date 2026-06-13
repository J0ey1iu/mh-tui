"""Terminal UI client built on top of the minimal-harness SDK.

This module re-exports the main components for convenient ``import mh_tui``
style access.
"""

from mh_tui.app import TUIApp, main
from mh_tui.buffer import StreamBuffer
from mh_tui.config import (
    DEFAULT_CONFIG,
    collect_tools,
    get_config_dir,
    load_agents_config,
    load_config,
    resolve_config_dir,
    save_config,
)
from mh_tui.constants import (
    FLUSH_INTERVAL,
    J0EY1IU_QUOTES,
    MAX_DISPLAY_LENGTH,
    THEMES,
)
from mh_tui.context import AppContext
from mh_tui.display import ChatDisplay
from mh_tui.error_handler import CapturedError, ErrorHandler
from mh_tui.export_presenter import ExportPresenter
from mh_tui.export_tracker import ExportEntry, ExportTracker
from mh_tui.modals import (
    ConfigScreen,
    ConfirmScreen,
    ErrorScreen,
    PromptScreen,
    SessionSelectScreen,
    ToolSelectScreen,
)
from mh_tui.streaming_controller import StreamingController
from mh_tui.widgets import ChatInput

__all__ = [
    "AppContext",
    "TUIApp",
    "main",
    "StreamBuffer",
    "DEFAULT_CONFIG",
    "FLUSH_INTERVAL",
    "J0EY1IU_QUOTES",
    "MAX_DISPLAY_LENGTH",
    "THEMES",
    "collect_tools",
    "get_config_dir",
    "load_agents_config",
    "load_config",
    "resolve_config_dir",
    "save_config",
    "ConfigScreen",
    "ConfirmScreen",
    "PromptScreen",
    "SessionSelectScreen",
    "ToolSelectScreen",
    "ErrorScreen",
    "ChatInput",
    "ChatDisplay",
    "ErrorHandler",
    "CapturedError",
    "ExportPresenter",
    "ExportEntry",
    "ExportTracker",
    "StreamingController",
]
