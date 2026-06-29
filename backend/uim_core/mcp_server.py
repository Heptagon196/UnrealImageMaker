from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import mcp_game_ui, mcp_pixel
from .api import api_list_project_assets
from .game_ui import game_ui_dsl_prompt
from .project import load_project_workspace


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on optional runtime package
        raise RuntimeError("The official MCP Python SDK is required. Install backend requirements, then run python -m uim_core.mcp_server.") from exc

    mcp = FastMCP("UnrealImageMaker")

    @mcp.resource("uim://pixel/presets")
    def pixel_presets() -> str:
        return _json(mcp_pixel.pixel_presets())

    @mcp.resource("uim://project/{project_root}/assets")
    def project_assets(project_root: str) -> str:
        return _json(api_list_project_assets(project_root))

    @mcp.resource("uim://project/{project_root}/workspace")
    def project_workspace(project_root: str) -> str:
        return _json(load_project_workspace(Path(project_root).resolve()))

    @mcp.resource("uim://game-ui/dsl")
    def game_ui_dsl() -> str:
        return _json({"prompt": game_ui_dsl_prompt()})

    @mcp.tool()
    def pixel_get_workspace(project_root: str) -> dict[str, Any]:
        return mcp_pixel.pixel_get_workspace(project_root)

    @mcp.tool()
    def pixel_set_context(project_root: str, asset_name: str, pixel_kind: str, stage: str = "concept", action: str = "idle", direction: str = "south", sheet_mode: str = "direct") -> dict[str, Any]:
        return mcp_pixel.pixel_set_context(project_root, asset_name, pixel_kind, stage, action, direction, sheet_mode)

    @mcp.tool()
    def pixel_generate_concept(project_root: str, asset_name: str, subject: str, asset_kind: str, output_size: str = "1024x1024", image_provider: str = "openai_api") -> dict[str, Any]:
        return mcp_pixel.pixel_generate_concept(project_root, asset_name, subject, asset_kind, output_size, image_provider)

    @mcp.tool()
    def pixel_generate_anchor(project_root: str, asset_name: str, subject: str, asset_kind: str, direction: str = "south", anchor_stage: str = "south", reference_anchor_path: str | None = None, dynamic_effect: str = "active effects, glow, particles, projectiles, and charged action pose", logical_frame_size: str = "256x256", output_size: str = "1024x1024", image_provider: str = "openai_api", mirror_from: str | None = None) -> dict[str, Any]:
        return mcp_pixel.pixel_generate_anchor(project_root, asset_name, subject, asset_kind, direction, anchor_stage, reference_anchor_path, dynamic_effect, logical_frame_size, output_size, image_provider, mirror_from)

    @mcp.tool()
    def pixel_generate_sheet(project_root: str, asset_name: str, subject: str, asset_kind: str, action: str, direction: str = "south", columns: int = 5, rows: int = 2, cell_size: int = 256, reference_path: str | None = None, action_description: str = "", attack_name: str = "magic projectile attack", effect_color: str = "violet", projectile_or_effect: str = "projectile or impact effect", image_provider: str = "openai_api", mirror_from: str | None = None) -> dict[str, Any]:
        return mcp_pixel.pixel_generate_sheet(project_root, asset_name, subject, asset_kind, action, direction, columns, rows, cell_size, reference_path, action_description, attack_name, effect_color, projectile_or_effect, image_provider, mirror_from)

    @mcp.tool()
    def pixel_generate_seedance_video(project_root: str, asset_name: str, anchor_path: str, action: str, direction: str, prompt: str, model: str | None = None, resolution: str | None = None, seconds: int = 5, asset_kind: str = "character") -> dict[str, Any]:
        return mcp_pixel.pixel_generate_seedance_video(project_root, asset_name, anchor_path, action, direction, prompt, model, resolution, seconds, asset_kind)

    @mcp.tool()
    def pixel_video_select_frames(project_root: str, video_path: str, mode: str, range_start: float = 0.0, range_end: float | None = None, fps: float = 8.0, frame_times: list[float] | None = None, thumbnail_size: int = 144) -> dict[str, Any]:
        return mcp_pixel.pixel_video_select_frames(project_root, video_path, mode, range_start, range_end, fps, frame_times, thumbnail_size)

    @mcp.tool()
    def pixel_video_find_loop(project_root: str, video_path: str, frame_times: list[float], min_score: float = 0.9) -> dict[str, Any]:
        return mcp_pixel.pixel_video_find_loop(project_root, video_path, frame_times, min_score)

    @mcp.tool()
    def pixel_video_debug_export(project_root: str, asset_name: str, video_path: str, action: str, direction: str, frame_times: list[float], export_type: str, columns: int = 5, cell_size: int = 256) -> dict[str, Any]:
        return mcp_pixel.pixel_video_debug_export(project_root, asset_name, video_path, action, direction, frame_times, export_type, columns, cell_size)

    @mcp.tool()
    def pixel_video_to_sheet(project_root: str, asset_name: str, video_path: str, action: str, direction: str, frame_times: list[float], columns: int = 5, cell_size: int = 256) -> dict[str, Any]:
        return mcp_pixel.pixel_video_to_sheet(project_root, asset_name, video_path, action, direction, frame_times, columns, cell_size)

    @mcp.tool()
    def pixel_cutout(project_root: str, asset_name: str, sheet_path: str, action: str, direction: str = "south", columns: int = 5, rows: int = 2, cell_width: int = 256, cell_height: int = 256, mask_mode: str = "hybrid", model_name: str = "isnet-general-use", decontaminate_edges: bool = True, debug_artifacts: bool = False) -> dict[str, Any]:
        return mcp_pixel.pixel_cutout(project_root, asset_name, sheet_path, action, direction, columns, rows, cell_width, cell_height, mask_mode, model_name, decontaminate_edges, debug_artifacts)

    @mcp.tool()
    def pixel_normalize(project_root: str, asset_name: str, sheet_path: str, action: str, direction: str = "south", columns: int = 0, rows: int = 0, cell_width: int = 256, cell_height: int = 256, pixel_restore_mode: str = "safe", source_cell_width: int | None = None, source_cell_height: int | None = None) -> dict[str, Any]:
        return mcp_pixel.pixel_normalize(project_root, asset_name, sheet_path, action, direction, columns, rows, cell_width, cell_height, pixel_restore_mode, source_cell_width, source_cell_height)

    @mcp.tool()
    def pixel_tilemap_47(project_root: str, asset_name: str, tileset_path: str, tile_size: int = 32, content_path: str = "/Game/UIM/Tiles") -> dict[str, Any]:
        return mcp_pixel.pixel_tilemap_47(project_root, asset_name, tileset_path, tile_size, content_path)

    @mcp.tool()
    def pixel_tilemap_dual_grid(project_root: str, asset_name: str, tileset_path: str, tile_size: int = 32, content_path: str = "/Game/UIM/Tiles") -> dict[str, Any]:
        return mcp_pixel.pixel_tilemap_dual_grid(project_root, asset_name, tileset_path, tile_size, content_path)

    @mcp.tool()
    def pixel_batch_matrix(project_root: str, asset_name: str, operation: str, cells: list[dict[str, Any]], common_options: dict[str, Any] | None = None) -> dict[str, Any]:
        return mcp_pixel.pixel_batch_matrix(project_root, asset_name, operation, cells, common_options)

    @mcp.tool()
    def game_ui_get_workspace(project_root: str) -> dict[str, Any]:
        """Inspect a specific UnrealImageMaker .uim workspace before creating Game UI HTML."""
        return mcp_game_ui.game_ui_get_workspace(project_root)

    @mcp.tool()
    def game_ui_get_dsl_prompt(project_root: str, width: int = 1920, height: int = 1080) -> dict[str, Any]:
        """Get the Game UI HTML DSL for project_root and a one-time dslPromptToken required by game_ui_write_html."""
        return mcp_game_ui.game_ui_get_dsl_prompt(project_root, width, height)

    @mcp.tool()
    def game_ui_write_html(project_root: str, screen_name: str, html: str, dsl_prompt_token: str) -> dict[str, Any]:
        """Write generated Game UI HTML into project_root/ui/html via MCP. Ask the user for screen_name first if they did not provide one; do not write local files directly."""
        return mcp_game_ui.game_ui_write_html(project_root, screen_name, html, dsl_prompt_token)

    @mcp.tool()
    def game_ui_get_current_workspace() -> dict[str, Any]:
        """Optional diagnostic: inspect the current/open UnrealImageMaker .uim workspace. HTML-only tasks do not need this; use game_ui_get_current_dsl_prompt first."""
        return mcp_game_ui.game_ui_get_current_workspace()

    @mcp.tool()
    def game_ui_get_current_dsl_prompt(width: int = 1920, height: int = 1080) -> dict[str, Any]:
        """Start here for HTML-only Game UI work: get the HTML DSL and one-time dslPromptToken for the app's current project."""
        return mcp_game_ui.game_ui_get_current_dsl_prompt(width, height)

    @mcp.tool()
    def game_ui_write_current_html(screen_name: str, html: str, dsl_prompt_token: str) -> dict[str, Any]:
        """Write generated Game UI HTML into the current/open workspace via MCP. Ask the user for screen_name first if they did not provide one."""
        return mcp_game_ui.game_ui_write_current_html(screen_name, html, dsl_prompt_token)

    @mcp.tool()
    def game_ui_bake_html(project_root: str, screen_name: str, html_path: str | None = None) -> dict[str, Any]:
        return mcp_game_ui.game_ui_bake_html(project_root, screen_name, html_path)

    @mcp.tool()
    def game_ui_list_structures(project_root: str) -> dict[str, Any]:
        return mcp_game_ui.game_ui_list_structures(project_root)

    @mcp.tool()
    def game_ui_list_texture_kits(project_root: str) -> dict[str, Any]:
        return mcp_game_ui.game_ui_list_texture_kits(project_root)

    @mcp.tool()
    def game_ui_export_umg(project_root: str, screen_name: str, structure_path: str, texture_kit_path: str, content_path: str = "/Game/UIM/UI") -> dict[str, Any]:
        return mcp_game_ui.game_ui_export_umg(project_root, screen_name, structure_path, texture_kit_path, content_path)

    @mcp.tool()
    def game_ui_generate_texture_kit(project_root: str, kit_name: str, concept_path: str | None = None, widget_tokens: list[dict[str, Any]] | None = None, provider: str = "openai_api", coverage: str = "default_full", mask_mode: str = "hybrid", decontaminate_edges: bool = True, debug_artifacts: bool = False, max_concurrency: int = 4) -> dict[str, Any]:
        return mcp_game_ui.game_ui_generate_texture_kit(project_root, kit_name, concept_path, widget_tokens, provider, coverage, mask_mode, decontaminate_edges, debug_artifacts, max_concurrency)

    @mcp.tool()
    def game_ui_register_texture_kit(project_root: str, kit_name: str, files: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
        return mcp_game_ui.game_ui_register_texture_kit(project_root, kit_name, files)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
