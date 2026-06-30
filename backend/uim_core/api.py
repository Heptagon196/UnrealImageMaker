from __future__ import annotations

import os
import logging
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import mcp_game_ui
from .asset_index import (
    asset_id_from_name,
    asset_index_to_record,
    delete_asset,
    delete_asset_version,
    load_asset_index,
    primary_version,
    register_asset_version,
    reorder_asset_versions,
    save_asset_index,
    sync_asset_and_record,
    sync_texture_manifest_primary,
)
from .image_processing import clean_alpha_halo, nearest_scale, quantize_palette, trim_transparent
from .constants import API_CONTRACT_VERSION, APP_VERSION, PROJECT_FILE
from .manifest import AssetManifest, validate_manifest, write_manifest
from .models import (
    MODEL_REGISTRY,
    delete_model,
    install_marker,
    load_models_lock,
    lock_model,
    missing_locked_models,
    model_status,
)
from .network import configured_network_proxy, open_external_url, set_network_proxy
from .json_io import read_json, write_json
from .game_ui import (
    bake_game_ui_html,
    clear_texture_kit,
    delete_game_ui_html,
    delete_game_ui_structure,
    export_game_ui_umg,
    game_ui_dsl_prompt,
    generate_texture_kit,
    list_game_ui_html_prototypes,
    list_game_ui_structures,
    list_texture_kits,
    read_game_ui_html,
    register_texture_kit,
    write_game_ui_html,
)
from .paths import model_cache_dir, user_data_dir, workspace_root
from .pixel_postprocess import pixel_dependency_statuses
from .pipelines import create_sprite_asset, create_spritesheet_manifest, create_ui_kit_manifest
from .providers.seedance_provider import DEFAULT_SEEDANCE_ENDPOINT, DEFAULT_SEEDANCE_MODEL, DEFAULT_SEEDANCE_RESOLUTION, SeedanceProvider, normalize_seedance_model
from .providers.codex_oauth_image import (
    codex_oauth_status,
    codex_stream_events,
    complete_codex_oauth,
    create_pkce_flow,
    delete_codex_oauth_tokens,
    refresh_codex_oauth_tokens,
    safe_token_status,
)
from .project import create_project, load_project, load_project_workspace, models_lock_path, save_current_project_root, save_processing_queue, save_workflow_slots
from .providers.rembg_adapter import RembgAdapter
from .providers.sam21_adapter import Sam21Adapter, SamPrompt
from .providers.openai_image import DEFAULT_OPENAI_BASE_URL
from .specialized import (
    CHARACTER_DIRECTIONS_8,
    CHARACTER_GENERATED_DIRECTIONS,
    CHARACTER_MIRRORED_DIRECTIONS,
    TILEMAP_47_IDS,
    TILEMAP_DUAL_GRID_16_IDS,
    create_animation_sheet,
    import_animation_sheet,
    create_pixel_anchor,
    create_pixel_concept,
    create_spritesheet_cutout,
    create_spritesheet_from_video,
    create_seedance_walk_video,
    create_tilemap_47_manifest,
    create_tilemap_from_seed_manifest,
    create_tilemap_seed_concept,
    create_tilemap_dual_grid_manifest,
    create_video_debug_export,
    extract_video_frame_thumbnails,
    create_ui_concept,
    import_ui_concept,
    create_ui_widget,
    normalize_spritesheet,
)
from .unreal.mcp_bridge import UnrealMcpBridge
from .unreal.python_export import generate_import_script, unreal_export_summary
from .validation import validate_asset_manifest, validate_file_exists, validate_frame_consistency

app = FastAPI(title="UnrealImageMaker API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?|http://tauri\.localhost|tauri://localhost)$",
    allow_methods=["*"],
    allow_headers=["*"],
)

CODEX_OAUTH_CALLBACK_HOST = "localhost"
CODEX_OAUTH_CALLBACK_PORT = 1455
_codex_oauth_lock = threading.Lock()
_codex_oauth_pending: dict[str, dict[str, Any]] = {}
_stream_lock = threading.Lock()
_stream_sessions: dict[str, list[str]] = {}
_stream_cancelled: set[str] = set()
logger = logging.getLogger("uim_core.api")


def _raise_bad_request(context: str, exc: Exception, **metadata: object) -> None:
    safe_metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
    logger.exception("API request failed: %s metadata=%s", context, safe_metadata)
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _append_stream_event(session_id: str, event: str) -> None:
    if not session_id or not event:
        return
    with _stream_lock:
        events = _stream_sessions.setdefault(session_id, [])
        events.append(event)
        del events[:-240]


def _is_stream_cancelled(session_id: str | None) -> bool:
    if not session_id:
        return False
    with _stream_lock:
        return session_id in _stream_cancelled


def _run_with_stream_session(session_id: str | None, task):
    if not session_id:
        return task()
    with _stream_lock:
        _stream_sessions.setdefault(session_id, [])
        _stream_cancelled.discard(session_id)
    with codex_stream_events(lambda event: _append_stream_event(session_id, event)):
        return task()


