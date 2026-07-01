from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import MODELS_LOCK_FILE, PROJECT_FILE
from .json_io import read_json, write_json
from .paths import user_data_dir, workspace_root
from .styles import write_builtin_styles


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class UimProject:
    id: str
    name: str
    schema: str = "uim.project.v1"
    version: str = "0.1.0"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    default_style: str = "pixel_art"
    target_engines: list[str] = field(default_factory=lambda: ["unreal"])
    model_cache: str = "software-shared"
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_path(root: Path) -> Path:
    return root / PROJECT_FILE


CURRENT_PROJECT_POINTER_FILE = "current-project.json"
WORKSPACE_CURRENT_PROJECT_POINTER_FILE = ".uim-current-project.json"


def current_project_pointer_path() -> Path:
    """Primary current-project pointer shared by the app API and MCP server."""
    return user_data_dir() / CURRENT_PROJECT_POINTER_FILE


def _current_project_pointer_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = str(os.environ.get("UIM_CURRENT_PROJECT_POINTER") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(current_project_pointer_path())
    candidates.append(workspace_root() / WORKSPACE_CURRENT_PROJECT_POINTER_FILE)
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except Exception:
            key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def save_current_project_root(root: Path | str) -> dict[str, Any]:
    resolved = Path(root).resolve()
    load_project(resolved)
    payload = {"projectRoot": str(resolved), "updatedAt": _now()}
    errors: list[Exception] = []
    wrote = False
    for pointer in _current_project_pointer_candidates():
        try:
            write_json(pointer, payload)
            wrote = True
        except Exception as exc:
            errors.append(exc)
    if not wrote and errors:
        raise errors[-1]
    return payload


def load_current_project_root() -> Path | None:
    newest: tuple[str, Path] | None = None
    for path in _current_project_pointer_candidates():
        if not path.exists():
            continue
        try:
            data = read_json(path)
            root_value = str(data.get("projectRoot") or "").strip()
            if not root_value:
                continue
            root = Path(root_value).resolve()
            load_project(root)
            updated_at = str(data.get("updatedAt") or "")
        except Exception:
            continue
        if newest is None or updated_at > newest[0]:
            newest = (updated_at, root)
    return newest[1] if newest else None


def models_lock_path(root: Path) -> Path:
    return root / MODELS_LOCK_FILE


def create_project(root: Path, name: str, overwrite: bool = False) -> UimProject:
    root = root.resolve()
    if project_path(root).exists() and not overwrite:
        raise FileExistsError(f"Project already exists: {project_path(root)}")

    for folder in [
        root / "profiles",
        root / "assets",
        root / "exports" / "unreal",
        root / "cache",
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    project = UimProject(id=str(uuid4()), name=name)
    write_json(project_path(root), project.to_dict())
    write_builtin_styles(root / "profiles")
    if not models_lock_path(root).exists() or overwrite:
        write_json(models_lock_path(root), {"schema": "uim.models_lock.v1", "models": []})
    return project


def load_project(root: Path) -> UimProject:
    data = read_json(project_path(root))
    return UimProject(
        id=str(data["id"]),
        name=str(data["name"]),
        schema=str(data.get("schema", "uim.project.v1")),
        version=str(data.get("version", "0.1.0")),
        created_at=str(data.get("created_at", _now())),
        updated_at=str(data.get("updated_at", _now())),
        default_style=str(data.get("default_style", "pixel_art")),
        target_engines=list(data.get("target_engines", ["unreal"])),
        model_cache=str(data.get("model_cache", "software-shared")),
        settings=dict(data.get("settings", {})),
    )


def save_project(root: Path, project: UimProject) -> None:
    project.updated_at = _now()
    write_json(project_path(root), project.to_dict())


def load_project_workspace(root: Path) -> dict[str, Any]:
    project = load_project(root)
    queue = project.settings.get("processingQueue")
    if not isinstance(queue, list):
        queue = []
    slots = project.settings.get("workflowSlots")
    if not isinstance(slots, dict):
        slots = {}
    mcp_ui_state = project.settings.get("mcpUiState")
    if not isinstance(mcp_ui_state, dict):
        mcp_ui_state = {}
    game_ui_settings = project.settings.get("gameUiSettings")
    if not isinstance(game_ui_settings, dict):
        game_ui_settings = {}
    return {
        "processingQueue": queue,
        "workflowSlots": slots,
        "mcpUiState": mcp_ui_state,
        "gameUiSettings": game_ui_settings,
    }


def save_processing_queue(root: Path, queue: list[dict[str, Any]]) -> dict[str, Any]:
    project = load_project(root)
    project.settings["processingQueue"] = queue
    save_project(root, project)
    return load_project_workspace(root)


def save_workflow_slots(root: Path, slots: dict[str, Any]) -> dict[str, Any]:
    project = load_project(root)
    project.settings["workflowSlots"] = slots
    save_project(root, project)
    return load_project_workspace(root)


def save_game_ui_settings(root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    project = load_project(root)
    current = project.settings.get("gameUiSettings")
    if not isinstance(current, dict):
        current = {}
    project.settings["gameUiSettings"] = {**current, **settings}
    save_project(root, project)
    return load_project_workspace(root)


def save_mcp_ui_state(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    project = load_project(root)
    current = project.settings.get("mcpUiState")
    current_revision = int(current.get("revision") or 0) if isinstance(current, dict) else 0
    project.settings["mcpUiState"] = {**state, "revision": current_revision + 1}
    save_project(root, project)
    return load_project_workspace(root)["mcpUiState"]
