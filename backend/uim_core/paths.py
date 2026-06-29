from __future__ import annotations

import os
from pathlib import Path

from .constants import APP_NAME


def workspace_root() -> Path:
    configured = os.environ.get("UIM_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd().resolve()


def model_cache_dir(root: Path | None = None) -> Path:
    base = root or workspace_root()
    return base / "model-cache"


def projects_dir(root: Path | None = None) -> Path:
    base = root or workspace_root()
    return base / "projects"


def user_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"
