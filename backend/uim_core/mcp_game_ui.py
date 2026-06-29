from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .game_ui import (
    bake_game_ui_html,
    export_game_ui_umg,
    game_ui_dsl_prompt,
    generate_texture_kit,
    list_game_ui_structures,
    list_texture_kits,
    register_texture_kit,
    write_game_ui_html,
)
from .project import load_current_project_root, load_project, load_project_workspace, save_mcp_ui_state, save_project

DSL_PROMPT_GRANT_KEY = "gameUiDslPromptGrant"
CURRENT_PROJECT_ENV = "UIM_CURRENT_PROJECT"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _save_context(project_root: Path, tool: str, message: str, *, screen_name: str = "") -> dict[str, Any]:
    return save_mcp_ui_state(
        project_root,
        {
            "mainTab": "game_ui",
            "assetName": screen_name,
            "lastTool": tool,
            "lastMessage": message,
            "updatedAt": _now(),
        },
    )


def _ok(project_root: Path, tool: str, message: str, payload: dict[str, Any], *, screen_name: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        **payload,
        "mcpUiState": _save_context(project_root, tool, message, screen_name=screen_name),
        "nextSuggestedStage": "game_ui",
    }


def _error(project_root: Path, tool: str, message: str, *, screen_name: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "mcpUiState": _save_context(project_root, tool, message, screen_name=screen_name),
    }


def _plain_error(tool: str, message: str, *, screen_name: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "mcpUiState": {
            "mainTab": "game_ui",
            "assetName": screen_name,
            "lastTool": tool,
            "lastMessage": message,
            "updatedAt": _now(),
        },
    }


def _call(project_root: str, tool: str, screen_name: str, callback) -> dict[str, Any]:
    root = Path(project_root).resolve()
    try:
        return callback(root)
    except Exception as exc:
        return _error(root, tool, str(exc), screen_name=screen_name)


def _current_project_root(project_root: str | None = None) -> Path:
    value = str(project_root or "").strip() or os.environ.get(CURRENT_PROJECT_ENV, "").strip()
    if not value:
        current = load_current_project_root()
        if current is not None:
            return current
    if not value:
        raise ValueError(
            "No current UnrealImageMaker project is configured. Open or refresh a project in the UnrealImageMaker app, then retry the current Game UI MCP tool."
        )
    root = Path(value).resolve()
    load_project(root)
    return root