def _callback_html(title: str, message: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; display: grid; min-height: 100vh; place-items: center; background: #eef2f6; color: #181b21; }}
    main {{ width: min(520px, calc(100vw - 32px)); border: 1px solid #d9e0e8; border-radius: 8px; padding: 28px; background: white; box-shadow: 0 12px 34px rgba(30, 39, 50, 0.08); }}
    h1 {{ margin: 0 0 12px; font-size: 22px; }}
    p {{ margin: 0; line-height: 1.6; color: #465161; }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <p>{message}</p>
  </main>
  <script>window.setTimeout(() => window.close(), 1200);</script>
</body>
</html>""".encode("utf-8")


def _set_oauth_result(state: str, status: str, message: str, codex_status: dict[str, Any] | None = None) -> None:
    if not state:
        return
    with _codex_oauth_lock:
        current = _codex_oauth_pending.setdefault(state, {})
        current.update(
            {
                "status": status,
                "message": message,
                "codexOAuth": codex_status or codex_oauth_status(),
                "updatedAt": time.time(),
            }
        )


class CodexOAuthCallbackHandler(BaseHTTPRequestHandler):
    server_version = "UnrealImageMakerOAuth/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404)
            return

        query = urllib.parse.parse_qs(parsed.query)
        state = query.get("state", [""])[0].strip()
        code = query.get("code", [""])[0].strip()
        oauth_error = query.get("error", [""])[0].strip()

        if oauth_error:
            message = query.get("error_description", [oauth_error])[0]
            _set_oauth_result(state, "error", message)
            self._send_html(400, "绑定失败", message)
            _shutdown_codex_oauth_callback_server(state)
            return

        with _codex_oauth_lock:
            pending = _codex_oauth_pending.get(state, {}).copy()
        verifier = str(pending.get("verifier") or "")
        redirect_uri = str(pending.get("redirectUri") or "")
        expires_at = float(pending.get("expiresAt") or 0)

        if not state or not verifier:
            message = "未找到匹配的 OAuth 会话，请回到 UnrealImageMaker 重新开始绑定。"
            _set_oauth_result(state, "error", message)
            self._send_html(400, "绑定失败", message)
            _shutdown_codex_oauth_callback_server(state)
            return
        if expires_at and expires_at < time.time():
            message = "OAuth 会话已过期，请回到 UnrealImageMaker 重新开始绑定。"
            _set_oauth_result(state, "error", message)
            self._send_html(400, "绑定失败", message)
            _shutdown_codex_oauth_callback_server(state)
            return
        if not code:
            message = "OAuth 回调缺少授权 code。"
            _set_oauth_result(state, "error", message)
            self._send_html(400, "绑定失败", message)
            _shutdown_codex_oauth_callback_server(state)
            return

        callback_url = f"{redirect_uri}?{parsed.query}"
        try:
            tokens = complete_codex_oauth(callback_url, verifier, state, redirect_uri)
            status = safe_token_status(tokens)
        except Exception as exc:
            message = str(exc)
            _set_oauth_result(state, "error", message)
            self._send_html(400, "绑定失败", message)
            _shutdown_codex_oauth_callback_server(state)
            return

        _set_oauth_result(state, "success", "ChatGPT 订阅账号已绑定。", status)
        self._send_html(200, "绑定完成", "ChatGPT 订阅账号已绑定，可以关闭此页面并回到 UnrealImageMaker。")
        _shutdown_codex_oauth_callback_server(state)

    def _send_html(self, status_code: int, title: str, message: str) -> None:
        body = _callback_html(title, message)
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _codex_oauth_redirect_uri() -> str:
    return f"http://{CODEX_OAUTH_CALLBACK_HOST}:{CODEX_OAUTH_CALLBACK_PORT}/auth/callback"


def _create_codex_oauth_callback_server() -> ThreadingHTTPServer:
    try:
        server = ThreadingHTTPServer((CODEX_OAUTH_CALLBACK_HOST, CODEX_OAUTH_CALLBACK_PORT), CodexOAuthCallbackHandler)
    except OSError as exc:
        raise RuntimeError(f"无法启动 OAuth 本地回调服务 localhost:{CODEX_OAUTH_CALLBACK_PORT}：{exc}") from exc
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"codex-oauth-callback-{CODEX_OAUTH_CALLBACK_PORT}",
        daemon=True,
    )
    thread.start()
    return server


def _shutdown_codex_oauth_callback_server(state: str) -> None:
    with _codex_oauth_lock:
        server = _codex_oauth_pending.get(state, {}).get("server")
        if state in _codex_oauth_pending:
            _codex_oauth_pending[state]["server"] = None
    if isinstance(server, ThreadingHTTPServer):
        threading.Thread(target=server.shutdown, name="codex-oauth-callback-shutdown", daemon=True).start()


def _register_codex_oauth_flow(flow: dict[str, str], server: ThreadingHTTPServer | None, message: str) -> None:
    with _codex_oauth_lock:
        _codex_oauth_pending[flow["state"]] = {
            "status": "pending",
            "message": message,
            "verifier": flow["verifier"],
            "redirectUri": flow["redirect_uri"],
            "server": server,
            "expiresAt": time.time() + 600,
            "codexOAuth": codex_oauth_status(),
            "updatedAt": time.time(),
        }


def _oauth_poll_response(state: str, current: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": state,
        "status": current.get("status", "pending"),
        "message": current.get("message", ""),
        "redirectUri": current.get("redirectUri", ""),
        "expiresAt": current.get("expiresAt", 0),
        "codexOAuth": current.get("codexOAuth") or codex_oauth_status(),
    }


class CreateProjectRequest(BaseModel):
    root: str
    name: str
    overwrite: bool = False


class ProjectRequest(BaseModel):
    root: str


class ModelActionRequest(BaseModel):
    cache_root: str | None = None
    model_id: str


class RembgRequest(BaseModel):
    input_path: str
    output_path: str
    model_name: str = "isnet-general-use"


class SamDownloadRequest(BaseModel):
    cache_root: str | None = None
    model_id: str = "sam2.1_hiera_small"


class SamSegmentRequest(BaseModel):
    cache_root: str | None = None
    model_id: str = "sam2.1_hiera_small"
    image_path: str
    output_mask_path: str
    points: list[tuple[int, int]] | None = None
    labels: list[int] | None = None
    box: tuple[int, int, int, int] | None = None


class ImageProcessRequest(BaseModel):
    input_path: str
    output_path: str
    operation: str
    padding: int = 0
    scale: int = 1
    colors: int = 32


class AssetImageRegisterRequest(BaseModel):
    project_root: str
    asset_name: str
    image_path: str
    role: str = "image"
    label: str | None = None


class AssetVersionOrderRequest(BaseModel):
    project_root: str
    version_ids: list[str]


class AssetSettingsRequest(BaseModel):
    project_root: str
    display_name: str | None = None
    settings: dict[str, Any]


class ProcessingQueueRequest(BaseModel):
    project_root: str
    queue: list[dict[str, Any]]


class WorkflowSlotsRequest(BaseModel):
    project_root: str
    workflow_slots: dict[str, Any]


class SpriteAssetRequest(BaseModel):
    project_root: str
    prompt: str
    asset_name: str
    style_id: str = "pixel_art"
    content_path: str = "/Game/UIM"
    image_provider: str = "openai_api"
    stream_session: str | None = None


class SpritesheetRequest(BaseModel):
    project_root: str
    sheet_path: str
    asset_name: str
    style_id: str = "pixel_art"
    cell_width: int = Field(gt=0)
    cell_height: int = Field(gt=0)
    content_path: str = "/Game/UIM"


class UIKitRequest(BaseModel):
    project_root: str
    asset_name: str
    style_id: str = "semi_realistic_ui"
    state_files: dict[str, str]
    nine_slice: tuple[int, int, int, int] | None = None
    content_path: str = "/Game/UIM/UI"


class ManifestRequest(BaseModel):
    project_root: str
    manifest: dict[str, Any]
    output_path: str | None = None


class RuntimeSettingsRequest(BaseModel):
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    unreal_mcp_url: str | None = None
    huggingface_token: str | None = None
    network_proxy: str | None = None
    seedance_api_key: str | None = None
    seedance_endpoint: str | None = None
    seedance_model: str | None = None
    seedance_resolution: str | None = None


class PixelConceptRequest(BaseModel):
    project_root: str
    asset_name: str
    subject: str
    asset_kind: str = "character"
    style_id: str = "pixel_art"
    image_provider: str = "openai_api"
    content_path: str = "/Game/UIM/Pixels"
    output_size: str = "1024x1024"
    stream_session: str | None = None


class PixelAnchorRequest(BaseModel):
    project_root: str
    asset_name: str
    subject: str
    asset_kind: str = "character"
    direction: str = "south"
    style_id: str = "pixel_art"
    image_provider: str = "openai_api"
    content_path: str = "/Game/UIM/Pixels"
    concept_path: str | None = None
    reference_anchor_path: str | None = None
    anchor_stage: str = "south"
    dynamic_effect: str = "active effects, glow, particles, projectiles, and charged action pose"
    logical_frame_size: str = "256x256"
    output_size: str = "1024x1024"
    mirror_from: str | None = None
    stream_session: str | None = None


class PixelSheetRequest(BaseModel):
    project_root: str
    asset_name: str
    subject: str
    asset_kind: str = "character"
    action: str = "idle"
    direction: str = "south"
    style_id: str = "pixel_art"
    image_provider: str = "openai_api"
    content_path: str = "/Game/UIM/Pixels"
    columns: int = Field(default=5, gt=0)
    rows: int = Field(default=2, gt=0)
    cell_size: int = Field(default=256, gt=0)
    reference_path: str | None = None
    attack_name: str = "magic projectile attack"
    effect_color: str = "violet"
    projectile_or_effect: str = "projectile or impact effect"
    action_description: str = ""
    mirror_from: str | None = None
    stream_session: str | None = None


class PixelSheetImportRequest(BaseModel):
    project_root: str
    asset_name: str
    sheet_path: str
    asset_kind: str = "character"
    action: str = "idle"
    direction: str = "south"
    style_id: str = "pixel_art"
    content_path: str = "/Game/UIM/Pixels"
    columns: int = Field(default=5, gt=0)
    rows: int = Field(default=2, gt=0)
    cell_size: int = Field(default=256, gt=0)


class PixelNormalizeRequest(BaseModel):
    project_root: str
    sheet_path: str
    asset_name: str
    action: str = "idle"
    direction: str | None = None
    columns: int = Field(default=0, ge=0)
    rows: int = Field(default=0, ge=0)
    source_cell_width: int | None = Field(default=None, gt=0)
    source_cell_height: int | None = Field(default=None, gt=0)
    cell_width: int = Field(default=256, gt=0)
    cell_height: int = Field(default=256, gt=0)
    style_id: str = "pixel_art"
    content_path: str = "/Game/UIM/Pixels"
    chroma_key: tuple[int, int, int] | None = (255, 0, 255)
    pixel_restore_mode: str = "safe"
    stream_session: str | None = None


class PixelCutoutRequest(BaseModel):
    project_root: str
    sheet_path: str
    asset_name: str
    action: str = "idle"
    direction: str = "south"
    columns: int = Field(default=5, gt=0)
    rows: int = Field(default=2, gt=0)
    cell_width: int = Field(default=256, gt=0)
    cell_height: int = Field(default=256, gt=0)
    style_id: str = "pixel_art"
    content_path: str = "/Game/UIM/Pixels"
    model_name: str = "isnet-general-use"
    mask_mode: str = "hybrid"
    decontaminate_edges: bool = True
    debug_artifacts: bool = False
    stream_session: str | None = None


class Tilemap47Request(BaseModel):
    project_root: str
    asset_name: str
    tileset_path: str
    tile_size: int = Field(default=32, gt=0)
    style_id: str = "pixel_art"
    content_path: str = "/Game/UIM/Tiles"


class TilemapSeedRequest(BaseModel):
    project_root: str
    asset_name: str
    subject: str
    standard: str = "47-tile"
    tile_size: int = Field(default=32, gt=0)
    style_id: str = "pixel_art"
    image_provider: str = "openai_api"
    content_path: str = "/Game/UIM/Tiles"
    stream_session: str | None = None


class TilemapComposeRequest(BaseModel):
    project_root: str
    asset_name: str
    seed_path: str
    subject: str = ""
    standard: str = "47-tile"
    tile_size: int = Field(default=32, gt=0)
    style_id: str = "pixel_art"
    image_provider: str = "openai_api"
    content_path: str = "/Game/UIM/Tiles"
    stream_session: str | None = None


class SeedanceWalkRequest(BaseModel):
    project_root: str
    asset_name: str
    anchor_path: str
    action: str = "walk"
    direction: str = "south"
    model: str | None = None
    resolution: str | None = None
    prompt: str
    seconds: int = Field(default=5, ge=4, le=15)
    stream_session: str | None = None


class VideoSheetRequest(BaseModel):
    project_root: str
    asset_name: str
    video_path: str
    action: str = "walk"
    direction: str = "south"
    style_id: str = "pixel_art"
    content_path: str = "/Game/UIM/Pixels"
    columns: int = Field(default=5, gt=0)
    rows: int = Field(default=2, gt=0)
    cell_size: int = Field(default=256, gt=0)
    frame_times: list[float] | None = None


class VideoDebugExportRequest(BaseModel):
    project_root: str
    asset_name: str
    video_path: str
    action: str = "walk"
    direction: str = "south"
    export_type: str = "sheet"
    style_id: str = "pixel_art"
    content_path: str = "/Game/UIM/Pixels"
    columns: int = Field(default=5, gt=0)
    rows: int = Field(default=2, gt=0)
    cell_size: int = Field(default=256, gt=0)
    frame_times: list[float]


class VideoThumbnailRequest(BaseModel):
    project_root: str
    video_path: str
    frame_times: list[float]
    thumbnail_size: int = Field(default=144, gt=0, le=512)


class UIConceptRequest(BaseModel):
    project_root: str
    asset_name: str
    game_description: str
    layout: str
    style_id: str = "semi_realistic_ui"
    image_provider: str = "openai_api"
    content_path: str = "/Game/UIM/UI"
    stream_session: str | None = None


class UIConceptImportRequest(BaseModel):
    project_root: str
    asset_name: str
    concept_path: str
    style_id: str = "semi_realistic_ui"
    content_path: str = "/Game/UIM/UI"


class UIWidgetRequest(BaseModel):
    project_root: str
    asset_name: str
    widget_type: str
    widget_description: str
    concept_path: str | None = None
    style_id: str = "semi_realistic_ui"
    image_provider: str = "openai_api"
    content_path: str = "/Game/UIM/UI"
    nine_slice: tuple[int, int, int, int] | None = None
    stream_session: str | None = None


class GameUiDslPromptRequest(BaseModel):
    width: int = Field(default=1920, gt=0)
    height: int = Field(default=1080, gt=0)


class GameUiHtmlRequest(BaseModel):
    project_root: str
    screen_name: str
    html: str


class GameUiHtmlDeleteRequest(BaseModel):
    project_root: str
    html_path: str


class GameUiBakeRequest(BaseModel):
    project_root: str
    screen_name: str
    html_path: str | None = None
    width: int = Field(default=1920, gt=0)
    height: int = Field(default=1080, gt=0)


class GameUiStructureDeleteRequest(BaseModel):
    project_root: str
    structure_path: str


class GameUiTextureKitRegisterRequest(BaseModel):
    project_root: str
    kit_name: str
    files: list[dict[str, Any]] | dict[str, Any]
    content_path: str = "/Game/UIM/UI"


class GameUiTextureKitGenerateRequest(BaseModel):
    project_root: str
    kit_name: str
    concept_path: str | None = None
    widget_tokens: list[dict[str, Any]] = Field(default_factory=list)
    provider: str = "openai_api"
    content_path: str = "/Game/UIM/UI"
    coverage: str = "default_full"
    mask_mode: str = "hybrid"
    decontaminate_edges: bool = True
    debug_artifacts: bool = False
    max_concurrency: int = Field(default=4, ge=1, le=4)
    chroma_key: tuple[int, int, int] | None = (255, 0, 255)
    stream_session: str | None = None


class GameUiExportUmgRequest(BaseModel):
    project_root: str
    screen_name: str
    structure_path: str
    texture_kit_path: str
    content_path: str = "/Game/UIM/UI"


class GameUiTextureKitClearRequest(BaseModel):
    project_root: str
    texture_kit_path: str = ""
    kit_name: str = ""


class CodexOAuthCompleteRequest(BaseModel):
    callback_input: str
    verifier: str = ""
    state: str = ""


def _runtime_settings_path() -> Path:
    return user_data_dir() / "runtime-settings.json"


def _load_saved_runtime_settings() -> dict[str, Any]:
    path = _runtime_settings_path()
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _save_runtime_settings_patch(patch: dict[str, Any]) -> None:
    saved = _load_saved_runtime_settings()
    saved.update(patch)
    write_json(_runtime_settings_path(), saved)


def _apply_saved_runtime_settings() -> None:
    saved = _load_saved_runtime_settings()
    if "networkProxy" in saved:
        set_network_proxy(str(saved.get("networkProxy") or ""))
    if saved.get("openAiApiKey") and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = str(saved["openAiApiKey"])
    if saved.get("seedanceApiKey") and not os.environ.get("UIM_SEEDANCE_API_KEY"):
        os.environ["UIM_SEEDANCE_API_KEY"] = str(saved["seedanceApiKey"])
    if saved.get("openAiBaseUrl") and not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = str(saved["openAiBaseUrl"])
    if saved.get("unrealMcpUrl") and not os.environ.get("UIM_UNREAL_MCP_URL"):
        os.environ["UIM_UNREAL_MCP_URL"] = str(saved["unrealMcpUrl"])
    if saved.get("seedanceEndpoint") and not os.environ.get("UIM_SEEDANCE_ENDPOINT"):
        os.environ["UIM_SEEDANCE_ENDPOINT"] = str(saved["seedanceEndpoint"])
    if saved.get("seedanceModel") and not os.environ.get("UIM_SEEDANCE_MODEL"):
        os.environ["UIM_SEEDANCE_MODEL"] = normalize_seedance_model(str(saved["seedanceModel"]))
    if saved.get("seedanceResolution") and not os.environ.get("UIM_SEEDANCE_RESOLUTION"):
        os.environ["UIM_SEEDANCE_RESOLUTION"] = str(saved["seedanceResolution"])


_apply_saved_runtime_settings()


def _remember_current_project(project_root: str | Path) -> None:
    root = Path(project_root)
    if not (root / PROJECT_FILE).exists():
        return
    try:
        save_current_project_root(root)
    except Exception as exc:
        logging.warning("Failed to update current project pointer for MCP: %s", exc)


def _runtime_settings() -> dict[str, Any]:
    proxy = configured_network_proxy()
    seedance = SeedanceProvider()
    return {
        "workspaceRoot": str(workspace_root()),
        "modelCacheDir": str(model_cache_dir()),
        "hasOpenAiApiKey": bool(os.environ.get("OPENAI_API_KEY")),
        "openAiBaseUrl": os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        "unrealMcpUrl": os.environ.get("UIM_UNREAL_MCP_URL", ""),
        "hasHuggingFaceToken": bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")),
        "networkProxy": proxy,
        "codexOAuth": codex_oauth_status(),
        "hasSeedanceApiKey": bool(os.environ.get("UIM_SEEDANCE_API_KEY")),
        "seedanceEndpoint": os.environ.get("UIM_SEEDANCE_ENDPOINT", DEFAULT_SEEDANCE_ENDPOINT),
        "seedanceModel": normalize_seedance_model(os.environ.get("UIM_SEEDANCE_MODEL")),
        "seedanceResolution": os.environ.get("UIM_SEEDANCE_RESOLUTION", DEFAULT_SEEDANCE_RESOLUTION),
        "seedanceConfigured": seedance.is_configured(),
    }


def _project_path(project_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "appVersion": APP_VERSION,
        "apiContractVersion": API_CONTRACT_VERSION,
        "capabilities": {"codexOAuthCallback": "fixed-loopback-manual-fallback", "openAiBaseUrl": True, "bundledVideoFfmpeg": True, "videoThumbnails": True, "gameUiMcp": True},
    }


@app.get("/events/stream/{session_id}")
def api_stream_events(session_id: str, after: int = 0) -> dict[str, Any]:
    with _stream_lock:
        events = list(_stream_sessions.get(session_id, []))
    start = max(0, after)
    return {
        "session": session_id,
        "next": len(events),
        "events": [{"index": index, "message": message} for index, message in enumerate(events[start:], start)],
    }


@app.delete("/events/stream/{session_id}")
def api_delete_stream_events(session_id: str) -> dict[str, Any]:
    with _stream_lock:
        _stream_sessions.pop(session_id, None)
        _stream_cancelled.discard(session_id)
    return {"deleted": True}


@app.post("/events/stream/{session_id}/cancel")
def api_cancel_stream_events(session_id: str) -> dict[str, Any]:
    with _stream_lock:
        _stream_sessions.setdefault(session_id, [])
        _stream_cancelled.add(session_id)
    _append_stream_event(session_id, "task.cancel.requested")
    return {"cancelled": True}


@app.get("/settings/runtime")
def api_runtime_settings() -> dict[str, Any]:
    return _runtime_settings()


@app.post("/settings/runtime")
def api_update_runtime_settings(request: RuntimeSettingsRequest) -> dict[str, Any]:
    if request.openai_api_key:
        value = request.openai_api_key.strip()
        os.environ["OPENAI_API_KEY"] = value
        _save_runtime_settings_patch({"openAiApiKey": value})
    if request.openai_base_url is not None:
        value = request.openai_base_url.strip().rstrip("/")
        if value:
            os.environ["OPENAI_BASE_URL"] = value
        else:
            os.environ.pop("OPENAI_BASE_URL", None)
        _save_runtime_settings_patch({"openAiBaseUrl": value})
    if request.unreal_mcp_url is not None:
        value = request.unreal_mcp_url.strip()
        if value:
            os.environ["UIM_UNREAL_MCP_URL"] = value
        else:
            os.environ.pop("UIM_UNREAL_MCP_URL", None)
        _save_runtime_settings_patch({"unrealMcpUrl": value})
    if request.huggingface_token:
        os.environ["HF_TOKEN"] = request.huggingface_token
    if request.network_proxy is not None:
        set_network_proxy(request.network_proxy)
        _save_runtime_settings_patch({"networkProxy": request.network_proxy.strip()})
    if request.seedance_api_key:
        value = request.seedance_api_key.strip()
        os.environ["UIM_SEEDANCE_API_KEY"] = value
        _save_runtime_settings_patch({"seedanceApiKey": value})
    if request.seedance_endpoint is not None:
        value = request.seedance_endpoint.strip()
        if value:
            os.environ["UIM_SEEDANCE_ENDPOINT"] = value
        else:
            os.environ.pop("UIM_SEEDANCE_ENDPOINT", None)
        _save_runtime_settings_patch({"seedanceEndpoint": value})
    if request.seedance_model is not None:
        raw_value = request.seedance_model.strip()
        value = normalize_seedance_model(raw_value) if raw_value else ""
        if value:
            os.environ["UIM_SEEDANCE_MODEL"] = value
        else:
            os.environ.pop("UIM_SEEDANCE_MODEL", None)
        _save_runtime_settings_patch({"seedanceModel": value})
    if request.seedance_resolution is not None:
        value = request.seedance_resolution.strip() or DEFAULT_SEEDANCE_RESOLUTION
        os.environ["UIM_SEEDANCE_RESOLUTION"] = value
        _save_runtime_settings_patch({"seedanceResolution": value})
    return _runtime_settings()


@app.get("/settings/network-check")
def api_network_check() -> dict[str, Any]:
    request = urllib.request.Request(
        "https://auth.openai.com/oauth/authorize",
        headers={"Accept": "text/html,application/json"},
        method="GET",
    )
    try:
        with open_external_url(request, timeout=15) as response:
            return {
                "reachable": True,
                "proxy": configured_network_proxy(),
                "status": response.status,
                "detail": "OpenAI auth endpoint is reachable.",
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": True,
            "proxy": configured_network_proxy(),
            "status": exc.code,
            "detail": "OpenAI auth endpoint responded; network path is reachable.",
        }
    except Exception as exc:
        return {
            "reachable": False,
            "proxy": configured_network_proxy(),
            "status": 0,
            "detail": str(exc),
        }


@app.get("/auth/codex/status")
def api_codex_oauth_status() -> dict[str, Any]:
    return codex_oauth_status()


@app.post("/auth/codex/start")
def api_codex_oauth_start() -> dict[str, Any]:
    redirect_uri = _codex_oauth_redirect_uri()
    server: ThreadingHTTPServer | None = None
    auto_callback = True
    message = "等待浏览器授权，授权完成后会自动回到 UnrealImageMaker。"
    try:
        server = _create_codex_oauth_callback_server()
    except RuntimeError as exc:
        auto_callback = False
        message = f"{exc}。请继续在浏览器完成授权，然后把最终跳转到 localhost:1455 的完整网址粘贴回软件。"
    flow = create_pkce_flow(redirect_uri)
    _register_codex_oauth_flow(flow, server, message)
    return {
        "state": flow["state"],
        "challenge": flow["challenge"],
        "authorize_url": flow["authorize_url"],
        "redirect_uri": flow["redirect_uri"],
        "auto_callback": auto_callback,
        "message": message,
    }


@app.get("/auth/codex/poll/{state}")
def api_codex_oauth_poll(state: str) -> dict[str, Any]:
    with _codex_oauth_lock:
        current = _codex_oauth_pending.get(state, {}).copy()
    if not current:
        raise HTTPException(status_code=404, detail="OAuth flow is not active")
    if current.get("status") == "pending" and float(current.get("expiresAt") or 0) < time.time():
        _set_oauth_result(state, "error", "OAuth 会话已过期，请重新开始绑定。")
        _shutdown_codex_oauth_callback_server(state)
        with _codex_oauth_lock:
            current = _codex_oauth_pending.get(state, {}).copy()
    return _oauth_poll_response(state, current)


@app.post("/auth/codex/complete")
def api_codex_oauth_complete(request: CodexOAuthCompleteRequest) -> dict[str, Any]:
    verifier = request.verifier
    redirect_uri: str | None = None
    if request.state:
        with _codex_oauth_lock:
            pending = _codex_oauth_pending.get(request.state, {}).copy()
        verifier = verifier or str(pending.get("verifier") or "")
        redirect_uri = str(pending.get("redirectUri") or "") or None
    try:
        tokens = complete_codex_oauth(request.callback_input, verifier, request.state, redirect_uri)
    except Exception as exc:
        _set_oauth_result(request.state, "error", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status = safe_token_status(tokens)
    _set_oauth_result(request.state, "success", "ChatGPT 订阅账号已绑定。", status)
    _shutdown_codex_oauth_callback_server(request.state)
    return status


@app.post("/auth/codex/refresh")
def api_codex_oauth_refresh() -> dict[str, Any]:
    try:
        tokens = refresh_codex_oauth_tokens()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return safe_token_status(tokens)


@app.post("/auth/codex/disconnect")
def api_codex_oauth_disconnect() -> dict[str, Any]:
    delete_codex_oauth_tokens()
    return codex_oauth_status()


@app.post("/projects")
def api_create_project(request: CreateProjectRequest) -> dict[str, Any]:
    try:
        project = create_project(Path(request.root), request.name, request.overwrite)
        _remember_current_project(request.root)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return project.to_dict()


@app.post("/projects/open")
def api_open_project(request: ProjectRequest) -> dict[str, Any]:
    root = Path(request.root)
    try:
        project = load_project(root)
        _remember_current_project(root)
        locked = load_models_lock(models_lock_path(root))
        missing = missing_locked_models(model_cache_dir(), locked)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "project": project.to_dict(),
        "lockedModels": [asdict(model) for model in locked],
        "missingModels": [asdict(model) for model in missing],
    }


@app.get("/projects/assets")
def api_list_project_assets(project_root: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    _remember_current_project(root)
    asset_dirs = sorted((root / "assets").glob("*"), key=lambda path: path.stat().st_mtime, reverse=True) if (root / "assets").exists() else []
    assets: list[dict[str, Any]] = []
    for asset_dir in asset_dirs:
        if not asset_dir.is_dir():
            continue
        asset_id = asset_dir.name
        manifest_path = asset_dir / "manifests" / "manifest.json"
        manifest: dict[str, Any] = {}
        try:
            if manifest_path.exists():
                manifest = read_json(manifest_path)
        except Exception:
            manifest = {}
        display_name = str(manifest.get("displayName") or asset_id)
        index = load_asset_index(root, asset_id, display_name)
        if not index.versions and manifest:
            files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
            for file in files:
                if isinstance(file, dict) and file.get("path"):
                    role = str(file.get("role") or "image")
                    try:
                        index = register_asset_version(root, display_name, str(file["path"]), role, role, asset_id=asset_id)
                    except Exception:
                        continue
        primary = primary_version(index)
        if primary:
            sync_texture_manifest_primary(root, index.asset_id)
            if manifest_path.exists():
                try:
                    manifest = read_json(manifest_path)
                except Exception:
                    pass
        assets.append(asset_index_to_record(root, index, manifest))
    return {"assets": assets}


@app.get("/projects/workspace")
def api_project_workspace(project_root: str) -> dict[str, Any]:
    _remember_current_project(project_root)
    return load_project_workspace(Path(project_root))


@app.put("/projects/workspace/queue")
def api_update_processing_queue(request: ProcessingQueueRequest) -> dict[str, Any]:
    return save_processing_queue(Path(request.project_root), request.queue)


@app.put("/projects/workspace/slots")
def api_update_workflow_slots(request: WorkflowSlotsRequest) -> dict[str, Any]:
    return save_workflow_slots(Path(request.project_root), request.workflow_slots)


@app.put("/assets/{asset_id}/settings")
def api_update_asset_settings(asset_id: str, request: AssetSettingsRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        index = load_asset_index(root, asset_id, request.display_name or asset_id)
        if request.display_name:
            index.display_name = request.display_name
        index.settings = {**index.settings, **request.settings}
        save_asset_index(root, index)
        manifest_path = root / "assets" / asset_id / "manifests" / "manifest.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {}
        return asset_index_to_record(root, index, manifest)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/assets/images/register")
def api_register_asset_image(request: AssetImageRegisterRequest) -> dict[str, Any]:
    try:
        index = register_asset_version(
            Path(request.project_root),
            request.asset_name,
            request.image_path,
            request.role,
            request.label,
            asset_id=asset_id_from_name(request.asset_name),
        )
        return sync_asset_and_record(Path(request.project_root), index)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/assets/{asset_id}/versions/order")
def api_reorder_asset_versions(asset_id: str, request: AssetVersionOrderRequest) -> dict[str, Any]:
    try:
        index = reorder_asset_versions(Path(request.project_root), asset_id, request.version_ids)
        return sync_asset_and_record(Path(request.project_root), index)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/assets/{asset_id}/versions/{version_id}")
def api_delete_asset_version(asset_id: str, version_id: str, project_root: str) -> dict[str, Any]:
    try:
        index = delete_asset_version(Path(project_root), asset_id, version_id)
        return sync_asset_and_record(Path(project_root), index)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/assets/{asset_id}")
def api_delete_asset(asset_id: str, project_root: str) -> dict[str, Any]:
    try:
        delete_asset(Path(project_root), asset_id)
        return {"deleted": asset_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/models")
def api_list_models(cache_root: str | None = None) -> dict[str, Any]:
    cache = Path(cache_root) if cache_root else model_cache_dir()
    return {
        "cacheDir": str(cache),
        "dependencies": [item.to_dict() for item in pixel_dependency_statuses()],
        "models": [
            {
                **asdict(spec),
                "status": model_status(cache, spec.id),
                "local_path": str((cache / spec.id.replace(":", "_")).resolve()),
            }
            for spec in MODEL_REGISTRY.values()
        ],
    }


@app.post("/models/install-marker")
def api_install_marker(request: ModelActionRequest) -> dict[str, Any]:
    cache = Path(request.cache_root) if request.cache_root else model_cache_dir()
    spec = MODEL_REGISTRY.get(request.model_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown model: {request.model_id}")
    marker = install_marker(cache, spec)
    return {"status": model_status(cache, request.model_id), "marker": str(marker)}


@app.post("/models/delete")
def api_delete_model(request: ModelActionRequest) -> dict[str, Any]:
    cache = Path(request.cache_root) if request.cache_root else model_cache_dir()
    if request.model_id not in MODEL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown model: {request.model_id}")
    try:
        deleted = delete_model(cache, request.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": deleted}


@app.post("/models/lock")
def api_lock_model(request: ModelActionRequest) -> dict[str, Any]:
    if not request.cache_root:
        raise HTTPException(status_code=400, detail="cache_root must be the .uim project root for lock writes")
    locked = lock_model(models_lock_path(Path(request.cache_root)), request.model_id)
    return asdict(locked)


@app.post("/rembg/remove")
def api_rembg_remove(request: RembgRequest) -> dict[str, Any]:
    adapter = RembgAdapter(request.model_name)
    result = adapter.remove_background(Path(request.input_path), Path(request.output_path))
    data = asdict(result)
    data["output_path"] = str(data["output_path"])
    return data


@app.post("/sam/download")
def api_sam_download(request: SamDownloadRequest) -> dict[str, Any]:
    cache = Path(request.cache_root) if request.cache_root else model_cache_dir()
    adapter = Sam21Adapter(cache, request.model_id)
    checkpoint = adapter.download_checkpoint()
    return {"checkpoint": str(checkpoint), "status": adapter.status()}


@app.post("/sam/segment")
def api_sam_segment(request: SamSegmentRequest) -> dict[str, Any]:
    cache = Path(request.cache_root) if request.cache_root else model_cache_dir()
    adapter = Sam21Adapter(cache, request.model_id)
    output = adapter.segment(
        Path(request.image_path),
        Path(request.output_mask_path),
        SamPrompt(points=request.points, labels=request.labels, box=request.box),
    )
    return {"mask": str(output)}


@app.post("/image/process")
def api_image_process(request: ImageProcessRequest) -> dict[str, Any]:
    input_path = Path(request.input_path)
    output_path = Path(request.output_path)
    if request.operation == "trim":
        bounds = trim_transparent(input_path, output_path, request.padding)
        return {"bounds": bounds.to_dict() if bounds else None}
    if request.operation == "clean_alpha":
        clean_alpha_halo(input_path, output_path)
        return {"output": str(output_path)}
    if request.operation == "nearest_scale":
        nearest_scale(input_path, output_path, request.scale)
        return {"output": str(output_path)}
    if request.operation == "quantize_palette":
        quantize_palette(input_path, output_path, request.colors)
        return {"output": str(output_path)}
    raise HTTPException(status_code=400, detail=f"Unknown operation: {request.operation}")


@app.post("/assets/sprite")
def api_create_sprite(request: SpriteAssetRequest) -> dict[str, Any]:
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_sprite_asset(
                project_root=Path(request.project_root),
                prompt=request.prompt,
                style_id=request.style_id,
                asset_name=request.asset_name,
                content_path=request.content_path,
                image_provider=request.image_provider,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "assets/sprite",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.get("/specialized/pixel/presets")
def api_pixel_presets() -> dict[str, Any]:
    return {
        "characterDirections": CHARACTER_DIRECTIONS_8,
        "generatedCharacterDirections": CHARACTER_GENERATED_DIRECTIONS,
        "mirroredCharacterDirections": CHARACTER_MIRRORED_DIRECTIONS,
        "tilemap47": TILEMAP_47_IDS,
        "tilemapDualGrid16": TILEMAP_DUAL_GRID_16_IDS,
    }


@app.post("/specialized/pixel/concept")
def api_pixel_concept(request: PixelConceptRequest) -> dict[str, Any]:
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_pixel_concept(
                project_root=Path(request.project_root),
                asset_name=request.asset_name,
                subject=request.subject,
                asset_kind=request.asset_kind,
                style_id=request.style_id,
                image_provider=request.image_provider,
                content_path=request.content_path,
                output_size=request.output_size,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "specialized/pixel/concept",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            asset_kind=request.asset_kind,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.post("/specialized/pixel/anchor")
def api_pixel_anchor(request: PixelAnchorRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_pixel_anchor(
                project_root=root,
                asset_name=request.asset_name,
                subject=request.subject,
                asset_kind=request.asset_kind,
                direction=request.direction,
                style_id=request.style_id,
                image_provider=request.image_provider,
                content_path=request.content_path,
                concept_path=_project_path(root, request.concept_path),
                reference_anchor_path=_project_path(root, request.reference_anchor_path),
                anchor_stage=request.anchor_stage,
                dynamic_effect=request.dynamic_effect,
                logical_frame_size=request.logical_frame_size,
                output_size=request.output_size,
                mirror_from=request.mirror_from,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "specialized/pixel/anchor",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            asset_kind=request.asset_kind,
            direction=request.direction,
            anchor_stage=request.anchor_stage,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.post("/specialized/pixel/sheet")
def api_pixel_sheet(request: PixelSheetRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_animation_sheet(
                project_root=root,
                asset_name=request.asset_name,
                subject=request.subject,
                asset_kind=request.asset_kind,
                action=request.action,
                direction=request.direction,
                style_id=request.style_id,
                image_provider=request.image_provider,
                content_path=request.content_path,
                columns=request.columns,
                rows=request.rows,
                cell_size=request.cell_size,
                reference_path=_project_path(root, request.reference_path),
                attack_name=request.attack_name,
                effect_color=request.effect_color,
                projectile_or_effect=request.projectile_or_effect,
                action_description=request.action_description,
                mirror_from=request.mirror_from,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "specialized/pixel/sheet",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            asset_kind=request.asset_kind,
            action=request.action,
            direction=request.direction,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.post("/specialized/pixel/sheet-import")
def api_pixel_sheet_import(request: PixelSheetImportRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = import_animation_sheet(
            project_root=root,
            asset_name=request.asset_name,
            source_path=_project_path(root, request.sheet_path) or Path(request.sheet_path),
            asset_kind=request.asset_kind,
            action=request.action,
            direction=request.direction,
            style_id=request.style_id,
            content_path=request.content_path,
            columns=request.columns,
            rows=request.rows,
            cell_size=request.cell_size,
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/sheet-import", exc, project_root=request.project_root, asset_name=request.asset_name, sheet_path=request.sheet_path)
    return manifest.to_dict()


@app.post("/specialized/pixel/normalize")
def api_pixel_normalize(request: PixelNormalizeRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: normalize_spritesheet(
                project_root=root,
                sheet_path=_project_path(root, request.sheet_path) or Path(request.sheet_path),
                asset_name=request.asset_name,
                action=request.action,
                columns=request.columns,
                rows=request.rows,
                cell_width=request.cell_width,
                cell_height=request.cell_height,
                style_id=request.style_id,
                content_path=request.content_path,
                chroma_key=request.chroma_key,
                direction=request.direction,
                pixel_restore_mode=request.pixel_restore_mode,
                source_cell_width=request.source_cell_width,
                source_cell_height=request.source_cell_height,
                progress=lambda event: _append_stream_event(request.stream_session or "", event),
                is_cancelled=lambda: _is_stream_cancelled(request.stream_session),
            ),
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/normalize", exc, project_root=request.project_root, asset_name=request.asset_name, action=request.action)
    return manifest.to_dict()


@app.post("/specialized/pixel/cutout")
def api_pixel_cutout(request: PixelCutoutRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_spritesheet_cutout(
                project_root=root,
                sheet_path=_project_path(root, request.sheet_path) or Path(request.sheet_path),
                asset_name=request.asset_name,
                action=request.action,
                direction=request.direction,
                columns=request.columns,
                rows=request.rows,
                cell_width=request.cell_width,
                cell_height=request.cell_height,
                style_id=request.style_id,
                content_path=request.content_path,
                model_name=request.model_name,
                mask_mode=request.mask_mode,
                decontaminate_edges=request.decontaminate_edges,
                debug_artifacts=request.debug_artifacts,
                progress=lambda event: _append_stream_event(request.stream_session or "", event),
            ),
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/cutout", exc, project_root=request.project_root, asset_name=request.asset_name, action=request.action, direction=request.direction, sheet_path=request.sheet_path)
    return manifest.to_dict()


@app.post("/specialized/pixel/tilemap-seed")
def api_tilemap_seed(request: TilemapSeedRequest) -> dict[str, Any]:
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_tilemap_seed_concept(
                project_root=Path(request.project_root),
                asset_name=request.asset_name,
                subject=request.subject,
                standard=request.standard,
                tile_size=request.tile_size,
                style_id=request.style_id,
                image_provider=request.image_provider,
                content_path=request.content_path,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "specialized/pixel/tilemap-seed",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            standard=request.standard,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.post("/specialized/pixel/tilemap-compose")
def api_tilemap_compose(request: TilemapComposeRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_tilemap_from_seed_manifest(
                project_root=root,
                asset_name=request.asset_name,
                seed_path=_project_path(root, request.seed_path) or Path(request.seed_path),
                subject=request.subject,
                standard=request.standard,
                tile_size=request.tile_size,
                style_id=request.style_id,
                image_provider=request.image_provider,
                content_path=request.content_path,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "specialized/pixel/tilemap-compose",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            standard=request.standard,
            seed_path=request.seed_path,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.post("/specialized/pixel/tilemap-47")
def api_tilemap_47(request: Tilemap47Request) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = create_tilemap_47_manifest(
            project_root=root,
            asset_name=request.asset_name,
            tileset_path=_project_path(root, request.tileset_path) or Path(request.tileset_path),
            tile_size=request.tile_size,
            style_id=request.style_id,
            content_path=request.content_path,
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/tilemap-47", exc, project_root=request.project_root, asset_name=request.asset_name, tileset_path=request.tileset_path)
    return manifest.to_dict()


@app.post("/specialized/pixel/tilemap-dual-grid")
def api_tilemap_dual_grid(request: Tilemap47Request) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = create_tilemap_dual_grid_manifest(
            project_root=root,
            asset_name=request.asset_name,
            tileset_path=_project_path(root, request.tileset_path) or Path(request.tileset_path),
            tile_size=request.tile_size,
            style_id=request.style_id,
            content_path=request.content_path,
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/tilemap-dual-grid", exc, project_root=request.project_root, asset_name=request.asset_name, tileset_path=request.tileset_path)
    return manifest.to_dict()


@app.post("/specialized/pixel/seedance-walk")
def api_seedance_walk(request: SeedanceWalkRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        return _run_with_stream_session(
            request.stream_session,
            lambda: create_seedance_walk_video(
                project_root=root,
                asset_name=request.asset_name,
                anchor_path=_project_path(root, request.anchor_path) or Path(request.anchor_path),
                direction=request.direction,
                model=request.model,
                resolution=request.resolution,
                prompt=request.prompt,
                seconds=request.seconds,
                action=request.action,
                progress=lambda event: _append_stream_event(request.stream_session or "", event),
                is_cancelled=lambda: _is_stream_cancelled(request.stream_session),
            ),
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/seedance-walk", exc, project_root=request.project_root, asset_name=request.asset_name, action=request.action, direction=request.direction)


@app.post("/specialized/pixel/video-sheet")
def api_video_sheet(request: VideoSheetRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = create_spritesheet_from_video(
            project_root=root,
            asset_name=request.asset_name,
            video_path=_project_path(root, request.video_path) or Path(request.video_path),
            action=request.action,
            direction=request.direction,
            columns=request.columns,
            rows=request.rows,
            cell_size=request.cell_size,
            style_id=request.style_id,
            content_path=request.content_path,
            frame_times=request.frame_times,
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/video-sheet", exc, project_root=request.project_root, asset_name=request.asset_name, action=request.action, direction=request.direction, video_path=request.video_path)
    return manifest.to_dict()


@app.post("/specialized/pixel/video-debug-export")
def api_video_debug_export(request: VideoDebugExportRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = create_video_debug_export(
            project_root=root,
            asset_name=request.asset_name,
            video_path=_project_path(root, request.video_path) or Path(request.video_path),
            action=request.action,
            direction=request.direction,
            export_type=request.export_type,
            columns=request.columns,
            rows=request.rows,
            cell_size=request.cell_size,
            style_id=request.style_id,
            content_path=request.content_path,
            frame_times=request.frame_times,
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/video-debug-export", exc, project_root=request.project_root, asset_name=request.asset_name, action=request.action, direction=request.direction, video_path=request.video_path)
    return manifest.to_dict()


@app.post("/specialized/pixel/video-thumbnails")
def api_video_thumbnails(request: VideoThumbnailRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        return extract_video_frame_thumbnails(
            video_path=_project_path(root, request.video_path) or Path(request.video_path),
            frame_times=request.frame_times,
            thumbnail_size=request.thumbnail_size,
        )
    except Exception as exc:
        _raise_bad_request("specialized/pixel/video-thumbnails", exc, project_root=request.project_root, video_path=request.video_path)


@app.post("/specialized/ui/concept")
def api_ui_concept(request: UIConceptRequest) -> dict[str, Any]:
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_ui_concept(
                project_root=Path(request.project_root),
                asset_name=request.asset_name,
                game_description=request.game_description,
                layout=request.layout,
                style_id=request.style_id,
                image_provider=request.image_provider,
                content_path=request.content_path,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "specialized/ui/concept",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.post("/specialized/ui/concept-import")
def api_ui_concept_import(request: UIConceptImportRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = import_ui_concept(
            project_root=root,
            asset_name=request.asset_name,
            source_path=_project_path(root, request.concept_path) or Path(request.concept_path),
            style_id=request.style_id,
            content_path=request.content_path,
        )
    except Exception as exc:
        _raise_bad_request("specialized/ui/concept-import", exc, project_root=request.project_root, asset_name=request.asset_name, concept_path=request.concept_path)
    return manifest.to_dict()


@app.post("/specialized/ui/widget")
def api_ui_widget(request: UIWidgetRequest) -> dict[str, Any]:
    root = Path(request.project_root)
    try:
        manifest = _run_with_stream_session(
            request.stream_session,
            lambda: create_ui_widget(
                project_root=root,
                asset_name=request.asset_name,
                widget_type=request.widget_type,
                widget_description=request.widget_description,
                concept_path=_project_path(root, request.concept_path),
                style_id=request.style_id,
                image_provider=request.image_provider,
                content_path=request.content_path,
                nine_slice=request.nine_slice,
            ),
        )
    except Exception as exc:
        _raise_bad_request(
            "specialized/ui/widget",
            exc,
            project_root=request.project_root,
            asset_name=request.asset_name,
            widget_type=request.widget_type,
            image_provider=request.image_provider,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )
    return manifest.to_dict()


@app.get("/game-ui/dsl-prompt")
def api_game_ui_dsl_prompt(width: int = 1920, height: int = 1080, project_root: str = "") -> dict[str, Any]:
    try:
        if project_root:
            _remember_current_project(project_root)
        workflow = mcp_game_ui.game_ui_html_write_workflow(project_root, width, height) if project_root else None
        return {"prompt": game_ui_dsl_prompt(width, height, project_root or None), "width": width, "height": height, "writeWorkflow": workflow}
    except Exception as exc:
        _raise_bad_request("game-ui/dsl-prompt", exc, width=width, height=height, project_root=project_root)


@app.post("/game-ui/html")
def api_game_ui_write_html(request: GameUiHtmlRequest) -> dict[str, Any]:
    try:
        return write_game_ui_html(Path(request.project_root), request.screen_name, request.html)
    except Exception as exc:
        _raise_bad_request("game-ui/html", exc, project_root=request.project_root, screen_name=request.screen_name)


@app.get("/game-ui/html-prototypes")
def api_game_ui_html_prototypes(project_root: str) -> dict[str, Any]:
    try:
        return list_game_ui_html_prototypes(Path(project_root))
    except Exception as exc:
        _raise_bad_request("game-ui/html-prototypes", exc, project_root=project_root)


@app.get("/game-ui/html-content")
def api_game_ui_html_content(project_root: str, html_path: str) -> dict[str, Any]:
    try:
        return read_game_ui_html(Path(project_root), html_path)
    except Exception as exc:
        _raise_bad_request("game-ui/html-content", exc, project_root=project_root, html_path=html_path)


@app.post("/game-ui/html/delete")
def api_game_ui_delete_html(request: GameUiHtmlDeleteRequest) -> dict[str, Any]:
    try:
        return delete_game_ui_html(Path(request.project_root), request.html_path)
    except Exception as exc:
        _raise_bad_request("game-ui/html/delete", exc, project_root=request.project_root, html_path=request.html_path)


@app.post("/game-ui/bake-html")
def api_game_ui_bake_html(request: GameUiBakeRequest) -> dict[str, Any]:
    try:
        return bake_game_ui_html(Path(request.project_root), request.screen_name, request.html_path, request.width, request.height)
    except Exception as exc:
        _raise_bad_request("game-ui/bake-html", exc, project_root=request.project_root, screen_name=request.screen_name, html_path=request.html_path)


@app.get("/game-ui/structures")
def api_game_ui_structures(project_root: str) -> dict[str, Any]:
    try:
        return list_game_ui_structures(Path(project_root))
    except Exception as exc:
        _raise_bad_request("game-ui/structures", exc, project_root=project_root)


@app.post("/game-ui/structure/delete")
def api_game_ui_delete_structure(request: GameUiStructureDeleteRequest) -> dict[str, Any]:
    try:
        return delete_game_ui_structure(Path(request.project_root), request.structure_path)
    except Exception as exc:
        _raise_bad_request("game-ui/structure/delete", exc, project_root=request.project_root, structure_path=request.structure_path)


@app.get("/game-ui/texture-kits")
def api_game_ui_texture_kits(project_root: str) -> dict[str, Any]:
    try:
        return list_texture_kits(Path(project_root))
    except Exception as exc:
        _raise_bad_request("game-ui/texture-kits", exc, project_root=project_root)


@app.post("/game-ui/texture-kit/register")
def api_game_ui_register_texture_kit(request: GameUiTextureKitRegisterRequest) -> dict[str, Any]:
    try:
        return register_texture_kit(Path(request.project_root), request.kit_name, request.files, request.content_path)
    except Exception as exc:
        _raise_bad_request("game-ui/texture-kit/register", exc, project_root=request.project_root, kit_name=request.kit_name)


@app.post("/game-ui/texture-kit/generate")
def api_game_ui_generate_texture_kit(request: GameUiTextureKitGenerateRequest) -> dict[str, Any]:
    try:
        return _run_with_stream_session(
            request.stream_session,
            lambda: generate_texture_kit(
                Path(request.project_root),
                request.kit_name,
                request.concept_path,
                request.widget_tokens,
                request.provider,
                request.content_path,
                coverage=request.coverage,
                mask_mode=request.mask_mode,
                decontaminate_edges=request.decontaminate_edges,
                debug_artifacts=request.debug_artifacts,
                max_concurrency=request.max_concurrency,
                chroma_key=request.chroma_key,
                progress=lambda event: _append_stream_event(request.stream_session or "", event),
            ),
        )
    except Exception as exc:
        _raise_bad_request("game-ui/texture-kit/generate", exc, project_root=request.project_root, kit_name=request.kit_name)


@app.post("/game-ui/texture-kit/clear")
def api_game_ui_clear_texture_kit(request: GameUiTextureKitClearRequest) -> dict[str, Any]:
    try:
        return clear_texture_kit(Path(request.project_root), request.texture_kit_path, request.kit_name)
    except Exception as exc:
        _raise_bad_request("game-ui/texture-kit/clear", exc, project_root=request.project_root, texture_kit_path=request.texture_kit_path, kit_name=request.kit_name)


@app.post("/game-ui/export-umg")
def api_game_ui_export_umg(request: GameUiExportUmgRequest) -> dict[str, Any]:
    try:
        return export_game_ui_umg(Path(request.project_root), request.screen_name, request.structure_path, request.texture_kit_path, request.content_path)
    except Exception as exc:
        _raise_bad_request("game-ui/export-umg", exc, project_root=request.project_root, screen_name=request.screen_name)


@app.get("/game-ui/preview-data")
def api_game_ui_preview_data(project_root: str, structure_path: str, texture_kit_path: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    try:
        structure_file = _project_path(root, structure_path)
        kit_file = _project_path(root, texture_kit_path)
        if structure_file is None or not structure_file.exists() or not structure_file.is_file():
            raise ValueError(f"UI structure JSON does not exist: {structure_path}")
        if kit_file is None or not kit_file.exists() or not kit_file.is_file():
            raise ValueError(f"UI texture kit does not exist: {texture_kit_path}")
        structure_file.relative_to(root)
        kit_file.relative_to(root)
        return {
            "structure": read_json(structure_file),
            "textureKit": read_json(kit_file),
            "structurePath": structure_file.resolve().relative_to(root).as_posix(),
            "textureKitPath": kit_file.resolve().relative_to(root).as_posix(),
        }
    except Exception as exc:
        _raise_bad_request("game-ui/preview-data", exc, project_root=project_root, structure_path=structure_path, texture_kit_path=texture_kit_path)


@app.get("/assets/preview")
def api_asset_preview(project_root: str, path: str) -> FileResponse:
    root = Path(project_root).resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="preview path must stay inside project_root") from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Preview file not found: {path}")
    return FileResponse(target)


@app.post("/manifests/spritesheet")
def api_spritesheet(request: SpritesheetRequest) -> dict[str, Any]:
    manifest = create_spritesheet_manifest(
        project_root=Path(request.project_root),
        sheet_path=Path(request.sheet_path),
        asset_name=request.asset_name,
        style_id=request.style_id,
        cell_width=request.cell_width,
        cell_height=request.cell_height,
        content_path=request.content_path,
    )
    return manifest.to_dict()


@app.post("/manifests/ui-kit")
def api_ui_kit(request: UIKitRequest) -> dict[str, Any]:
    manifest = create_ui_kit_manifest(
        project_root=Path(request.project_root),
        asset_name=request.asset_name,
        style_id=request.style_id,
        state_files={key: Path(value) for key, value in request.state_files.items()},
        nine_slice=request.nine_slice,
        content_path=request.content_path,
    )
    return manifest.to_dict()


@app.post("/manifests/validate")
def api_validate_manifest(request: ManifestRequest) -> dict[str, Any]:
    project_root = Path(request.project_root)
    manifest = AssetManifest.from_dict(request.manifest)
    issues = [
        *validate_asset_manifest(manifest),
        *validate_file_exists(project_root, manifest),
        *validate_frame_consistency(manifest),
    ]
    return {"errors": validate_manifest(manifest), "issues": [asdict(issue) for issue in issues]}


@app.post("/unreal/python-script")
def api_unreal_script(request: ManifestRequest) -> dict[str, Any]:
    project_root = Path(request.project_root)
    manifest = AssetManifest.from_dict(request.manifest)
    output_path = Path(request.output_path) if request.output_path else project_root / "exports" / "unreal" / f"{manifest.asset_id}_import.py"
    try:
        output_path.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="output_path must stay inside project_root") from exc
    script = generate_import_script(manifest, project_root, output_path)
    return {"script": str(script), "summary": unreal_export_summary(manifest)}


@app.get("/unreal/mcp/status")
def api_unreal_mcp_status() -> dict[str, Any]:
    return asdict(UnrealMcpBridge().status())


def main() -> None:
    import uvicorn

    uvicorn.run("uim_core.api:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
