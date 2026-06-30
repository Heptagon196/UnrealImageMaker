from __future__ import annotations

import base64
import math
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from .asset_index import asset_id_from_name
from .manifest import AssetManifest
from .project import load_project_workspace, save_mcp_ui_state
from .specialized import (
    CHARACTER_DIRECTIONS_8,
    CHARACTER_GENERATED_DIRECTIONS,
    CHARACTER_MIRRORED_DIRECTIONS,
    TILEMAP_47_IDS,
    TILEMAP_DUAL_GRID_16_IDS,
    create_animation_sheet,
    create_pixel_anchor,
    create_pixel_concept,
    create_seedance_walk_video,
    create_spritesheet_cutout,
    create_spritesheet_from_video,
    create_tilemap_47_manifest,
    create_tilemap_dual_grid_manifest,
    create_video_debug_export,
    extract_video_frame_thumbnails,
    normalize_spritesheet,
)


DEFAULT_CONTENT_PATH = "/Game/UIM/Pixels"
DEFAULT_STYLE_ID = "pixel_art"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _project_path(project_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _manifest_result(manifest: AssetManifest) -> dict[str, Any]:
    data = manifest.to_dict()
    return {
        "manifest": data,
        "files": data.get("files", []),
        "registeredVersions": data.get("files", []),
    }


def _ok(project_root: Path, payload: dict[str, Any], *, ui_state: dict[str, Any] | None = None, next_stage: str | None = None) -> dict[str, Any]:
    saved_state = save_mcp_context(project_root, **ui_state) if ui_state else load_project_workspace(project_root).get("mcpUiState", {})
    return {
        "ok": True,
        **payload,
        "mcpUiState": saved_state,
        "nextSuggestedStage": next_stage,
    }


def _error(project_root: Path, tool: str, message: str, context: dict[str, Any]) -> dict[str, Any]:
    state = save_mcp_context(
        project_root,
        asset_name=str(context.get("asset_name") or ""),
        pixel_kind=str(context.get("asset_kind") or context.get("pixel_kind") or "character"),
        stage=str(context.get("stage") or "concept"),
        action=str(context.get("action") or "idle"),
        direction=str(context.get("direction") or "south"),
        sheet_mode=str(context.get("sheet_mode") or "direct"),
        last_tool=tool,
        last_message=message,
    )
    return {"ok": False, "error": message, "mcpUiState": state}


def _call_tool(tool: str, project_root: str, context: dict[str, Any], callback) -> dict[str, Any]:
    root = Path(project_root).resolve()
    try:
        return callback(root)
    except Exception as exc:
        return _error(root, tool, str(exc), context)


def save_mcp_context(
    project_root: Path,
    *,
    asset_name: str,
    pixel_kind: str,
    stage: str = "concept",
    action: str = "idle",
    direction: str = "south",
    sheet_mode: str = "direct",
    last_tool: str = "",
    last_message: str = "",
) -> dict[str, Any]:
    return save_mcp_ui_state(
        project_root,
        {
            "mainTab": "pixel",
            "assetName": asset_name,
            "pixelKind": pixel_kind,
            "pixelStage": stage,
            "pixelAction": action,
            "pixelDirection": direction,
            "pixelSheetMode": sheet_mode,
            "lastTool": last_tool,
            "lastMessage": last_message,
            "updatedAt": _now(),
        },
    )


def pixel_presets() -> dict[str, Any]:
    return {
        "characterDirections": CHARACTER_DIRECTIONS_8,
        "generatedCharacterDirections": CHARACTER_GENERATED_DIRECTIONS,
        "mirroredCharacterDirections": CHARACTER_MIRRORED_DIRECTIONS,
        "tilemap47": TILEMAP_47_IDS,
        "tilemapDualGrid16": TILEMAP_DUAL_GRID_16_IDS,
    }


def pixel_get_workspace(project_root: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    return {"ok": True, "workspace": load_project_workspace(root), "presets": pixel_presets()}


def pixel_set_context(
    project_root: str,
    asset_name: str,
    pixel_kind: str,
    stage: str = "concept",
    action: str = "idle",
    direction: str = "south",
    sheet_mode: str = "direct",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state = save_mcp_context(
        root,
        asset_name=asset_name,
        pixel_kind=pixel_kind,
        stage=stage,
        action=action,
        direction=direction,
        sheet_mode=sheet_mode,
        last_tool="pixel_set_context",
        last_message="Context updated by MCP.",
    )
    return {"ok": True, "mcpUiState": state}


def pixel_generate_concept(
    project_root: str,
    asset_name: str,
    subject: str,
    asset_kind: str,
    output_size: str = "1024x1024",
    image_provider: str = "openai_api",
) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        manifest = create_pixel_concept(root, asset_name, subject, asset_kind, DEFAULT_STYLE_ID, image_provider, DEFAULT_CONTENT_PATH, output_size=output_size)
        return _ok(
            root,
            _manifest_result(manifest),
            ui_state={
                "asset_name": asset_name,
                "pixel_kind": asset_kind,
                "stage": "south_anchor",
                "action": "idle",
                "direction": "south",
                "sheet_mode": "direct" if asset_kind == "tilemap" else "video",
                "last_tool": "pixel_generate_concept",
                "last_message": "Concept generated by MCP.",
            },
            next_stage="south_anchor",
        )

    return _call_tool("pixel_generate_concept", project_root, context, run)


def pixel_generate_anchor(
    project_root: str,
    asset_name: str,
    subject: str,
    asset_kind: str,
    direction: str = "south",
    anchor_stage: str = "south",
    reference_anchor_path: str | None = None,
    dynamic_effect: str = "active effects, glow, particles, projectiles, and charged action pose",
    logical_frame_size: str = "256x256",
    output_size: str = "1024x1024",
    image_provider: str = "openai_api",
    mirror_from: str | None = None,
) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        resolved_direction = "single" if asset_kind != "character" else direction
        manifest = create_pixel_anchor(
            root,
            asset_name,
            subject,
            asset_kind,
            resolved_direction,
            DEFAULT_STYLE_ID,
            image_provider,
            DEFAULT_CONTENT_PATH,
            reference_anchor_path=_project_path(root, reference_anchor_path),
            anchor_stage=anchor_stage,
            dynamic_effect=dynamic_effect,
            logical_frame_size=logical_frame_size,
            output_size=output_size,
            mirror_from=mirror_from,
        )
        next_stage = "neutral_anchor" if asset_kind == "character" and anchor_stage == "south" else "direction_anchor" if asset_kind == "character" and anchor_stage == "neutral" else "sheet"
        return _ok(
            root,
            _manifest_result(manifest),
            ui_state={
                "asset_name": asset_name,
                "pixel_kind": asset_kind,
                "stage": next_stage,
                "action": "idle",
                "direction": resolved_direction if resolved_direction != "single" else "south",
                "sheet_mode": "direct" if asset_kind == "tilemap" else "video",
                "last_tool": "pixel_generate_anchor",
                "last_message": "Anchor generated by MCP.",
            },
            next_stage=next_stage,
        )

    return _call_tool("pixel_generate_anchor", project_root, context, run)


def pixel_generate_sheet(
    project_root: str,
    asset_name: str,
    subject: str,
    asset_kind: str,
    action: str,
    direction: str = "south",
    columns: int = 5,
    rows: int = 2,
    cell_size: int = 256,
    reference_path: str | None = None,
    action_description: str = "",
    attack_name: str = "magic projectile attack",
    effect_color: str = "violet",
    projectile_or_effect: str = "projectile or impact effect",
    image_provider: str = "openai_api",
    mirror_from: str | None = None,
) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        resolved_direction = "single" if asset_kind != "character" else direction
        manifest = create_animation_sheet(
            root,
            asset_name,
            subject,
            asset_kind,
            asset_id_from_name(action or "idle"),
            resolved_direction,
            DEFAULT_STYLE_ID,
            image_provider,
            DEFAULT_CONTENT_PATH,
            columns=columns,
            rows=rows,
            cell_size=cell_size,
            reference_path=_project_path(root, reference_path),
            attack_name=attack_name,
            effect_color=effect_color,
            projectile_or_effect=projectile_or_effect,
            action_description=action_description,
            mirror_from=mirror_from,
        )
        return _ok(
            root,
            _manifest_result(manifest),
            ui_state={
                "asset_name": asset_name,
                "pixel_kind": asset_kind,
                "stage": "cutout",
                "action": asset_id_from_name(action or "idle"),
                "direction": resolved_direction if resolved_direction != "single" else "south",
                "sheet_mode": "direct",
                "last_tool": "pixel_generate_sheet",
                "last_message": "Sheet generated by MCP.",
            },
            next_stage="cutout",
        )

    return _call_tool("pixel_generate_sheet", project_root, context, run)


def pixel_generate_seedance_video(
    project_root: str,
    asset_name: str,
    anchor_path: str,
    action: str,
    direction: str,
    prompt: str,
    model: str | None = None,
    resolution: str | None = None,
    seconds: int = 5,
    asset_kind: str = "character",
) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        result = create_seedance_walk_video(root, asset_name, _project_path(root, anchor_path) or Path(anchor_path), direction, prompt, seconds, action=action, model=model, resolution=resolution)
        return _ok(
            root,
            {"result": result, "files": [{"role": f"video:{asset_id_from_name(action)}:{direction}", "path": result.get("path", "")}], "registeredVersions": []},
            ui_state={
                "asset_name": asset_name,
                "pixel_kind": asset_kind,
                "stage": "sheet",
                "action": asset_id_from_name(action),
                "direction": direction,
                "sheet_mode": "video",
                "last_tool": "pixel_generate_seedance_video",
                "last_message": "Seedance video generated by MCP.",
            },
            next_stage="sheet",
        )

    return _call_tool("pixel_generate_seedance_video", project_root, context, run)


def _even_times(start: float, end: float, count: int) -> list[float]:
    if count <= 1:
        return [round(max(0.0, start), 3)]
    return [round(start + (end - start) * index / (count - 1), 3) for index in range(count)]


def _fps_times(start: float, end: float, fps: float) -> list[float]:
    step = 1 / max(1.0, min(60.0, float(fps or 8)))
    tail_guard = max(0.001, min(0.1, step * 0.5))
    sample_end = max(0.0, end - tail_guard)
    times: list[float] = []
    current = max(0.0, start)
    while current <= sample_end + 0.0001 and len(times) < 240:
        times.append(round(current, 3))
        current += step
    return times


def pixel_video_select_frames(
    project_root: str,
    video_path: str,
    mode: str,
    range_start: float = 0.0,
    range_end: float | None = None,
    fps: float = 8.0,
    frame_times: list[float] | None = None,
    thumbnail_size: int = 144,
) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        if mode == "manual":
            times = [round(max(0.0, float(time)), 3) for time in (frame_times or [])]
        elif mode == "fps":
            if range_end is None:
                raise ValueError("range_end is required for FPS frame selection")
            times = _fps_times(float(range_start), float(range_end), fps)
        elif mode == "even":
            if range_end is None:
                raise ValueError("range_end is required for even frame selection")
            count = max(1, len(frame_times or []) or 10)
            times = _even_times(float(range_start), float(range_end), count)
        else:
            raise ValueError(f"Unknown video frame selection mode: {mode}")
        thumbnails = extract_video_frame_thumbnails(_project_path(root, video_path) or Path(video_path), times, thumbnail_size)
        frames = [{"id": f"frame_{index:03d}", **frame, "selected": False, "loopHint": False} for index, frame in enumerate(thumbnails.get("frames", []))]
        return _ok(root, {"result": {"mode": mode, "extractor": thumbnails.get("extractor", ""), "frameTimes": times, "frames": frames}}, ui_state={"asset_name": "", "pixel_kind": "character", "stage": "sheet", "action": "walk", "direction": "south", "sheet_mode": "video", "last_tool": "pixel_video_select_frames", "last_message": f"Selected {len(times)} video frames by MCP."}, next_stage="sheet")

    return _call_tool("pixel_video_select_frames", project_root, context, run)


def _thumbnail_metrics(thumbnail: str) -> dict[str, list[float]]:
    from PIL import Image

    data = thumbnail.split(",", 1)[1] if thumbnail.startswith("data:") and "," in thumbnail else thumbnail
    image = Image.open(BytesIO(base64.b64decode(data))).convert("RGBA").resize((96, 96))
    pixels = image.load()
    bins: dict[tuple[int, int, int], int] = {}
    for index in range(96):
        for x, y in ((index, 0), (index, 95), (0, index), (95, index)):
            r, g, b, _ = pixels[x, y]
            key = (round(r / 16), round(g / 16), round(b / 16))
            bins[key] = bins.get(key, 0) + 1
    bg_bin = max(bins.items(), key=lambda item: item[1])[0] if bins else (15, 15, 15)
    bg = tuple(max(0, min(255, value * 16 + 8)) for value in bg_bin)
    min_x, min_y, max_x, max_y = 96, 96, -1, -1
    for y in range(96):
        for x in range(96):
            r, g, b, a = pixels[x, y]
            distance = math.dist((r, g, b), bg)
            if a > 8 and distance > 42:
                min_x, min_y, max_x, max_y = min(min_x, x), min(min_y, y), max(max_x, x), max(max_y, y)
    if max_x >= min_x and max_y >= min_y:
        crop = image.crop((max(0, min_x - 5), max(0, min_y - 5), min(95, max_x + 5) + 1, min(95, max_y + 5) + 1))
    else:
        crop = image
    canvas = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    crop.thumbnail((64, 64))
    canvas.alpha_composite(crop, ((64 - crop.width) // 2, (64 - crop.height) // 2))
    histogram = [0.0] * 256
    spatial: list[float] = []
    for r, g, b, a in canvas.getdata():
        gray = max(0, min(255, round(r * 0.299 + g * 0.587 + b * 0.114)))
        distance = math.dist((r, g, b), bg)
        weight = 1.0 if a > 8 and distance > 42 else 0.0
        histogram[gray] += weight
        spatial.append(float(gray if weight else 255))
    return {"histogram": histogram, "pixels": spatial}


def _histogram_correlation(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return -1.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((left[index] - left_mean) * (right[index] - right_mean) for index in range(len(left)))
    left_energy = sum((value - left_mean) ** 2 for value in left)
    right_energy = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_energy * right_energy)
    return numerator / denominator if denominator > 0 else 1.0


def _pixel_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return -1.0
    return 1 - sum(abs(left[index] - right[index]) for index in range(len(left))) / (len(left) * 255)


def pixel_video_find_loop(project_root: str, video_path: str, frame_times: list[float], min_score: float = 0.9) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        times = [round(max(0.0, float(time)), 3) for time in frame_times]
        thumbnails = extract_video_frame_thumbnails(_project_path(root, video_path) or Path(video_path), times, 384)
        frames = thumbnails.get("frames", [])
        if len(frames) < 3:
            raise ValueError("At least 3 frames are required to find a loop frame")
        metrics = [_thumbnail_metrics(str(frame["thumbnail"])) for frame in frames]
        candidates = []
        best = None
        threshold = max(0.0, min(1.0, float(min_score)))
        for index in range(2, len(metrics)):
            histogram = _histogram_correlation(metrics[0]["histogram"], metrics[index]["histogram"])
            spatial = _pixel_similarity(metrics[0]["pixels"], metrics[index]["pixels"])
            score = spatial * 0.82 + max(0.0, histogram) * 0.18
            result = {"index": index, "time": times[index], "score": score, "spatial": spatial, "histogram": histogram}
            if score >= threshold:
                candidates.append(result)
            if best is None or score > best["score"]:
                best = result
        selected = max(candidates, key=lambda item: item["score"]) if candidates else None
        return _ok(root, {"result": {"threshold": threshold, "candidates": candidates, "selected": selected, "best": best, "frames": frames}}, ui_state={"asset_name": "", "pixel_kind": "character", "stage": "sheet", "action": "walk", "direction": "south", "sheet_mode": "video", "last_tool": "pixel_video_find_loop", "last_message": f"Found {len(candidates)} loop candidates by MCP."}, next_stage="sheet")

    return _call_tool("pixel_video_find_loop", project_root, context, run)


def pixel_video_debug_export(project_root: str, asset_name: str, video_path: str, action: str, direction: str, frame_times: list[float], export_type: str, columns: int = 5, cell_size: int = 256) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        rows = max(1, math.ceil(len(frame_times) / max(1, columns)))
        manifest = create_video_debug_export(root, asset_name, _project_path(root, video_path) or Path(video_path), action, direction, export_type, columns, rows, cell_size, DEFAULT_STYLE_ID, DEFAULT_CONTENT_PATH, frame_times)
        return _ok(root, _manifest_result(manifest), ui_state={"asset_name": asset_name, "pixel_kind": "character", "stage": "sheet", "action": asset_id_from_name(action), "direction": direction, "sheet_mode": "video", "last_tool": "pixel_video_debug_export", "last_message": "Video debug export generated by MCP."}, next_stage="sheet")

    return _call_tool("pixel_video_debug_export", project_root, context, run)


def pixel_video_to_sheet(project_root: str, asset_name: str, video_path: str, action: str, direction: str, frame_times: list[float], columns: int = 5, cell_size: int = 256) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        rows = max(1, math.ceil(len(frame_times) / max(1, columns)))
        manifest = create_spritesheet_from_video(root, asset_name, _project_path(root, video_path) or Path(video_path), action, direction, columns, rows, cell_size, DEFAULT_STYLE_ID, DEFAULT_CONTENT_PATH, frame_times)
        return _ok(root, _manifest_result(manifest), ui_state={"asset_name": asset_name, "pixel_kind": "character", "stage": "cutout", "action": asset_id_from_name(action), "direction": direction, "sheet_mode": "video", "last_tool": "pixel_video_to_sheet", "last_message": "Video sheet generated by MCP."}, next_stage="cutout")

    return _call_tool("pixel_video_to_sheet", project_root, context, run)


def pixel_cutout(project_root: str, asset_name: str, sheet_path: str, action: str, direction: str = "south", columns: int = 5, rows: int = 2, cell_width: int = 256, cell_height: int = 256, mask_mode: str = "hybrid", model_name: str = "isnet-general-use", decontaminate_edges: bool = True, debug_artifacts: bool = False) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        manifest = create_spritesheet_cutout(root, _project_path(root, sheet_path) or Path(sheet_path), asset_name, action, direction, columns, rows, cell_width, cell_height, DEFAULT_STYLE_ID, DEFAULT_CONTENT_PATH, model_name=model_name, mask_mode=mask_mode, decontaminate_edges=decontaminate_edges, debug_artifacts=debug_artifacts)
        return _ok(root, _manifest_result(manifest), ui_state={"asset_name": asset_name, "pixel_kind": "character", "stage": "normalize", "action": asset_id_from_name(action), "direction": direction, "sheet_mode": "direct", "last_tool": "pixel_cutout", "last_message": "Cutout generated by MCP."}, next_stage="normalize")

    return _call_tool("pixel_cutout", project_root, context, run)


def pixel_normalize(project_root: str, asset_name: str, sheet_path: str, action: str, direction: str = "south", columns: int = 0, rows: int = 0, cell_width: int = 256, cell_height: int = 256, pixel_restore_mode: str = "safe", source_cell_width: int | None = None, source_cell_height: int | None = None) -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        manifest = normalize_spritesheet(root, _project_path(root, sheet_path) or Path(sheet_path), asset_name, action, columns, rows, cell_width, cell_height, DEFAULT_STYLE_ID, DEFAULT_CONTENT_PATH, direction=direction, pixel_restore_mode=pixel_restore_mode, source_cell_width=source_cell_width, source_cell_height=source_cell_height)
        return _ok(root, _manifest_result(manifest), ui_state={"asset_name": asset_name, "pixel_kind": "character", "stage": "normalize", "action": asset_id_from_name(action), "direction": direction, "sheet_mode": "direct", "last_tool": "pixel_normalize", "last_message": "Runtime sheet generated by MCP."}, next_stage="normalize")

    return _call_tool("pixel_normalize", project_root, context, run)


def pixel_tilemap_47(project_root: str, asset_name: str, tileset_path: str, tile_size: int = 32, content_path: str = "/Game/UIM/Tiles") -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        manifest = create_tilemap_47_manifest(root, asset_name, _project_path(root, tileset_path) or Path(tileset_path), tile_size, DEFAULT_STYLE_ID, content_path)
        return _ok(root, _manifest_result(manifest), ui_state={"asset_name": asset_name, "pixel_kind": "tilemap", "stage": "tilemap_tileset", "action": "idle", "direction": "south", "sheet_mode": "direct", "last_tool": "pixel_tilemap_47", "last_message": "Tilemap manifest generated by MCP."}, next_stage="tilemap_tileset")

    return _call_tool("pixel_tilemap_47", project_root, context, run)


def pixel_tilemap_dual_grid(project_root: str, asset_name: str, tileset_path: str, tile_size: int = 32, content_path: str = "/Game/UIM/Tiles") -> dict[str, Any]:
    context = locals()

    def run(root: Path) -> dict[str, Any]:
        manifest = create_tilemap_dual_grid_manifest(root, asset_name, _project_path(root, tileset_path) or Path(tileset_path), tile_size, DEFAULT_STYLE_ID, content_path)
        return _ok(root, _manifest_result(manifest), ui_state={"asset_name": asset_name, "pixel_kind": "tilemap", "stage": "tilemap_tileset", "action": "idle", "direction": "south", "sheet_mode": "direct", "last_tool": "pixel_tilemap_dual_grid", "last_message": "Dual-grid tilemap manifest generated by MCP."}, next_stage="tilemap_tileset")

    return _call_tool("pixel_tilemap_dual_grid", project_root, context, run)


def pixel_batch_matrix(project_root: str, asset_name: str, operation: str, cells: list[dict[str, Any]], common_options: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    options = common_options or {}
    results = []
    columns = int(options.get("columns", 0))
    rows = int(options.get("rows", 0))
    cutout_columns = columns or 5
    cutout_rows = rows or 2
    cell_width = int(options.get("cell_width", options.get("cell_size", 256)))
    cell_height = int(options.get("cell_height", options.get("cell_size", 256)))
    source_cell_width = int(options["source_cell_width"]) if options.get("source_cell_width") else None
    source_cell_height = int(options["source_cell_height"]) if options.get("source_cell_height") else None
    for cell in cells:
        action = str(cell.get("action") or options.get("action") or "idle")
        direction = str(cell.get("direction") or options.get("direction") or "south")
        try:
            if operation == "cutout":
                result = pixel_cutout(project_root, asset_name, str(cell.get("sheet_path") or options.get("sheet_path")), action, direction, cutout_columns, cutout_rows, source_cell_width or cell_width, source_cell_height or cell_height, str(options.get("mask_mode", "hybrid")), str(options.get("model_name", "isnet-general-use")), bool(options.get("decontaminate_edges", True)), bool(options.get("debug_artifacts", False)))
            elif operation == "normalize":
                result = pixel_normalize(project_root, asset_name, str(cell.get("sheet_path") or options.get("sheet_path")), action, direction, columns, rows, cell_width, cell_height, str(options.get("pixel_restore_mode", "safe")), source_cell_width, source_cell_height)
            elif operation == "cutout_normalize":
                cutout = pixel_cutout(project_root, asset_name, str(cell.get("sheet_path") or options.get("sheet_path")), action, direction, cutout_columns, cutout_rows, source_cell_width or cell_width, source_cell_height or cell_height, str(options.get("mask_mode", "hybrid")), str(options.get("model_name", "isnet-general-use")), bool(options.get("decontaminate_edges", True)), bool(options.get("debug_artifacts", False)))
                cutout_path = cutout.get("files", [{}])[0].get("path") if cutout.get("ok") else ""
                result = pixel_normalize(project_root, asset_name, str(cutout_path), action, direction, columns, rows, cell_width, cell_height, str(options.get("pixel_restore_mode", "safe")), source_cell_width, source_cell_height) if cutout_path else cutout
            elif operation == "generate_missing":
                result = pixel_generate_sheet(project_root, asset_name, str(options.get("subject", "")), str(options.get("asset_kind", "character")), action, direction, int(options.get("columns", 5)), int(options.get("rows", 2)), int(options.get("cell_size", 256)), cell.get("reference_path") or options.get("reference_path"), str(options.get("action_description", "")))
            else:
                raise ValueError(f"Unknown batch operation: {operation}")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        results.append({"cell": cell, "result": result})
    state = save_mcp_context(root, asset_name=asset_name, pixel_kind=str(options.get("asset_kind", "character")), stage="normalize" if operation in {"normalize", "cutout_normalize"} else "sheet", action=str(cells[0].get("action", "idle") if cells else "idle"), direction=str(cells[0].get("direction", "south") if cells else "south"), sheet_mode="direct", last_tool="pixel_batch_matrix", last_message=f"Batch {operation} completed by MCP.")
    return {"ok": True, "result": {"operation": operation, "items": results}, "mcpUiState": state, "nextSuggestedStage": state.get("pixelStage")}
