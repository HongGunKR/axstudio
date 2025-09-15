from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from langchain_core._api.deprecation import LangChainDeprecationWarning

from langflow.components._importing import import_mod

if TYPE_CHECKING:
    from .tool_invoker import ToolInvokerFromSelectionMin
    from .tool_picker_router import ToolPickerJsonRouterMessageOnlyV2
    from .tool_picker import ToolPickerDropdownSafeMessage

_dynamic_imports = {
    "ToolInvokerFromSelectionMin": "tool_invoker",
    "ToolPickerJsonRouterMessageOnlyV2": "tool_picker_router",
    "ToolPickerDropdownSafeMessage": "tool_picker",
}

__all__ = [
    "ToolInvokerFromSelectionMin",
    "ToolPickerJsonRouterMessageOnlyV2",
    "ToolPickerDropdownSafeMessage",
]


def __getattr__(attr_name: str) -> Any:
    """Lazily import tool components on attribute access."""
    if attr_name not in _dynamic_imports:
        msg = f"module '{__name__}' has no attribute '{attr_name}'"
        raise AttributeError(msg)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LangChainDeprecationWarning)
            result = import_mod(attr_name, _dynamic_imports[attr_name], __spec__.parent)
    except (ModuleNotFoundError, ImportError, AttributeError) as e:
        msg = f"Could not import '{attr_name}' from '{__name__}': {e}"
        raise AttributeError(msg) from e
    globals()[attr_name] = result
    return result


def __dir__() -> list[str]:
    return list(__all__)
