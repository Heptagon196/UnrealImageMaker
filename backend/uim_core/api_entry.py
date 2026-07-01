from __future__ import annotations

import os
import sys
from pathlib import Path


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _default_workspace_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "UnrealImageMaker"
    return Path.home() / ".unrealimagemaker"


def _prepare_environment() -> None:
    root = _runtime_root()
    os.environ.setdefault("UIM_RUNTIME_ROOT", str(root))
    if getattr(sys, "frozen", False):
        workspace = _default_workspace_root()
        workspace.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("UIM_WORKSPACE", str(workspace))
    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
    os.environ.setdefault("no_proxy", "127.0.0.1,localhost")


def main() -> None:
    _prepare_environment()
    args = set(sys.argv[1:])
    if "--mcp" in args:
        from uim_core.mcp_server import main as mcp_main

        mcp_main()
        return

    from uim_core.api import main as api_main

    api_main()


if __name__ == "__main__":
    main()