def game_ui_get_workspace(project_root: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    return {"ok": True, "workspace": load_project_workspace(root), "structures": list_game_ui_structures(root), "textureKits": list_texture_kits(root)}


def game_ui_get_current_workspace() -> dict[str, Any]:
    try:
        root = _current_project_root()
        payload = game_ui_get_workspace(str(root))
        payload["projectRoot"] = str(root)
        payload["writeWorkflow"] = game_ui_html_write_workflow(str(root))
        return payload
    except Exception as exc:
        return _plain_error("game_ui_get_current_workspace", str(exc))


def _dsl_prompt_version(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    return f"game-ui-dsl-anchor-v2-{digest}"


def _issue_dsl_prompt_grant(root: Path, width: int, height: int, prompt: str) -> dict[str, str | int]:
    token = uuid4().hex
    version = _dsl_prompt_version(prompt)
    project = load_project(root)
    project.settings[DSL_PROMPT_GRANT_KEY] = {
        "token": token,
        "version": version,
        "width": width,
        "height": height,
        "issuedAt": _now(),
        "used": False,
    }
    save_project(root, project)
    return {"dslPromptToken": token, "dslPromptVersion": version, "dslPromptHash": version.rsplit("-", 1)[-1]}


def _require_dsl_prompt_grant(root: Path, token: str | None) -> dict[str, Any]:
    if not token:
        raise ValueError("game_ui_write_html requires dsl_prompt_token from game_ui_get_dsl_prompt. Call game_ui_get_dsl_prompt first, then pass its dslPromptToken.")
    project = load_project(root)
    grant = project.settings.get(DSL_PROMPT_GRANT_KEY)
    if not isinstance(grant, dict) or grant.get("used"):
        raise ValueError("No active Game UI DSL prompt grant. Call game_ui_get_dsl_prompt before game_ui_write_html.")
    if str(grant.get("token") or "") != token:
        raise ValueError("Invalid Game UI DSL prompt token. Call game_ui_get_dsl_prompt again and pass the returned dslPromptToken.")
    return dict(grant)


def _consume_dsl_prompt_grant(root: Path, token: str) -> dict[str, Any]:
    project = load_project(root)
    grant = project.settings.get(DSL_PROMPT_GRANT_KEY)
    if not isinstance(grant, dict) or str(grant.get("token") or "") != token:
        raise ValueError("Game UI DSL prompt token disappeared before it could be consumed.")
    grant["used"] = True
    grant["usedAt"] = _now()
    project.settings[DSL_PROMPT_GRANT_KEY] = grant
    save_project(root, project)
    return grant


def game_ui_html_write_workflow(project_root: str, width: int = 1920, height: int = 1080) -> dict[str, Any]:
    resolved_root = str(Path(project_root).resolve()) if project_root else ""
    return {
        "purpose": "Create HTML and write it into the currently opened UnrealImageMaker .uim workspace.",
        "projectRoot": resolved_root,
        "htmlDestination": "ui/html/{safeScreenName}.html inside projectRoot",
        "htmlOnlyCurrentToolOrder": [
            {
                "tool": "game_ui_get_current_dsl_prompt",
                "arguments": {"width": width, "height": height},
                "reason": "Get the HTML DSL and a one-time dslPromptToken for the app's current project. Do not create, find, or switch projects.",
            },
            {
                "tool": "game_ui_write_current_html",
                "arguments": {
                    "screen_name": "<ask the user for the HTML prototype/screen name if not specified>",
                    "html": "<complete single-file HTML>",
                    "dsl_prompt_token": "<dslPromptToken from game_ui_get_current_dsl_prompt>",
                },
                "reason": "Write HTML into the current workspace through MCP without local file editing.",
            },
        ],
        "explicitProjectToolOrder": [
            {
                "tool": "game_ui_get_dsl_prompt",
                "arguments": {"project_root": resolved_root or "<current .uim project root>", "width": width, "height": height},
                "reason": "Use only when project_root was explicitly provided; get the DSL plus a one-time dslPromptToken.",
            },
            {
                "tool": "game_ui_write_html",
                "arguments": {
                    "project_root": resolved_root or "<current .uim project root>",
                    "screen_name": "<ask the user for the HTML prototype/screen name if not specified>",
                    "html": "<complete single-file HTML>",
                    "dsl_prompt_token": "<dslPromptToken from game_ui_get_dsl_prompt>",
                },
                "reason": "This is the only supported way for an MCP agent to write the HTML into the open workspace.",
            },
        ],
        "mustNot": [
            "Do not only answer with an HTML code block.",
            "Do not write the HTML with shell commands or direct filesystem editing.",
            "Do not create, search for, or switch workspaces for an HTML-only request; the app/MCP server owns the current project context.",
            "Do not call game_ui_write_html without the latest dslPromptToken.",
            "Do not invent the HTML prototype/screen name when the user has not specified it; ask for it.",
            "Do not reuse a dslPromptToken after a write attempt.",
        ],
        "completionCriteria": "game_ui_write_html returns ok=true and a project-relative path under ui/html/.",
    }


def _write_html_after_prompt_grant(root: Path, screen_name: str, html: str, token: str | None) -> dict[str, Any]:
    _require_dsl_prompt_grant(root, token)
    result = write_game_ui_html(root, screen_name, html)
    grant = _consume_dsl_prompt_grant(root, str(token))
    return {**result, "dslPromptGrant": grant}


def game_ui_get_dsl_prompt(project_root: str, width: int = 1920, height: int = 1080) -> dict[str, Any]:
    root = Path(project_root).resolve()
    prompt = game_ui_dsl_prompt(width, height, str(root))
    grant = _issue_dsl_prompt_grant(root, width, height, prompt)
    return _ok(
        root,
        "game_ui_get_dsl_prompt",
        "Game UI DSL prompt generated by MCP. The returned dslPromptToken is one-time-use; pass it as dsl_prompt_token to exactly one game_ui_write_html call.",
        {"prompt": prompt, "width": width, "height": height, "writeWorkflow": game_ui_html_write_workflow(str(root), width, height), **grant},
    )


def game_ui_get_current_dsl_prompt(width: int = 1920, height: int = 1080) -> dict[str, Any]:
    try:
        root = _current_project_root()
        return game_ui_get_dsl_prompt(str(root), width, height)
    except Exception as exc:
        return _plain_error("game_ui_get_current_dsl_prompt", str(exc))


def game_ui_write_html(project_root: str, screen_name: str, html: str, dsl_prompt_token: str | None = None) -> dict[str, Any]:
    return _call(
        project_root,
        "game_ui_write_html",
        screen_name,
        lambda root: _ok(
            root,
            "game_ui_write_html",
            "Game UI HTML written by MCP after DSL prompt grant validation.",
            _write_html_after_prompt_grant(root, screen_name, html, dsl_prompt_token),
            screen_name=screen_name,
        ),
    )


def game_ui_write_current_html(screen_name: str, html: str, dsl_prompt_token: str | None = None) -> dict[str, Any]:
    try:
        root = _current_project_root()
        return game_ui_write_html(str(root), screen_name, html, dsl_prompt_token)
    except Exception as exc:
        return _plain_error("game_ui_write_current_html", str(exc), screen_name=screen_name)


def game_ui_bake_html(project_root: str, screen_name: str, html_path: str | None = None) -> dict[str, Any]:
    return _call(
        project_root,
        "game_ui_bake_html",
        screen_name,
        lambda root: _ok(root, "game_ui_bake_html", "Game UI HTML baked by MCP.", bake_game_ui_html(root, screen_name, html_path), screen_name=screen_name),
    )


def game_ui_list_structures(project_root: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    return _ok(root, "game_ui_list_structures", "Game UI structures listed by MCP.", list_game_ui_structures(root))


def game_ui_list_texture_kits(project_root: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    return _ok(root, "game_ui_list_texture_kits", "Game UI texture kits listed by MCP.", list_texture_kits(root))


def game_ui_export_umg(project_root: str, screen_name: str, structure_path: str, texture_kit_path: str, content_path: str = "/Game/UIM/UI") -> dict[str, Any]:
    return _call(
        project_root,
        "game_ui_export_umg",
        screen_name,
        lambda root: _ok(
            root,
            "game_ui_export_umg",
            "Game UI UMG import script exported by MCP.",
            export_game_ui_umg(root, screen_name, structure_path, texture_kit_path, content_path),
            screen_name=screen_name,
        ),
    )


def game_ui_generate_texture_kit(
    project_root: str,
    kit_name: str,
    concept_path: str | None = None,
    widget_tokens: list[dict[str, Any]] | None = None,
    provider: str = "openai_api",
    coverage: str = "default_full",
    mask_mode: str = "hybrid",
    decontaminate_edges: bool = True,
    debug_artifacts: bool = False,
    max_concurrency: int = 4,
) -> dict[str, Any]:
    tokens = widget_tokens or []
    return _call(
        project_root,
        "game_ui_generate_texture_kit",
        kit_name,
        lambda root: _ok(
            root,
            "game_ui_generate_texture_kit",
            "Game UI texture kit generated by MCP.",
            generate_texture_kit(root, kit_name, concept_path, tokens, provider, coverage=coverage, mask_mode=mask_mode, decontaminate_edges=decontaminate_edges, debug_artifacts=debug_artifacts, max_concurrency=max_concurrency),
            screen_name=kit_name,
        ),
    )


def game_ui_register_texture_kit(project_root: str, kit_name: str, files: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    return _call(
        project_root,
        "game_ui_register_texture_kit",
        kit_name,
        lambda root: _ok(
            root,
            "game_ui_register_texture_kit",
            "Game UI texture kit registered by MCP.",
            register_texture_kit(root, kit_name, files),
            screen_name=kit_name,
        ),
    )
