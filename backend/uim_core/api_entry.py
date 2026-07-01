from __future__ import annotations

import os
import sys
from pathlib import Path


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _prepare_environment() -> None:
    root = _runtime_root()
    os.environ.setdefault("UIM_RUNTIME_ROOT", str(root))
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
