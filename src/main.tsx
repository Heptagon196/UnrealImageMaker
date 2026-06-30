import React, { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Command } from "cmdk";
import { invoke } from "@tauri-apps/api/core";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  Box,
  CheckCircle2,
  Check,
  ChevronDown,
  Cpu,
  FileImage,
  Layers,
  RefreshCw,
  Settings
} from "lucide-react";
import "./styles.css";
import { AppContext } from "./AppContext";

const PixelPage = lazy(() => import("./pages/PixelPage"));
const GameUiPage = lazy(() => import("./pages/GameUiPage"));
const ModelsPage = lazy(() => import("./pages/ModelsPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const AssetsPage = lazy(() => import("./pages/AssetsPage"));
const ExportPage = lazy(() => import("./pages/ExportPage"));
const ProjectSidebar = lazy(() => import("./components/ProjectSidebar"));
const RightPanel = lazy(() => import("./components/RightPanel"));
const AssetPreviewPanel = lazy(() => import("./components/AssetPreviewPanel"));
const AppDialogs = lazy(() => import("./dialogs/AppDialogs"));

const API_BASE = "http://127.0.0.1:8765";
const EXPECTED_API_CONTRACT_VERSION = "uim-api-2026-06-29-ui-import-assets";
const RECENT_PROJECTS_KEY = "uim.recentProjects.v1";
const SUPPORTED_ANCHOR_OUTPUT_SIZES = [512, 1024, 1536];
const DEFAULT_SEEDANCE_MODEL = "doubao-seedance-2-0-260128";
const DEFAULT_SEEDANCE_RESOLUTION = "720p";
const DEFAULT_SEEDANCE_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks";
let lastBackendStartStatus: BackendWorkerStatus | null = null;
const GAME_UI_DEFAULT_STYLE_TOKENS: Record<string, string> = {
  panel: "panelDefault",
  image: "imageFrame",
  text: "textPlate",
  button: "buttonDefault",
  input: "inputDefault",
  checkbox: "checkboxBox",
  scroll: "scrollTrack",
  slider: "sliderTrack",
  dropdown: "dropdownBox"
};
const GAME_UI_BOX_STYLE_TOKENS = new Set([
  "panelDefault",
  "textPlate",
  "buttonDefault",
  "inputDefault",
  "scrollTrack",
  "scrollThumb",
  "sliderTrack",
  "sliderFill",
  "dropdownBox",
  "dropdownOption"
]);
const SEEDANCE_MODEL_ALIASES: Record<string, string> = {
  "seedance2.0": "doubao-seedance-2-0-260128",
  "seedance-2.0": "doubao-seedance-2-0-260128",
  "doubao-seedance-2-0-pro-260128": "doubao-seedance-2-0-260128",
  "seedance2.0-fast": "doubao-seedance-2-0-fast-260128",
  "seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
  "seedance2.0-mini": "doubao-seedance-2-0-mini-260615",
  "seedance-2.0-mini": "doubao-seedance-2-0-mini-260615",
  "doubao-seedance-2-0-mini-260128": "doubao-seedance-2-0-mini-260615"
};
const SEEDANCE_MODEL_RESOLUTIONS: Record<string, string[]> = {
  "doubao-seedance-2-0-260128": ["480p", "720p", "1080p", "4K"],
  "doubao-seedance-2-0-fast-260128": ["480p", "720p"],
  "doubao-seedance-2-0-mini-260615": ["480p", "720p"]
};
const SEEDANCE_MODEL_OPTIONS = [
  { value: "doubao-seedance-2-0-260128", label: "Seedance 2.0", description: "质量优先，支持 480p/720p/1080p/4K" },
  { value: "doubao-seedance-2-0-fast-260128", label: "Seedance 2.0 Fast", description: "速度优先，推荐 480p/720p" },
  { value: "doubao-seedance-2-0-mini-260615", label: "Seedance 2.0 Mini", description: "轻量模式，推荐 480p/720p" }
];
const PIXEL_MASK_MODE_OPTIONS = [
  { value: "hybrid", label: "Hybrid Mask", description: "OpenCV 边缘背景 + rembg 语义参考，默认推荐" },
  { value: "rembg", label: "rembg Alpha", description: "只使用 rembg 结果的 alpha" },
  { value: "classic", label: "边缘连通背景", description: "只用 OpenCV 从边缘连通背景抠图" }
];
const PIXEL_RESTORE_MODE_OPTIONS = [
  { value: "none", label: "不修复", description: "直接归一化，默认" },
  { value: "clean", label: "unfake clean", description: "轻量像素清理" },
  { value: "safe", label: "unfake safe", description: "动画推荐，降低伪像素和抗锯齿" },
  { value: "pixel", label: "unfake pixel", description: "更激进的像素重建，适合静态图" }
];
const DEFAULT_PIXEL_I2V_ACTION_DESCRIPTIONS: Record<PixelKind, string> = {
  character: "原地行走循环，镜头不动，角色始终居中，背景保持纯 #FF00FF，动作匀速且节奏稳定，轻微上下起伏，双腿交替迈步，衣物和装备轻微摆动，手臂动作克制",
  weapon: "单件武器状态循环，镜头不动，武器始终完整居中，背景保持纯 #FF00FF，动作匀速且节奏稳定，轻微闪光、蓄力亮度变化或克制的挥动残影，最后回到起始轮廓",
  decoration: "单个装饰物 idle 循环，镜头不动，物件始终完整居中，背景保持纯 #FF00FF，可有轻微发光、漂浮、火焰跳动或机关开合，最后回到起始状态",
  tilemap: ""
};
const DEFAULT_VIDEO_LOOP_MIN_SCORE = 0.9;

type MainTab = "pixel" | "game_ui" | "assets" | "export" | "models" | "settings";
type ImageProvider = "openai_api" | "codex_oauth";
type PixelKind = "character" | "weapon" | "decoration" | "tilemap";
const PIXEL_KIND_DEFAULT_SUBJECTS: Record<PixelKind, string> = {
  character: "红披风剑士，短剑，轻甲",
  weapon: "银色长剑，蓝色宝石护手，轻微魔法纹路",
  decoration: "发光水晶柱，石质底座，蓝紫色微光",
  tilemap: ""
};

const PIXEL_KIND_COPY: Record<
  PixelKind,
  {
    label: string;
    subjectLabel: string;
    conceptTitle: string;
    conceptStepDetail: string;
    conceptHint: string;
    conceptButton: string;
    anchorTitle: string;
    anchorStepDetail: string;
    anchorHint: string;
    anchorButton: string;
    anchorSlotLabel: string;
    anchorSlotDescription: string;
    sheetTitle: string;
    sheetStepDetail: string;
    sheetDirectHint: string;
  }
> = {
  character: {
    label: "角色",
    subjectLabel: "角色设定",
    conceptTitle: "角色概念图",
    conceptStepDetail: "确定轮廓、配色、气质",
    conceptHint: "文本生成 {size} 的美术方向图。它只用来确定轮廓、配色和角色气质，不会作为后续基准图的图片参考。",
    conceptButton: "生成角色概念图",
    anchorTitle: "正面游戏基准图",
    anchorStepDetail: "文本 + 像素网格",
    anchorHint: "只传像素网格参考，不传概念图。逻辑帧尺寸会作为后续动作序列图的默认单帧尺寸，输出尺寸用于控制基准图实际生成分辨率。",
    anchorButton: "生成正面基准图",
    anchorSlotLabel: "方向基准图",
    anchorSlotDescription: "直接生成会读取这里的基准图。右侧可独立生成，也可手动选择由左侧镜像生成。",
    sheetTitle: "动作序列图",
    sheetStepDetail: "直接生成或图生视频",
    sheetDirectHint: "直接生成适合待机、简单攻击和草稿动作；输出可直接进入归一化。"
  },
  weapon: {
    label: "武器",
    subjectLabel: "武器设定",
    conceptTitle: "武器概念图",
    conceptStepDetail: "确定武器轮廓、材质、特征",
    conceptHint: "文本生成 {size} 的武器美术方向图。重点确认武器类型、材质、轮廓、握持方向和克制特效，不作为后续基准图的图片参考。",
    conceptButton: "生成武器概念图",
    anchorTitle: "单物件基准图",
    anchorStepDetail: "网格约束的单件武器",
    anchorHint: "使用像素网格约束生成单件武器基准图，要求居中、轮廓可读、无持有者/手臂/文字；不做多方向基准。",
    anchorButton: "生成单物件基准图",
    anchorSlotLabel: "单物件基准图",
    anchorSlotDescription: "直接生成会读取这里的单件武器基准图。",
    sheetTitle: "状态序列图",
    sheetStepDetail: "闪光、蓄力、挥动残影等状态帧",
    sheetDirectHint: "直接生成适合武器轻微闪光、蓄力、挥动残影等简单状态帧；主体必须保持同一件武器。"
  },
  decoration: {
    label: "装饰物",
    subjectLabel: "装饰物设定",
    conceptTitle: "装饰物概念图",
    conceptStepDetail: "确定道具用途、材质、体积",
    conceptHint: "文本生成 {size} 的装饰物美术方向图。重点确认场景小物/道具用途、材质、体积和俯视角可读性，不作为后续基准图的图片参考。",
    conceptButton: "生成装饰物概念图",
    anchorTitle: "单物件基准图",
    anchorStepDetail: "网格约束的独立装饰物",
    anchorHint: "使用像素网格约束生成单个可放置装饰物基准图，要求独立、居中、底座/占地清楚、无持有者/手臂/文字。",
    anchorButton: "生成单物件基准图",
    anchorSlotLabel: "单物件基准图",
    anchorSlotDescription: "直接生成会读取这里的单个装饰物基准图。",
    sheetTitle: "状态序列图",
    sheetStepDetail: "发光、漂浮、火焰、机关等状态帧",
    sheetDirectHint: "直接生成适合装饰物 idle loop，如轻微发光、漂浮、火焰、机关开合等；主体必须保持同一件物件。"
  },
  tilemap: {
    label: "地形集",
    subjectLabel: "地形集设定",
    conceptTitle: "地形集",
    conceptStepDetail: "生成 outer / primary 材质样例",
    conceptHint: "先同步生成 outer / primary 两个纯材质样例格子，确认材质可用后再生成最终 dual-grid 16 地形集。",
    conceptButton: "生成材质样例",
    anchorTitle: "生成 Dual-Grid 16",
    anchorStepDetail: "从材质样例生成最终地形集",
    anchorHint: "读取 outer / primary 两个样例格子，程序拼出 dual-grid 16 硬模板，再让 AI 精修真实过渡边界。",
    anchorButton: "生成 Dual-Grid 16 地形集",
    anchorSlotLabel: "材质样例",
    anchorSlotDescription: "阶段 1 生成的 outer / primary 纯材质样例。",
    sheetTitle: "地形集",
    sheetStepDetail: "Tilemap 自动拼接规则",
    sheetDirectHint: "地形集流程分为材质样例和 Dual-Grid 16 生成两步。"
  }
};

function pixelKindCopy(kind: PixelKind) {
  return PIXEL_KIND_COPY[kind];
}

type PixelStage = "concept" | "south_anchor" | "neutral_anchor" | "direction_anchor" | "sheet" | "cutout" | "normalize" | "tilemap_seed" | "tilemap_tileset";
type PixelSheetMode = "direct" | "video";
type PixelMaskMode = "hybrid" | "rembg" | "classic";
type PixelRestoreMode = "none" | "clean" | "safe" | "pixel";
type TilemapStandard = "47-tile" | "dual-grid-16";
type UIWidgetType = "button" | "panel" | "icon";
type GameUiWorkspaceTab = "structure" | "texture_kit";
type VideoFrameSelection = { id: string; time: number; thumbnail: string; selected: boolean; loopHint: boolean; loopScore?: number };
type VideoDebugExportType = "png_sequence" | "gif" | "sheet";
type VideoThumbnailResponse = { extractor?: string; frames: Array<{ time: number; thumbnail: string }> };
type VideoFrameMetrics = { histogram: number[]; pixels: number[] };
type VideoLoopScore = { score: number; spatial: number; histogram: number };

const DEFAULT_GAME_UI_TEXTURE_TOKEN_COUNT = 14;
const DEFAULT_GAME_UI_TEXTURE_STATE_COUNT = 39;
const DEFAULT_GAME_UI_TEXTURE_BATCH_COUNT = 3;
const GAME_UI_CHROMA_PRESETS = [
  { value: "#FF00FF", label: "#FF00FF 品红", description: "默认，兼容旧贴图流程" },
  { value: "#00FF00", label: "#00FF00 绿", description: "常见 chroma key" },
  { value: "#00FFFF", label: "#00FFFF 青", description: "避开紫色 UI 风格" },
  { value: "#B6FF00", label: "#B6FF00 黄绿", description: "避开蓝紫/青色 UI 风格" },
  { value: "custom", label: "自定义 HEX", description: "可输入 #RRGGBB" }
];
const TILEMAP_STANDARD_OPTIONS: Array<{ value: TilemapStandard; label: string; shortLabel: string; description: string; detail: string }> = [
  {
    value: "47-tile",
    label: "47 图块",
    shortLabel: "47",
    description: "AI 生成泥土/青草材质并精修边界，再程序组装为传统 47-tile 混合集。",
    detail: "适合自然地形边缘；tileset 按 8 列 row-major 排布。"
  },
  {
    value: "dual-grid-16",
    label: "双网格 16",
    shortLabel: "双网格",
    description: "AI 生成泥土/青草材质并精修边界，再程序组装为 dual-grid 转角集。",
    detail: "4x4 row-major；mask 位定义：NW=1, NE=2, SW=4, SE=8。"
  }
];

type ModelInfo = {
  id: string;
  display_name: string;
  provider: string;
  task: string;
  version: string;
  license: string;
  recommended_vram_gb: number;
  size_hint: string;
  source: string;
  status: string;
  local_path?: string;
  checksum?: string | null;
  download_url?: string;
  config_name?: string | null;
};

type ModelsResponse = {
  cacheDir: string;
  models: ModelInfo[];
  dependencies?: Array<{ id: string; label: string; available: boolean; detail: string }>;
};

type RuntimeSettings = {
  workspaceRoot: string;
  modelCacheDir: string;
  hasOpenAiApiKey: boolean;
  openAiBaseUrl: string;
  openAiMergeEditImages: boolean;
  unrealMcpUrl: string;
  hasHuggingFaceToken: boolean;
  networkProxy: string;
  codexOAuth: CodexOAuthStatus;
  hasSeedanceApiKey: boolean;
  seedanceEndpoint: string;
  seedanceModel: string;
  seedanceResolution: string;
  seedanceConfigured: boolean;
};

type CodexOAuthStatus = {
  configured: boolean;
  email: string;
  accountId: string;
  expiresAt: string;
  hasRefreshToken: boolean;
  storePath: string;
};

type CodexOAuthFlow = {
  state: string;
  challenge: string;
  authorize_url: string;
  redirect_uri: string;
  auto_callback: boolean;
  message: string;
};

type CodexOAuthPollResult = {
  state: string;
  status: "pending" | "success" | "error";
  message: string;
  redirectUri: string;
  codexOAuth: CodexOAuthStatus;
};

type ValidationResult = {
  errors: string[];
  issues: Array<{ severity?: string; code?: string; message?: string; path?: string | null }>;
};

type UnrealMcpStatus = {
  available: boolean;
  mode: string;
  detail: string;
};

type NetworkCheckResult = {
  reachable: boolean;
  proxy: string;
  status: number;
  detail: string;
};

type ProjectOpenResult = {
  project: {
    id: string;
    name: string;
    default_style: string;
    target_engines: string[];
  };
  lockedModels: unknown[];
  missingModels: unknown[];
};

type RecentProject = {
  root: string;
  name: string;
  lastOpenedAt: string;
};

type BackendWorkerStatus = {
  online: boolean;
  stdout_log?: string;
  stderr_log?: string;
  error?: string;
  started?: boolean;
  reason?: string;
};

type McpRuntimePaths = {
  root: string;
  python: string;
  backend: string;
  available: boolean;
};

type HealthResponse = {
  status: string;
  appVersion?: string;
  apiContractVersion?: string;
  capabilities?: {
    codexOAuthCallback?: string;
    openAiBaseUrl?: boolean;
    bundledVideoFfmpeg?: boolean;
    videoThumbnails?: boolean;
    gameUiMcp?: boolean;
  };
};

type GameUiStructureSummary = {
  screenName: string;
  path: string;
  referenceResolution?: { width?: number; height?: number };
  createdAt?: string;
};

type GameUiHtmlPrototypeSummary = {
  screenName: string;
  path: string;
  updatedAt?: string;
};

type GameUiTextureKitSummary = {
  kitName: string;
  path: string;
  contentPath?: string;
  tokens: string[];
  validation?: { ok?: boolean; issues?: string[]; warnings?: string[] };
  inProgress?: boolean;
  generatedStateCount?: number;
  stateSheetCount?: number;
  workPath?: string;
  textureDir?: string;
};

type GameUiPreviewNode = {
  name?: string;
  type?: string;
  styleToken?: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  anchors?: {
    minimum?: { x?: number; y?: number };
    maximum?: { x?: number; y?: number };
  };
  offsets?: { left?: number; top?: number; right?: number; bottom?: number };
  alignment?: { x?: number; y?: number };
  color?: string;
  fontColor?: string;
  fontSize?: number;
  fontWeight?: string | number;
  textAlign?: string;
  text?: string;
  value?: number;
  checked?: boolean;
  direction?: string;
  options?: string[];
  children?: GameUiPreviewNode[];
};

type GameUiPreviewBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type GameUiPreviewLayoutNode = {
  node: GameUiPreviewNode;
  box: GameUiPreviewBox;
};

type GameUiPreviewStructure = {
  schema?: string;
  screenName?: string;
  referenceResolution?: { width?: number; height?: number };
  root?: GameUiPreviewNode;
};

type GameUiPreviewTextureState = {
  path?: string;
  unrealPath?: string;
};

type GameUiPreviewTextureKit = {
  kitName?: string;
  textures?: Record<string, { states?: Record<string, GameUiPreviewTextureState> }>;
};

type GameUiPreviewData = {
  structure: GameUiPreviewStructure;
  textureKit: GameUiPreviewTextureKit;
  structurePath: string;
  textureKitPath: string;
};

type AssetRecord = {
  id: string;
  name: string;
  kind?: string;
  type: string;
  path?: string;
  manifest?: Record<string, unknown>;
  settings?: Record<string, unknown>;
  versions?: AssetImageVersion[];
};

type PixelAssetSettings = {
  cellSize?: number;
  anchorOutputSize?: string;
};

type AssetImageVersion = {
  id: string;
  role: string;
  label: string;
  path: string;
  createdAt: string;
  order: number;
};

type ProjectAssetsResponse = {
  assets: AssetRecord[];
};

type WorkflowSlotValue = {
  mode?: "auto" | "fixed";
  assetId?: string;
  versionId?: string;
};

type WorkflowSlots = {
  pixel?: Record<string, WorkflowSlotValue>;
  gameUi?: Record<string, WorkflowSlotValue>;
};

type WorkflowSlotGroup = keyof WorkflowSlots;

type ResolvedSlot = {
  group: WorkflowSlotGroup;
  key: string;
  label: string;
  roles: string[];
  asset: AssetRecord;
  version: AssetImageVersion;
  mode: "auto" | "fixed";
};

type BrowserRoleMatcher =
  | { type: "exact"; value: string }
  | { type: "prefix"; value: string };

type ImageVersionTreeNode = {
  id: string;
  name: string;
  kind: "folder" | "file" | "empty";
  count?: number;
  version?: AssetImageVersion;
  path?: string;
  roleLabel?: string;
  dateLabel?: string;
  children?: ImageVersionTreeNode[];
};

type AssetTreeNode = {
  id: string;
  name: string;
  kind: "group" | "asset";
  asset?: AssetRecord;
  count?: number;
  children?: AssetTreeNode[];
};

type PendingDeleteTarget =
  | { kind: "asset"; asset: AssetRecord }
  | { kind: "version"; version: AssetImageVersion };

type RunActionOptions = {
  notify?: boolean;
};

type PixelMatrixActionKey = string;
type PixelMatrixDirection = "south" | "north" | "west" | "east";
type PixelBatchOperation = "generate_missing" | "cutout" | "normalize" | "cutout_normalize";
type PixelBatchStep = "sheet" | "cutout" | "normalize";
type PixelBatchTaskStatus = "queued" | "running" | "done" | "failed";

type PixelBatchTask = {
  id: string;
  actionKey: PixelMatrixActionKey;
  actionId: string;
  direction: PixelMatrixDirection;
  steps: PixelBatchStep[];
  status: PixelBatchTaskStatus;
  currentStep?: PixelBatchStep;
  logs: string[];
  error?: string;
};

type PixelMatrixCellState = {
  key: string;
  actionKey: PixelMatrixActionKey;
  actionId: string;
  actionLabel: string;
  direction: PixelMatrixDirection;
  directionLabel: string;
  sheet?: AssetImageVersion;
  cutout?: AssetImageVersion;
  runtime?: AssetImageVersion;
  preview?: AssetImageVersion;
  video?: AssetImageVersion;
  status: "missing" | "video" | "sheet" | "cutout" | "runtime" | "stale";
  statusLabel: string;
  stale: boolean;
};

type PixelMatrixAction = {
  key: PixelMatrixActionKey;
  id: string;
  label: string;
  source: "current" | "asset";
};

type ProjectWorkspaceResponse = {
  processingQueue?: unknown[];
  workflowSlots: WorkflowSlots;
  mcpUiState?: McpUiState;
};

type McpUiState = {
  revision?: number;
  mainTab?: MainTab;
  assetName?: string;
  pixelKind?: PixelKind;
  pixelStage?: PixelStage;
  pixelAction?: string;
  pixelDirection?: string;
  pixelSheetMode?: PixelSheetMode;
  lastTool?: string;
  lastMessage?: string;
  updatedAt?: string;
};

type StreamEventResponse = {
  session: string;
  next: number;
  events: Array<{ index: number; message: string }>;
};

async function api<T>(path: string, init?: RequestInit, retryBackend = true): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers,
      ...init
    });
  } catch (error) {
    if (retryBackend) {
      if (await waitForBackendHealth(900)) {
        return api<T>(path, init, false);
      }
      const status = await startBackendWorker();
      void status;
      await waitForBackendHealth();
      return api<T>(path, init, false);
    }
    const detail = error instanceof Error ? error.message : String(error);
    const suffix = detail && detail !== "Failed to fetch" ? ` 原始错误：${detail}` : "";
    throw new Error(`无法连接本地后端 ${API_BASE}。已尝试自动拉起后端。${backendStartDiagnostic()}${suffix}`);
  }
  if (!response.ok) {
    const text = await response.text();
    let message = text || response.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      message = parsed.detail || message;
    } catch {
      // Keep raw text for non-JSON errors.
    }
    if (retryBackend && response.status === 404) {
      await startBackendWorker();
      await waitForBackendHealth();
      return api<T>(path, init, false);
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

async function tauriCommand<T>(command: string): Promise<T | null> {
  try {
    return await invoke<T>(command);
  } catch {
    return null;
  }
}

async function startBackendWorker(): Promise<BackendWorkerStatus | null> {
  const tauriStatus = await tauriCommand<BackendWorkerStatus>("restart_backend_worker");
  if (tauriStatus) {
    lastBackendStartStatus = tauriStatus;
    return tauriStatus;
  }
  if (window.location.protocol !== "http:" && window.location.protocol !== "https:") return null;
  if (!["127.0.0.1", "localhost"].includes(window.location.hostname)) return null;
  try {
    const response = await fetch(`${window.location.origin}/__uim/restart-backend`, { method: "POST" });
    if (!response.ok) {
      lastBackendStartStatus = { online: false, error: await response.text() };
      return lastBackendStartStatus;
    }
    lastBackendStartStatus = (await response.json()) as BackendWorkerStatus;
    return lastBackendStartStatus;
  } catch (error) {
    lastBackendStartStatus = { online: false, error: error instanceof Error ? error.message : String(error) };
    return lastBackendStartStatus;
  }
}

async function waitForBackendHealth(timeoutMs = 6000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${API_BASE}/health`);
      if (response.ok) {
        const health = (await response.json()) as HealthResponse;
        if (health.status === "ok" && health.apiContractVersion === EXPECTED_API_CONTRACT_VERSION) return true;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 300));
  }
  if (lastError) {
    lastBackendStartStatus = { ...(lastBackendStartStatus ?? { online: false }), online: false, error: lastError };
  }
  return false;
}

function backendStartDiagnostic() {
  const status = lastBackendStartStatus;
  if (!status) return "";
  const parts = [
    status.error ? `启动错误：${status.error}` : "",
    status.stderr_log ? `stderr：${status.stderr_log}` : "",
    status.stdout_log ? `stdout：${status.stdout_log}` : ""
  ].filter(Boolean);
  return parts.length > 0 ? ` ${parts.join("；")}` : "";
}

function manifestName(manifest: Record<string, unknown>) {
  return String(manifest.displayName || manifest.id || "Untitled asset");
}

function manifestType(manifest: Record<string, unknown>) {
  return String(manifest.assetType || "asset");
}

function firstManifestPath(manifest: Record<string, unknown>) {
  const files = manifest.files as Array<{ path?: string }> | undefined;
  return files?.find((file) => file.path)?.path;
}

function previewUrl(projectRoot: string, asset: AssetRecord | null) {
  if (!asset?.path) return "";
  return previewUrlForPath(projectRoot, asset.path);
}

function previewUrlForPath(projectRoot: string, path: string) {
  if (!path) return "";
  const query = new URLSearchParams({
    project_root: projectRoot,
    path
  });
  return `${API_BASE}/assets/preview?${query.toString()}`;
}

function normalizeProjectRootInput(root: string) {
  return root.trim().replace(/[\\/]+$/, "");
}

function projectNameFromRoot(root: string) {
  const normalized = normalizeProjectRootInput(root);
  const parts = normalized.split(/[\\/]/).filter(Boolean);
  const last = parts[parts.length - 1] || "Project";
  return last.replace(/\.uim$/i, "") || "Project";
}

function loadRecentProjects() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(RECENT_PROJECTS_KEY) || "[]") as RecentProject[];
    return parsed
      .filter((item) => item && typeof item.root === "string" && item.root.trim())
      .map((item) => ({
        root: normalizeProjectRootInput(item.root),
        name: item.name || projectNameFromRoot(item.root),
        lastOpenedAt: item.lastOpenedAt || new Date(0).toISOString()
      }))
      .slice(0, 8);
  } catch {
    return [];
  }
}

function saveRecentProjects(projects: RecentProject[]) {
  try {
    window.localStorage.setItem(RECENT_PROJECTS_KEY, JSON.stringify(projects.slice(0, 8)));
  } catch {
    // Recent projects are a convenience; project operations should continue even if storage is blocked.
  }
}

function formatRecentProjectTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function assetIdFromName(name: string) {
  const trimmed = name.trim();
  const ascii = trimmed.toLowerCase().split(/\s+/).join("_").replace(/[^a-z0-9_-]/g, "");
  if (ascii) return ascii;
  const unicodeKey = Array.from(trimmed)
    .map((char) => char.codePointAt(0)?.toString(16) || "")
    .filter(Boolean)
    .join("_");
  return unicodeKey ? `asset_${unicodeKey.slice(0, 96)}` : "asset";
}

function timestampLabel() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function projectPathForGenerated(projectRoot: string, assetName: string, role: string) {
  const assetId = assetIdFromName(assetName);
  return `${projectRoot.replace(/[\\/]$/, "")}/assets/${assetId}/generated/${assetIdFromName(role)}_${timestampLabel()}.png`;
}

function absoluteProjectPath(projectRoot: string, path: string) {
  if (!path) return "";
  if (/^[a-zA-Z]:[\\/]/.test(path) || path.startsWith("/") || path.startsWith("\\\\")) return path;
  return `${projectRoot.replace(/[\\/]$/, "")}/${path}`;
}

function formatVideoTime(seconds: number) {
  if (!Number.isFinite(seconds)) return "00:00.000";
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const wholeSeconds = Math.floor(safe % 60);
  const millis = Math.round((safe - Math.floor(safe)) * 1000);
  return `${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function normalizeSeedanceModel(value: string | null | undefined) {
  const trimmed = (value || "").trim();
  if (!trimmed) return "";
  return SEEDANCE_MODEL_ALIASES[trimmed] || trimmed;
}

type CommandComboboxOption = {
  value: string;
  label: string;
  description?: string;
};

function useDismissableCombobox<T extends HTMLElement>(setOpen: (open: boolean) => void) {
  const rootRef = useRef<T | null>(null);

  const handleBlur = (event: React.FocusEvent<T>) => {
    const nextFocus = event.relatedTarget;
    if (nextFocus instanceof Node && event.currentTarget.contains(nextFocus)) return;
    setOpen(false);
  };

  const handleKeyDown = (event: React.KeyboardEvent<T>) => {
    if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return { rootRef, handleBlur, handleKeyDown };
}

function CommandCombobox({
  value,
  onValueChange,
  options,
  placeholder,
  searchPlaceholder,
  emptyLabel = "没有匹配项",
  allowCustom = true
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: CommandComboboxOption[];
  placeholder: string;
  searchPlaceholder: string;
  emptyLabel?: string;
  allowCustom?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = options.find((option) => option.value === value);
  const queryValue = query.trim();
  const canUseCustom = allowCustom && queryValue && !options.some((option) => option.value.toLowerCase() === queryValue.toLowerCase());
  const comboboxDismiss = useDismissableCombobox<HTMLDivElement>(setOpen);

  function choose(nextValue: string) {
    onValueChange(nextValue);
    setQuery("");
    setOpen(false);
  }

  return (
    <div className="cmdk-combobox" onBlur={comboboxDismiss.handleBlur} onKeyDown={comboboxDismiss.handleKeyDown} ref={comboboxDismiss.rootRef}>
      <button
        className="cmdk-combobox-trigger"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span>
          <strong>{selected?.label || value || placeholder}</strong>
          {(selected?.description || (value && !selected ? "自定义值" : "")) && <small>{selected?.description || "自定义值"}</small>}
        </span>
        <ChevronDown size={16} />
      </button>
      {open && (
        <Command className="cmdk-combobox-menu" shouldFilter>
          <Command.Input autoFocus value={query} onValueChange={setQuery} placeholder={searchPlaceholder} />
          <Command.List>
            <Command.Empty>{emptyLabel}</Command.Empty>
            <Command.Group>
              {options.map((option) => (
                <Command.Item key={option.value} value={`${option.label} ${option.value} ${option.description || ""}`} onSelect={() => choose(option.value)}>
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.value}{option.description ? ` · ${option.description}` : ""}</small>
                  </span>
                  {option.value === value && <Check size={15} />}
                </Command.Item>
              ))}
              {canUseCustom && (
                <Command.Item value={queryValue} onSelect={() => choose(queryValue)}>
                  <span>
                    <strong>使用“{queryValue}”</strong>
                    <small>自定义值</small>
                  </span>
                  <CheckCircle2 size={15} />
                </Command.Item>
              )}
            </Command.Group>
          </Command.List>
        </Command>
      )}
    </div>
  );
}

function EditableCommandCombobox({
  value,
  onValueChange,
  options,
  placeholder,
  emptyLabel = "没有匹配项"
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: CommandComboboxOption[];
  placeholder: string;
  emptyLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(value);
  const comboboxDismiss = useDismissableCombobox<HTMLDivElement>(setOpen);
  const queryValue = query.trim();
  const normalizedQuery = queryValue.toLowerCase();
  const filteredOptions = normalizedQuery
    ? options.filter((option) => `${option.label} ${option.value} ${option.description || ""}`.toLowerCase().includes(normalizedQuery))
    : options;
  const hasExactOption = options.some((option) => option.value.toLowerCase() === queryValue.toLowerCase() || option.label.toLowerCase() === queryValue.toLowerCase());
  const canUseCustom = Boolean(queryValue && !hasExactOption);

  function choose(nextValue: string) {
    onValueChange(nextValue);
    setQuery(nextValue);
    setOpen(false);
  }

  function updateTypedValue(nextValue: string) {
    onValueChange(nextValue);
    setQuery(nextValue);
    setOpen(true);
  }

  return (
    <div className="cmdk-combobox" onBlur={comboboxDismiss.handleBlur} onKeyDown={comboboxDismiss.handleKeyDown} ref={comboboxDismiss.rootRef}>
      <div className="cmdk-combobox-trigger cmdk-combobox-input-trigger">
        <input
          value={value}
          onChange={(event) => updateTypedValue(event.currentTarget.value)}
          onFocus={() => {
            setQuery(value);
            setOpen(true);
          }}
          placeholder={placeholder}
        />
        <button
          aria-label="展开选项"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            setQuery(value);
            setOpen((current) => !current);
          }}
          type="button"
        >
          <ChevronDown size={16} />
        </button>
      </div>
      {open && (
        <Command className="cmdk-combobox-menu" shouldFilter={false}>
          <Command.List>
            {filteredOptions.length === 0 && !canUseCustom && <Command.Empty>{emptyLabel}</Command.Empty>}
            <Command.Group>
              {filteredOptions.map((option) => (
                <Command.Item key={option.value} value={option.value} onSelect={() => choose(option.value)}>
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.value}{option.description ? ` · ${option.description}` : ""}</small>
                  </span>
                  {option.value === value && <Check size={15} />}
                </Command.Item>
              ))}
              {canUseCustom && (
                <Command.Item value={queryValue} onSelect={() => choose(queryValue)}>
                  <span>
                    <strong>新增“{queryValue}”</strong>
                    <small>自定义名称</small>
                  </span>
                  <CheckCircle2 size={15} />
                </Command.Item>
              )}
            </Command.Group>
          </Command.List>
        </Command>
      )}
    </div>
  );
}

function App() {
  const [backend, setBackend] = useState<"checking" | "online" | "offline">("checking");
  const [workerStatus, setWorkerStatus] = useState<BackendWorkerStatus | null>(null);
  const [projectRoot, setProjectRoot] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectPanelMode, setProjectPanelMode] = useState<"open" | "create">("open");
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>(() => loadRecentProjects());
  const [project, setProject] = useState<ProjectOpenResult | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelDependencies, setModelDependencies] = useState<ModelsResponse["dependencies"]>([]);
  const [assets, setAssets] = useState<AssetRecord[]>([]);
  const [workflowSlots, setWorkflowSlots] = useState<WorkflowSlots>({});
  const [mainTab, setMainTab] = useState<MainTab>("pixel");
  const [currentManifest, setCurrentManifest] = useState<Record<string, unknown> | null>(null);
  const [lastResult, setLastResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [activeStreamSession, setActiveStreamSession] = useState<string | null>(null);
  const [cancelRequested, setCancelRequested] = useState(false);
  const [taskProgress, setTaskProgress] = useState<{ current: number; total: number; label: string } | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const consoleOutputRef = useRef<HTMLDivElement | null>(null);
  const consolePinnedToBottomRef = useRef(true);
  const mcpUiRevisionRef = useRef(0);
  const projectRootRef = useRef("");
  const videoFramePickerRef = useRef<HTMLVideoElement | null>(null);
  const videoSelectionPreviewTimerRef = useRef<number | null>(null);
  const videoSelectionPreviewingRef = useRef(false);
  const videoLoopPreviewingRef = useRef(false);
  const videoPreviewStageRef = useRef<HTMLDivElement | null>(null);
  const gameUiPreviewCanvasRef = useRef<HTMLDivElement | null>(null);
  const videoFrameThumbnailCacheRef = useRef(new Map<string, string>());
  const videoFrameMetricCacheRef = useRef(new Map<string, VideoFrameMetrics>());
  const videoLoopScoreCacheRef = useRef(new Map<string, VideoLoopScore>());
  const assetRefreshRequestRef = useRef(0);
  const workspaceRefreshRequestRef = useRef(0);
  const [gameUiPreviewCanvasWidth, setGameUiPreviewCanvasWidth] = useState(0);
  const [previewHeight, setPreviewHeight] = useState(360);
  const previewResizeRef = useRef<{ pointerId: number; startY: number; startHeight: number } | null>(null);
  const [activePreviewVersionId, setActivePreviewVersionId] = useState<string | null>(null);
  const [activePreviewPath, setActivePreviewPath] = useState("");
  const [activePreviewLabel, setActivePreviewLabel] = useState("");
  const [pendingDelete, setPendingDelete] = useState<PendingDeleteTarget | null>(null);
  const [modelCacheDir, setModelCacheDir] = useState("");
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null);
  const [mcpRuntimePaths, setMcpRuntimePaths] = useState<McpRuntimePaths | null>(null);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [unrealStatus, setUnrealStatus] = useState<UnrealMcpStatus | null>(null);
  const [networkCheck, setNetworkCheck] = useState<NetworkCheckResult | null>(null);
  const [openAiKeyDraft, setOpenAiKeyDraft] = useState("");
  const [openAiBaseUrlDraft, setOpenAiBaseUrlDraft] = useState("");
  const [openAiMergeEditImagesDraft, setOpenAiMergeEditImagesDraft] = useState(true);
  const [huggingFaceTokenDraft, setHuggingFaceTokenDraft] = useState("");
  const [unrealMcpUrlDraft, setUnrealMcpUrlDraft] = useState("");
  const [networkProxyDraft, setNetworkProxyDraft] = useState("");
  const [seedanceKeyDraft, setSeedanceKeyDraft] = useState("");
  const [seedanceEndpointDraft, setSeedanceEndpointDraft] = useState("");
  const [seedanceModelDraft, setSeedanceModelDraft] = useState("");
  const [seedanceResolutionDraft, setSeedanceResolutionDraft] = useState("720p");
  const [codexFlow, setCodexFlow] = useState<CodexOAuthFlow | null>(null);
  const [codexCallbackInput, setCodexCallbackInput] = useState("");

  const [prompt, setPrompt] = useState("32x32 pixel art fire spell icon, transparent background");
  const [assetName, setAssetName] = useState("火焰法术");
  const [styleId, setStyleId] = useState("pixel_art");
  const [contentPath, setContentPath] = useState("/Game/UIM");
  const [imageProvider, setImageProvider] = useState<ImageProvider>("openai_api");

  const [pixelKind, setPixelKind] = useState<PixelKind>("character");
  const [pixelStage, setPixelStage] = useState<PixelStage>("concept");
  const [pixelSubject, setPixelSubject] = useState(PIXEL_KIND_DEFAULT_SUBJECTS.character);
  const [pixelDirection, setPixelDirection] = useState("south");
  const [pixelAction, setPixelAction] = useState("idle");
  const [pixelSheetMode, setPixelSheetMode] = useState<PixelSheetMode>("video");
  const [pixelCustomActionName, setPixelCustomActionName] = useState("闪避翻滚");
  const [pixelActionDescription, setPixelActionDescription] = useState("快速向当前方向翻滚/闪避，身体压低，披风和装备有短暂拖拽，最后回到稳定站姿");
  const [pixelConceptPath, setPixelConceptPath] = useState("");
  const [pixelAnchorUseConcept, setPixelAnchorUseConcept] = useState(true);
  const [pixelMirrorEastFromWest, setPixelMirrorEastFromWest] = useState(false);
  const [pixelAnchorPath, setPixelAnchorPath] = useState("");
  const [pixelSheetPath, setPixelSheetPath] = useState("");
  const [pixelCutoutPath, setPixelCutoutPath] = useState("");
  const [pixelVideoPath, setPixelVideoPath] = useState("");
  const [pixelSeedanceModel, setPixelSeedanceModel] = useState("");
  const [pixelSeedanceResolution, setPixelSeedanceResolution] = useState("");
  const [videoFramePickerOpen, setVideoFramePickerOpen] = useState(false);
  const [videoFrameSelections, setVideoFrameSelections] = useState<VideoFrameSelection[]>([]);
  const [videoPickerDuration, setVideoPickerDuration] = useState(0);
  const [videoPickerCurrentTime, setVideoPickerCurrentTime] = useState(0);
  const [videoRangeStart, setVideoRangeStart] = useState(0);
  const [videoRangeEnd, setVideoRangeEnd] = useState(0);
  const [videoSelectionPreviewIndex, setVideoSelectionPreviewIndex] = useState<number | null>(null);
  const [videoSelectionPreviewing, setVideoSelectionPreviewing] = useState(false);
  const [videoLoopPreviewing, setVideoLoopPreviewing] = useState(false);
  const [videoPreviewNaturalSize, setVideoPreviewNaturalSize] = useState({ width: 0, height: 0 });
  const [videoPreviewStageSize, setVideoPreviewStageSize] = useState({ width: 0, height: 0 });
  const [videoSourceAspectRatio, setVideoSourceAspectRatio] = useState("1 / 1");
  const [videoAutoFps, setVideoAutoFps] = useState(8);
  const [videoFrameThumbnailsLoading, setVideoFrameThumbnailsLoading] = useState(false);
  const [videoLoopMinScore, setVideoLoopMinScore] = useState(DEFAULT_VIDEO_LOOP_MIN_SCORE);
  const [selectedLoopFrameId, setSelectedLoopFrameId] = useState<string | null>(null);
  const [pixelDynamicEffect, setPixelDynamicEffect] = useState("手上的火球、光效、粒子、投射物或蓄力攻击姿势");
  const [pixelAttackName, setPixelAttackName] = useState("魔法投射攻击");
  const [pixelEffectColor, setPixelEffectColor] = useState("紫色");
  const [pixelProjectileEffect, setPixelProjectileEffect] = useState("紧凑的火球投射物");
  const [pixelI2vActionDescription, setPixelI2vActionDescription] = useState(DEFAULT_PIXEL_I2V_ACTION_DESCRIPTIONS.character);
  const [pixelColumns, setPixelColumns] = useState(5);
  const [pixelRows, setPixelRows] = useState(2);
  const [pixelCellSize, setPixelCellSize] = useState(256);
  const [pixelAnchorOutputSize, setPixelAnchorOutputSize] = useState("1024x1024");
  const [pixelTileSetPath, setPixelTileSetPath] = useState("");
  const [pixelTilemapSeedPath, setPixelTilemapSeedPath] = useState("");
  const [pixelTilemapOuterPath, setPixelTilemapOuterPath] = useState("");
  const [pixelTilemapPrimaryPath, setPixelTilemapPrimaryPath] = useState("");
  const [pixelTilemapSubject, setPixelTilemapSubject] = useState("青草地形过渡到泥土地面，清晰边缘与角落过渡，适合俯视角像素 RPG 地图");
  const [pixelTilemapOuterMaterial, setPixelTilemapOuterMaterial] = useState("紧实泥土地面，少量碎石与干燥颗粒，俯视角无草叶");
  const [pixelTilemapPrimaryMaterial, setPixelTilemapPrimaryMaterial] = useState("茂密青草地面，短草簇和自然绿色纹理，俯视角像素 RPG 风格");
  const [pixelTilemapStandard, setPixelTilemapStandard] = useState<TilemapStandard>("dual-grid-16");
  const [pixelTileSize, setPixelTileSize] = useState(32);
  const [tilemapImportOpen, setTilemapImportOpen] = useState(false);
  const [pixelSeedanceSeconds, setPixelSeedanceSeconds] = useState(5);
  const [pixelMatrixSelection, setPixelMatrixSelection] = useState<string[]>([]);
  const [pixelBatchQueue, setPixelBatchQueue] = useState<PixelBatchTask[]>([]);
  const [pixelPreviewOpen, setPixelPreviewOpen] = useState(false);
  const [pixelActionMenuOpen, setPixelActionMenuOpen] = useState(false);
  const [pixelActionQuery, setPixelActionQuery] = useState("");
  const tilemapStandardOption = TILEMAP_STANDARD_OPTIONS.find((option) => option.value === pixelTilemapStandard) || TILEMAP_STANDARD_OPTIONS[0];

  const [uiAssetName, setUiAssetName] = useState("奇幻战斗界面");
  const [uiGameDescription, setUiGameDescription] = useState("俯视角像素动作 RPG，魔法、背包、技能冷却和生命资源管理");
  const [uiLayout, setUiLayout] = useState("左上角角色状态，底部技能栏，右侧小地图和任务追踪，中央留出战斗视野");
  const [uiConceptPath, setUiConceptPath] = useState("");
  const [uiWidgetType, setUiWidgetType] = useState<UIWidgetType>("button");
  const [uiWidgetDescription, setUiWidgetDescription] = useState("主操作按钮，厚实边框，适合 UE UMG，透明背景，不含文字");
  const [gameUiTab, setGameUiTab] = useState<GameUiWorkspaceTab>("structure");
  const [gameUiScreenName, setGameUiScreenName] = useState("shopScreen");
  const [gameUiHtmlDraft, setGameUiHtmlDraft] = useState("");
  const [gameUiHtmlPath, setGameUiHtmlPath] = useState("");
  const [gameUiStructurePath, setGameUiStructurePath] = useState("");
  const [gameUiHtmlPrototypes, setGameUiHtmlPrototypes] = useState<GameUiHtmlPrototypeSummary[]>([]);
  const [gameUiStructures, setGameUiStructures] = useState<GameUiStructureSummary[]>([]);
  const [gameUiTextureKits, setGameUiTextureKits] = useState<GameUiTextureKitSummary[]>([]);
  const [gameUiSelectedKitPath, setGameUiSelectedKitPath] = useState("");
  const [gameUiPreviewOpen, setGameUiPreviewOpen] = useState(false);
  const [gameUiPreviewLoading, setGameUiPreviewLoading] = useState(false);
  const [gameUiPreviewData, setGameUiPreviewData] = useState<GameUiPreviewData | null>(null);
  const [gameUiClearTextureKitTarget, setGameUiClearTextureKitTarget] = useState<GameUiTextureKitSummary | null>(null);
  const [gameUiKitName, setGameUiKitName] = useState("defaultUiKit");
  const [gameUiKitFilesJson, setGameUiKitFilesJson] = useState('[\n  {"token":"primaryButton","state":"normal","unrealPath":"/Game/UIM/UI/T_primaryButton_normal"},\n  {"token":"primaryButton","state":"hover","unrealPath":"/Game/UIM/UI/T_primaryButton_hover"},\n  {"token":"primaryButton","state":"pressed","unrealPath":"/Game/UIM/UI/T_primaryButton_pressed"},\n  {"token":"primaryButton","state":"disabled","unrealPath":"/Game/UIM/UI/T_primaryButton_disabled"}\n]');
  const [gameUiWidgetTokensJson, setGameUiWidgetTokensJson] = useState("[]");
  const [gameUiAdvancedTokensOpen, setGameUiAdvancedTokensOpen] = useState(false);
  const [gameUiTextureDebugArtifacts, setGameUiTextureDebugArtifacts] = useState(false);
  const [gameUiTextureMaxConcurrency, setGameUiTextureMaxConcurrency] = useState(4);
  const [gameUiChromaPreset, setGameUiChromaPreset] = useState("#FF00FF");
  const [gameUiCustomChromaHex, setGameUiCustomChromaHex] = useState("#FFFFFF");

  const [processInput, setProcessInput] = useState("");
  const [processOutput, setProcessOutput] = useState("");
  const [processAssetName, setProcessAssetName] = useState("处理结果");
  const [processOperation, setProcessOperation] = useState("trim");
  const [padding, setPadding] = useState(2);
  const [scale, setScale] = useState(2);
  const [colors, setColors] = useState(32);
  const [rembgModel, setRembgModel] = useState("isnet-general-use");
  const [pixelMaskMode, setPixelMaskMode] = useState<PixelMaskMode>("hybrid");
  const [pixelDecontaminateEdges, setPixelDecontaminateEdges] = useState(true);
  const [pixelDebugArtifacts, setPixelDebugArtifacts] = useState(false);
  const [pixelRestoreMode, setPixelRestoreMode] = useState<PixelRestoreMode>("safe");
  const [samModelId, setSamModelId] = useState("sam2.1_hiera_small");
  const [samImagePath, setSamImagePath] = useState("");
  const [samMaskPath, setSamMaskPath] = useState("");
  const [samPoints, setSamPoints] = useState("");
  const [samLabels, setSamLabels] = useState("1");
  const [samBox, setSamBox] = useState("");

  const [sheetPath, setSheetPath] = useState("");
  const [sheetName, setSheetName] = useState("英雄奔跑");
  const [cellWidth, setCellWidth] = useState(64);
  const [cellHeight, setCellHeight] = useState(64);

  const [uiName, setUiName] = useState("主按钮");
  const [uiNormal, setUiNormal] = useState("");
  const [uiHover, setUiHover] = useState("");
  const [uiPressed, setUiPressed] = useState("");
  const [uiDisabled, setUiDisabled] = useState("");
  const [nineSlice, setNineSlice] = useState("8,8,8,8");

  const anchorOutputOptions = useMemo(
    () =>
      SUPPORTED_ANCHOR_OUTPUT_SIZES.filter((size) => pixelCellSize > 0 && size % pixelCellSize === 0).map((size) => ({
        size,
        value: `${size}x${size}`,
        scale: size / pixelCellSize
      })),
    [pixelCellSize]
  );
  const fallbackAnchorOutputSize = anchorOutputOptions[0]?.value || "1024x1024";
  const selectedAnchorOutputOption = anchorOutputOptions.find((option) => option.value === pixelAnchorOutputSize);
  const pixelWorkCellScale = selectedAnchorOutputOption?.scale || 1;
  const pixelWorkCellSize = Math.max(pixelCellSize, Math.round(pixelCellSize * pixelWorkCellScale));

  const installedCount = useMemo(() => models.filter((model) => model.status === "installed").length, [models]);
  const issueCount = (validationResult?.errors.length ?? 0) + (validationResult?.issues.length ?? 0);
  const activeAssetName = mainTab === "game_ui" ? uiAssetName : assetName;
  const activeAssetId = assetIdFromName(activeAssetName);
  const selectedAsset = project ? assets.find((asset) => asset.id === activeAssetId) ?? assets.find((asset) => asset.name === activeAssetName) ?? null : null;
  const assetTreeData = useMemo(() => {
    if (!project) return [];
    const groups: Array<{ id: string; name: string; accepts: (asset: AssetRecord) => boolean }> = [
      { id: "pixel", name: "像素序列帧", accepts: isPixelAsset },
      { id: "ui", name: "游戏 UI", accepts: isGameUiAsset },
      { id: "other", name: "其他资产", accepts: () => true }
    ];
    const assigned = new Set<string>();
    return groups
      .map((group) => {
        const children = assets
          .filter((asset) => {
            if (assigned.has(asset.id)) return false;
            const accepted = group.accepts(asset);
            if (accepted) assigned.add(asset.id);
            return accepted;
          })
          .map((asset) => ({
            id: `asset:${asset.id}`,
            name: asset.name,
            kind: "asset" as const,
            asset
          }));
        return {
          id: `group:${group.id}`,
          name: group.name,
          kind: "group" as const,
          count: children.length,
          children
        };
      })
      .filter((group) => (group.children?.length ?? 0) > 0);
  }, [assets, project]);
  const assetTreeSelectionId = selectedAsset ? `asset:${selectedAsset.id}` : undefined;
  const selectedAssetManifestSignature = selectedAsset?.manifest ? JSON.stringify(selectedAsset.manifest) : "";
  const selectedAssetSettingsSignature = selectedAsset?.settings ? JSON.stringify(selectedAsset.settings) : "";
  const activePreviewSlot = resolvePreviewSlot();
  const previewPath = activePreviewPath || activePreviewSlot?.version?.path || selectedAsset?.path || "";
  const previewName = activePreviewLabel || (activePreviewSlot?.version ? `${activePreviewSlot.asset.name} / ${versionDisplayLabel(activePreviewSlot.version)}` : selectedAsset?.name || "");
  const disabled = backend !== "online" || busy !== null;
  const workerBlocked = backend === "offline";
  const codexOAuth = runtimeSettings?.codexOAuth;

  const tabs: Array<{ id: MainTab; label: string; icon: React.ReactNode }> = [
    { id: "pixel", label: "像素序列帧", icon: <Layers size={16} /> },
    { id: "game_ui", label: "游戏 UI", icon: <Box size={16} /> },
    { id: "models", label: "本地模型", icon: <Cpu size={16} /> },
    { id: "settings", label: "设置", icon: <Settings size={16} /> }
  ];

  useEffect(() => {
    if (!selectedAnchorOutputOption) {
      setPixelAnchorOutputSize(fallbackAnchorOutputSize);
      if (selectedAsset) {
        void savePixelAssetSettings(selectedAsset.id, selectedAsset.name, { anchorOutputSize: fallbackAnchorOutputSize });
      }
    }
  }, [fallbackAnchorOutputSize, selectedAnchorOutputOption]);

  function pushLog(message: string) {
    setLog((items) => [...items, `${new Date().toLocaleTimeString()} ${message}`].slice(-80));
  }

  function handleConsoleScroll() {
    const element = consoleOutputRef.current;
    if (!element) return;
    consolePinnedToBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight <= 24;
  }

  function startPreviewResize(event: React.PointerEvent<HTMLDivElement>) {
    previewResizeRef.current = { pointerId: event.pointerId, startY: event.clientY, startHeight: previewHeight };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function movePreviewResize(event: React.PointerEvent<HTMLDivElement>) {
    const drag = previewResizeRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const nextHeight = Math.min(720, Math.max(300, drag.startHeight + event.clientY - drag.startY));
    setPreviewHeight(nextHeight);
  }

  function endPreviewResize(event: React.PointerEvent<HTMLDivElement>) {
    const drag = previewResizeRef.current;
    if (drag?.pointerId === event.pointerId) {
      previewResizeRef.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function streamEventsFromResult(result: unknown) {
    const data = result as {
      processing?: {
        streamEvents?: unknown;
        uiConcept?: { streamEvents?: unknown };
        widgets?: Array<{ streamEvents?: unknown }>;
        specialized?: { streamEvents?: unknown };
      };
      streamEvents?: unknown;
      events?: unknown;
    };
    const buckets = [
      data.processing?.streamEvents,
      data.processing?.specialized?.streamEvents,
      data.processing?.uiConcept?.streamEvents,
      data.streamEvents,
      data.events,
      ...(data.processing?.widgets?.map((widget) => widget.streamEvents) ?? [])
    ];
    return buckets
      .flatMap((events) => (Array.isArray(events) ? events : []))
      .map((event) => String(event))
      .filter(Boolean);
  }

  function readableStreamEvent(event: string) {
    const text = event.trim();
    if (!text) return "";
    if (text === "keepalive") return "连接保持中";
    if (text === "response.created") return "请求已创建";
    if (text === "response.in_progress") return "模型正在处理请求";
    if (text === "response.output_item.added") return "模型开始输出新内容";
    if (text === "response.content_part.added") return "开始接收文本说明";
    if (text === "response.content_part.done") return "文本说明接收完成";
    if (text === "response.output_text.delta") return "正在接收文本说明片段";
    if (text.startsWith("response.output_text.done")) return text.replace("response.output_text.done chars=", "文本说明完成，字符数 ");
    if (text === "response.image_generation_call.in_progress") return "图片生成任务已启动";
    if (text === "response.image_generation_call.generating") return "正在生成图片";
    if (text === "response.image_generation_call.partial_image") return "收到图片局部预览事件";
    if (text === "image_generation_call.result") return "图片结果已返回";
    if (text.startsWith("response.output_item.done item=image_generation_call")) return `图片生成调用结束（${text.includes("status=") ? text.split("status=").pop() : "状态未知"}）`;
    if (text.startsWith("response.output_item.done item=message")) return "模型消息输出完成";
    if (text.startsWith("response.completed")) {
      const status = text.match(/status=([^\s]+)/)?.[1] ?? "-";
      const model = text.match(/model=([^\s]+)/)?.[1] ?? "-";
      return `请求完成（状态 ${status}，模型 ${model}）`;
    }
    if (text.includes("mirrored anchor:")) return text.replace("mirrored anchor:", "本地镜像基准图：");
    if (text.includes("mirrored sheet:")) return text.replace("mirrored sheet:", "本地镜像序列图：");
    if (text.startsWith("pixel.cutout.start")) return text.replace("pixel.cutout.start", "开始背景透明化");
    if (text.startsWith("pixel.cutout.frame start")) return text.replace("pixel.cutout.frame start index=", "开始处理帧 ");
    if (text.startsWith("pixel.cutout.frame done")) return text.replace("pixel.cutout.frame done index=", "完成帧 ");
    if (text.startsWith("pixel.cutout.done")) return text.replace("pixel.cutout.done", "背景透明化完成");
    if (text.startsWith("rembg.cutout.start")) return text.replace("rembg.cutout.start", "开始逐帧透明化");
    if (text.startsWith("rembg.cutout.frame start")) return text.replace("rembg.cutout.frame start index=", "开始处理帧 ");
    if (text.startsWith("rembg.cutout.frame done")) return text.replace("rembg.cutout.frame done index=", "完成帧 ");
    if (text.startsWith("rembg.cutout.done")) return text.replace("rembg.cutout.done", "逐帧透明化完成");
    if (text.startsWith("pixel.normalize.start")) return text.replace("pixel.normalize.start", "开始归一化");
    if (text.startsWith("pixel.normalize.frame start")) return text.replace("pixel.normalize.frame start index=", "开始归一化帧 ");
    if (text.startsWith("pixel.normalize.frame done")) return text.replace("pixel.normalize.frame done index=", "完成归一化帧 ");
    if (text.startsWith("pixel.normalize.done")) return text.replace("pixel.normalize.done", "归一化完成");
    if (text === "task.cancel.requested") return "已请求中断，等待当前轮询返回";
    if (text.startsWith("seedance.task.submitted")) return text.replace("seedance.task.submitted", "Seedance 任务已提交");
    if (text.startsWith("seedance.task.poll")) return text.replace("seedance.task.poll", "Seedance 任务轮询");
    if (text.startsWith("seedance.task.done")) return text.replace("seedance.task.done", "Seedance 任务完成");
    if (text.startsWith("seedance.video.download start")) return "Seedance 视频生成完成，开始下载";
    if (text.startsWith("seedance.video.download done")) return text.replace("seedance.video.download done path=", "Seedance 视频已保存：");
    return `事件：${text}`;
  }

  async function cancelActiveTask() {
    if (!activeStreamSession || cancelRequested) return;
    setCancelRequested(true);
    pushLog(`请求中断：${busy ?? "当前任务"}`);
    try {
      await api(`/events/stream/${encodeURIComponent(activeStreamSession)}/cancel`, { method: "POST" }, false);
    } catch (error) {
      pushLog(`请求中断失败：${error instanceof Error ? error.message : String(error)}`);
      setCancelRequested(false);
    }
  }

  async function pollStreamEvents(label: string, sessionId: string, shouldContinue: () => boolean, seenEvents: string[]) {
    let next = 0;
    while (shouldContinue()) {
      try {
        const result = await api<StreamEventResponse>(`/events/stream/${encodeURIComponent(sessionId)}?${new URLSearchParams({ after: String(next) }).toString()}`, undefined, false);
        next = result.next;
        for (const event of result.events) {
          seenEvents.push(event.message);
          updateTaskProgressFromEvent(event.message);
          pushLog(`${label}：${readableStreamEvent(event.message)}`);
        }
      } catch {
        // Polling should never fail the generation request itself.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 300));
    }
  }

  function updateTaskProgressFromEvent(message: string) {
    if (message === "task.cancel.requested") {
      setTaskProgress((current) => (current ? { ...current, label: "中断中" } : current));
      return;
    }
    const match = message.match(/index=(\d+)\/(\d+)/);
    if (match) {
      const current = Number(match[1]);
      const total = Number(match[2]);
      if (Number.isFinite(current) && Number.isFinite(total) && total > 0) {
        setTaskProgress({ current: Math.min(current, total), total, label: readableStreamEvent(message) });
      }
      return;
    }
    const startMatch = message.match(/frames=(\d+)/);
    if (message.includes(".start") && startMatch) {
      const total = Number(startMatch[1]);
      if (Number.isFinite(total) && total > 0) setTaskProgress({ current: 0, total, label: readableStreamEvent(message) });
      return;
    }
    if (message.includes(".done")) {
      setTaskProgress((current) => (current ? { ...current, current: current.total, label: readableStreamEvent(message) } : current));
    }
  }

  function userIsAwayFromUi() {
    return document.visibilityState !== "visible" || !document.hasFocus();
  }

  async function notifyWhenAway(label: string, body = `${label} 已完成`) {
    if (!userIsAwayFromUi()) return;
    try {
      let allowed = await isPermissionGranted();
      if (!allowed) {
        const permission = await requestPermission();
        allowed = permission === "granted";
      }
      if (allowed) {
        sendNotification({
          title: "UnrealImageMaker",
          body
        });
      }
    } catch (error) {
      pushLog(`系统通知不可用：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function runAction<T>(
    label: string,
    action: (streamSession: string) => Promise<T>,
    onSuccess?: (result: T) => void | Promise<void>,
    options: RunActionOptions = {}
  ) {
    setBusy(label);
    const streamSession = crypto.randomUUID();
    setActiveStreamSession(streamSession);
    setCancelRequested(false);
    setTaskProgress(null);
    const seenStreamEvents: string[] = [];
    let polling = true;
    const pollTask = pollStreamEvents(label, streamSession, () => polling, seenStreamEvents);
    try {
      const result = await action(streamSession);
      setLastResult(result as Record<string, unknown>);
      await onSuccess?.(result);
      for (const event of streamEventsFromResult(result)) {
        if (!seenStreamEvents.includes(event)) {
          seenStreamEvents.push(event);
          pushLog(`${label}：${readableStreamEvent(event)}`);
        }
      }
      pushLog(`${label}完成`);
      if (options.notify !== false) {
        await notifyWhenAway(label);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushLog(`${label}失败：${message}`);
      if (options.notify !== false) {
        await notifyWhenAway(label, `${label} 失败：${message}`);
      }
    } finally {
      polling = false;
      await pollTask;
      api(`/events/stream/${encodeURIComponent(streamSession)}`, { method: "DELETE" }, false).catch(() => undefined);
      setActiveStreamSession(null);
      setCancelRequested(false);
      window.setTimeout(() => setTaskProgress(null), 600);
      setBusy(null);
    }
  }

  function addAssetFromManifest(manifest: Record<string, unknown>) {
    const id = String(manifest.id || crypto.randomUUID());
    const record: AssetRecord = {
      id,
      name: manifestName(manifest),
      type: manifestType(manifest),
      path: firstManifestPath(manifest),
      manifest
    };
    setCurrentManifest(manifest);
    setAssets((items) => [record, ...items.filter((item) => item.id !== id)].slice(0, 24));
  }

  async function refreshProjectAssets(root = projectRoot) {
    const normalizedRoot = normalizeProjectRootInput(root);
    const requestId = ++assetRefreshRequestRef.current;
    if (!normalizedRoot) {
      setAssets([]);
      return [];
    }
    const result = await api<ProjectAssetsResponse>(`/projects/assets?${new URLSearchParams({ project_root: normalizedRoot }).toString()}`);
    if (requestId === assetRefreshRequestRef.current && normalizeProjectRootInput(projectRootRef.current) === normalizedRoot) {
      setAssets(result.assets);
    }
    return result.assets;
  }

  async function refreshProjectWorkspace(root = projectRoot) {
    const normalizedRoot = normalizeProjectRootInput(root);
    const requestId = ++workspaceRefreshRequestRef.current;
    if (!normalizedRoot) {
      setWorkflowSlots({});
      return;
    }
    const result = await api<ProjectWorkspaceResponse>(`/projects/workspace?${new URLSearchParams({ project_root: normalizedRoot }).toString()}`);
    if (requestId === workspaceRefreshRequestRef.current && normalizeProjectRootInput(projectRootRef.current) === normalizedRoot) {
      setWorkflowSlots(result.workflowSlots && typeof result.workflowSlots === "object" ? result.workflowSlots : {});
      applyMcpUiState(result.mcpUiState);
    }
  }

  function pixelSettingsFromAsset(asset: AssetRecord | null): PixelAssetSettings {
    const settings = asset?.settings;
    const pixel = settings?.pixel;
    if (!pixel || typeof pixel !== "object") return {};
    const data = pixel as Record<string, unknown>;
    return {
      cellSize: typeof data.cellSize === "number" && Number.isFinite(data.cellSize) ? data.cellSize : undefined,
      anchorOutputSize: typeof data.anchorOutputSize === "string" ? data.anchorOutputSize : undefined
    };
  }

  function applyPixelAssetSettings(asset: AssetRecord) {
    const settings = pixelSettingsFromAsset(asset);
    if (settings.cellSize && settings.cellSize > 0) setPixelCellSize(settings.cellSize);
    if (settings.anchorOutputSize) setPixelAnchorOutputSize(settings.anchorOutputSize);
  }

  async function savePixelAssetSettings(assetId = selectedAsset?.id, displayName = selectedAsset?.name, patch: Partial<PixelAssetSettings> = {}) {
    if (!assetId) return;
    const record = await api<AssetRecord>(`/assets/${encodeURIComponent(assetId)}/settings`, {
      method: "PUT",
      body: JSON.stringify({
        project_root: projectRoot,
        display_name: displayName || assetName || assetId,
        settings: {
          pixel: {
            cellSize: patch.cellSize ?? pixelCellSize,
            anchorOutputSize: patch.anchorOutputSize ?? pixelAnchorOutputSize
          }
        }
      })
    });
    setAssets((items) => items.map((item) => (item.id === record.id ? { ...item, ...record } : item)));
  }

  function updatePixelCellSize(value: number) {
    const next = Number.isFinite(value) && value > 0 ? value : pixelCellSize;
    setPixelCellSize(next);
    if (selectedAsset) {
      void savePixelAssetSettings(selectedAsset.id, selectedAsset.name, { cellSize: next });
    }
  }

  function updatePixelAnchorOutputSize(value: string) {
    setPixelAnchorOutputSize(value);
    if (selectedAsset) {
      void savePixelAssetSettings(selectedAsset.id, selectedAsset.name, { anchorOutputSize: value });
    }
  }

  function applyMcpUiState(state?: McpUiState) {
    const revision = Number(state?.revision || 0);
    if (!state || !Number.isFinite(revision) || revision <= mcpUiRevisionRef.current) return;
    mcpUiRevisionRef.current = revision;
    if (state.mainTab === "pixel") setMainTab("pixel");
    if (state.mainTab === "game_ui") setMainTab("game_ui");
    if (state.assetName && state.mainTab === "game_ui") {
      setUiAssetName(state.assetName);
      setGameUiScreenName(state.assetName);
    } else if (state.assetName) {
      setAssetName(state.assetName);
    }
    if (state.pixelKind && ["character", "weapon", "decoration", "tilemap"].includes(state.pixelKind)) setPixelKind(state.pixelKind);
    if (state.pixelStage && ["concept", "south_anchor", "neutral_anchor", "direction_anchor", "sheet", "cutout", "normalize", "tilemap_seed", "tilemap_tileset"].includes(state.pixelStage)) {
      setPixelStage(state.pixelStage);
    }
    if (state.pixelAction) setPixelActionFromId(state.pixelAction);
    if (state.pixelDirection) setPixelDirection(state.pixelDirection);
    if (state.pixelSheetMode && ["direct", "video"].includes(state.pixelSheetMode)) setPixelSheetMode(state.pixelSheetMode);
    if (state.lastMessage) pushLog(`MCP：${state.lastMessage}`);
    const activeRoot = normalizeProjectRootInput(projectRootRef.current || projectRoot);
    if (activeRoot) {
      refreshProjectAssets(activeRoot).catch((error) => pushLog(error.message));
      refreshGameUiWorkspace().catch((error) => pushLog(error.message));
    }
  }

  async function saveWorkflowSlots(nextSlots: WorkflowSlots) {
    setWorkflowSlots(nextSlots);
    await api<ProjectWorkspaceResponse>("/projects/workspace/slots", {
      method: "PUT",
      body: JSON.stringify({ project_root: projectRoot, workflow_slots: nextSlots })
    });
  }

  async function setWorkflowSlot(group: WorkflowSlotGroup, key: string, value: WorkflowSlotValue) {
    const nextSlots: WorkflowSlots = {
      ...workflowSlots,
      [group]: {
        ...(workflowSlots[group] ?? {}),
        [key]: value
      }
    };
    await saveWorkflowSlots(nextSlots);
  }

  function roleMatches(version: AssetImageVersion, roles: string[]) {
    return roles.includes(version.role);
  }

  function slotAsset() {
    return selectedAsset;
  }

  function slotVersions(roles: string[], asset = slotAsset()) {
    return asset?.versions?.filter((version) => roleMatches(version, roles)) ?? [];
  }

  function resolveWorkflowSlot(group: WorkflowSlotGroup, key: string, roles: string[], label: string): ResolvedSlot | null {
    const slot = workflowSlots[group]?.[key];
    const fixedAsset = slot?.assetId ? assets.find((asset) => asset.id === slot.assetId) : null;
    const fixedVersion = fixedAsset?.versions?.find((version) => version.id === slot?.versionId && roleMatches(version, roles));
    if (slot?.mode === "fixed" && fixedAsset && fixedVersion) {
      return { group, key, label, roles, asset: fixedAsset, version: fixedVersion, mode: "fixed" };
    }
    const asset = slotAsset();
    const version = slotVersions(roles, asset)[0];
    if (!asset || !version) return null;
    return { group, key, label, roles, asset, version, mode: "auto" };
  }

  function currentPixelActionId() {
    const source = pixelAction === "custom" ? pixelCustomActionName : pixelAction;
    return source.trim() ? assetIdFromName(source) : "idle";
  }

  function currentSheetDirection() {
    return pixelKind === "character" ? pixelDirection : "single";
  }

  function currentVideoDirection() {
    if (pixelKind !== "character") return "single";
    return ["south", "west", "north", "east"].includes(pixelDirection) ? pixelDirection : "west";
  }

  function currentSheetRole() {
    return `sheet:${currentPixelActionId()}:${currentSheetDirection()}`;
  }

  function currentCutoutRole() {
    return `cutout:${currentPixelActionId()}:${currentSheetDirection()}`;
  }

  function currentVideoRole() {
    return `video:${currentPixelActionId()}:${currentVideoDirection()}`;
  }

  function currentTilemapRole() {
    return pixelTilemapStandard === "dual-grid-16" ? "tileset:dual-grid-16" : "tileset:47";
  }

  function currentTilemapPreviewRole() {
    return `preview:tilemap:${pixelTilemapStandard}`;
  }

  function runtimeRole(actionId = currentPixelActionId(), direction = currentSheetDirection()) {
    return `runtime:${actionId}:${direction}`;
  }

  function previewRole(actionId = currentPixelActionId(), direction = currentSheetDirection()) {
    return `preview:${actionId}:${direction}`;
  }

  function legacyRuntimeRole(actionId = currentPixelActionId()) {
    return `runtime:${actionId}`;
  }

  function legacyPreviewRole(actionId = currentPixelActionId()) {
    return `preview:${actionId}`;
  }

  function knownActionLabel(actionId: string) {
    if (actionId === "idle") return "待机";
    if (actionId === "walk") return "行走";
    if (actionId === "attack") return "攻击";
    return "";
  }

  function displayActionLabel(actionId: string) {
    const known = knownActionLabel(actionId);
    if (known) return known;
    if (actionId === currentPixelActionId() && pixelCustomActionName.trim()) return pixelCustomActionName.trim();
    return actionId.replace(/[_-]+/g, " ").trim() || "未命名动作";
  }

  function pixelMatrixActionLabel(actionKey: PixelMatrixActionKey) {
    return pixelMatrixActions.find((action) => action.key === actionKey)?.label || knownActionLabel(actionKey) || actionKey;
  }

  function pixelMatrixCellKey(actionKey: PixelMatrixActionKey, direction: PixelMatrixDirection) {
    return `${actionKey}:${direction}`;
  }

  function compareVersionTime(left: AssetImageVersion, right: AssetImageVersion) {
    const leftTime = new Date(left.createdAt).getTime();
    const rightTime = new Date(right.createdAt).getTime();
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return leftTime - rightTime;
    return (left.order ?? 0) - (right.order ?? 0);
  }

  function latestVersionForRole(role: string, asset = selectedAsset) {
    const matches = asset?.versions?.filter((version) => version.role === role) ?? [];
    return matches.sort(compareVersionTime).at(-1);
  }

  function latestVersionForRoles(roles: string[], asset = selectedAsset) {
    const matches = asset?.versions?.filter((version) => roles.includes(version.role)) ?? [];
    return matches.sort(compareVersionTime).at(-1);
  }

  function manifestReferencesVersion(version: AssetImageVersion | undefined) {
    if (!version || !selectedAsset?.manifest) return false;
    const files = selectedAsset.manifest.files as Array<{ path?: string; role?: string }> | undefined;
    return Boolean(files?.some((file) => file.path === version.path || file.role === version.role));
  }

  function currentManifestHasLegacyRuntimeLayout() {
    const manifest = selectedAsset?.manifest;
    if (!manifest) return false;
    const processing = manifest.processing as { normalization?: Record<string, unknown> } | undefined;
    const frames = manifest.frames as Array<{ trim_rect?: unknown; trimRect?: unknown }> | undefined;
    const hasOldTrim = frames?.some((frame) => frame.trim_rect || frame.trimRect) ?? false;
    const normalization = processing?.normalization;
    return hasOldTrim || normalization?.layoutMode !== "preserve_cell_origin" || normalization?.pipelineVersion !== "pixel-sheet-v2" || normalization?.apiContractVersion !== EXPECTED_API_CONTRACT_VERSION;
  }

  function pixelMatrixCellState(actionKey: PixelMatrixActionKey, direction: PixelMatrixDirection): PixelMatrixCellState {
    const actionId = pixelMatrixActions.find((action) => action.key === actionKey)?.id || actionKey;
    const sheet = latestVersionForRole(`sheet:${actionId}:${direction}`);
    const cutout = latestVersionForRole(`cutout:${actionId}:${direction}`);
    const runtime = latestVersionForRoles([runtimeRole(actionId, direction), legacyRuntimeRole(actionId)]);
    const preview = latestVersionForRoles([previewRole(actionId, direction), legacyPreviewRole(actionId)]);
    const video = latestVersionForRole(`video:${actionId}:${direction}`);
    const stale = Boolean(runtime && manifestReferencesVersion(runtime) && currentManifestHasLegacyRuntimeLayout());
    let status: PixelMatrixCellState["status"] = "missing";
    let statusLabel = "缺失";
    if (video) {
      status = "video";
      statusLabel = "有视频";
    }
    if (sheet) {
      status = "sheet";
      statusLabel = "已有 sheet";
    }
    if (cutout) {
      status = "cutout";
      statusLabel = "已透明化";
    }
    if (runtime || preview) {
      status = stale ? "stale" : "runtime";
      statusLabel = stale ? "建议重跑" : "完成";
    }
    return {
      key: pixelMatrixCellKey(actionKey, direction),
      actionKey,
      actionId,
      actionLabel: pixelMatrixActionLabel(actionKey),
      direction,
      directionLabel: pixelDirectionLabel(direction),
      sheet,
      cutout,
      runtime,
      preview,
      video,
      status,
      statusLabel,
      stale
    };
  }

  function extractActionIdFromRole(role: string) {
    const [kind, actionId] = role.split(":");
    if (!["sheet", "cutout", "runtime", "preview", "video"].includes(kind)) return "";
    return actionId || "";
  }

  function actionLabelFromId(actionId: string) {
    return displayActionLabel(actionId);
  }

  function setPixelActionFromId(actionId: string) {
    const normalized = assetIdFromName(actionId);
    setPixelAction(normalized || "idle");
    if (!knownActionLabel(normalized)) {
      setPixelCustomActionName(actionId.trim() || normalized || "自定义动作");
    }
  }

  const pixelMatrixActions: PixelMatrixAction[] = (() => {
    const byId = new Map<string, PixelMatrixAction>();
    const addAction = (id: string, source: PixelMatrixAction["source"]) => {
      const normalized = assetIdFromName(id);
      if (!id.trim() || normalized === "asset" || byId.has(normalized)) return;
      byId.set(normalized, {
        key: normalized,
        id: normalized,
        label: actionLabelFromId(normalized),
        source
      });
    };
    selectedAsset?.versions?.forEach((version) => addAction(extractActionIdFromRole(version.role), "asset"));
    addAction(currentPixelActionId(), "current");
    return Array.from(byId.values());
  })();
  const pixelActionOptions: CommandComboboxOption[] = (() => {
    const byValue = new Map<string, CommandComboboxOption>();
    const addOption = (value: string, label: string, description?: string) => {
      const normalized = assetIdFromName(value);
      if (!normalized || byValue.has(normalized)) return;
      byValue.set(normalized, { value: normalized, label, description });
    };
    pixelMatrixActions.forEach((action) => addOption(action.id, action.label, action.source === "asset" ? "当前资产已有动作" : "当前编辑动作"));
    addOption("idle", "待机", "常用动作");
    addOption("walk", "行走", "常用动作");
    addOption("attack", "攻击", "常用动作");
    return Array.from(byValue.values());
  })();
  const pixelMatrixDirections: PixelMatrixDirection[] = ["south", "north", "west", "east"];

  function selectedPixelMatrixCells() {
    return pixelMatrixActions
      .flatMap((action) => pixelMatrixDirections.map((direction) => pixelMatrixCellState(action.key, direction)))
      .filter((cell) => pixelMatrixSelection.includes(cell.key));
  }

  function selectPixelMatrixCell(actionKey: PixelMatrixActionKey, direction: PixelMatrixDirection) {
    const action = pixelMatrixActions.find((item) => item.key === actionKey);
    setPixelAction(actionKey);
    if (action && !knownActionLabel(action.id)) setPixelCustomActionName(action.label);
    setPixelDirection(direction);
    setPixelStage("sheet");
    setActivePreviewVersionId(null);
    setActivePreviewPath("");
    setActivePreviewLabel("");
  }

  function handlePixelMatrixCellClick(actionKey: PixelMatrixActionKey, direction: PixelMatrixDirection) {
    if (window.getSelection()?.toString()) return;
    selectPixelMatrixCell(actionKey, direction);
  }

  function togglePixelMatrixCell(actionKey: PixelMatrixActionKey, direction: PixelMatrixDirection) {
    const key = pixelMatrixCellKey(actionKey, direction);
    setPixelMatrixSelection((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  }

  function defaultSeedanceModel() {
    return normalizeSeedanceModel(seedanceModelDraft) || normalizeSeedanceModel(runtimeSettings?.seedanceModel) || DEFAULT_SEEDANCE_MODEL;
  }

  function defaultSeedanceResolution() {
    return seedanceResolutionDraft.trim() || runtimeSettings?.seedanceResolution || DEFAULT_SEEDANCE_RESOLUTION;
  }

  function currentSeedanceModel() {
    return normalizeSeedanceModel(pixelSeedanceModel) || defaultSeedanceModel();
  }

  function currentSeedanceResolution() {
    return pixelSeedanceResolution.trim() || defaultSeedanceResolution();
  }

  function seedanceResolutionOptions(model = defaultSeedanceModel(), fallbackResolution = defaultSeedanceResolution()) {
    return SEEDANCE_MODEL_RESOLUTIONS[normalizeSeedanceModel(model)] ?? [fallbackResolution || DEFAULT_SEEDANCE_RESOLUTION];
  }

  function updateSeedanceModelDraft(model: string) {
    const normalized = normalizeSeedanceModel(model);
    setSeedanceModelDraft(normalized);
    const options = SEEDANCE_MODEL_RESOLUTIONS[normalized];
    if (options?.length && !options.includes(seedanceResolutionDraft)) {
      setSeedanceResolutionDraft(options[0]);
    }
  }

  function updatePixelSeedanceModel(model: string) {
    const normalized = normalizeSeedanceModel(model);
    setPixelSeedanceModel(normalized);
    const options = SEEDANCE_MODEL_RESOLUTIONS[normalized];
    if (options?.length && !options.includes(currentSeedanceResolution())) {
      setPixelSeedanceResolution(options[0]);
    }
  }

  function southAnchorSlot() {
    return resolveWorkflowSlot("pixel", "southAnchor", ["anchor:south", "anchor:single"], "正面基准图");
  }

  function anchorConceptReferencePath() {
    return pixelConceptPath.trim() || latestVersionForRole("concept:box_art")?.path || "";
  }

  function directionAnchorSlot(directionOverride?: string) {
    const direction = directionOverride ?? (pixelKind === "character" ? pixelDirection : "single");
    return resolveWorkflowSlot("pixel", "directionAnchor", [`anchor:${direction}`], "方向基准图");
  }

  function anchorPathForDirection(direction: string) {
    if (pixelKind !== "character") {
      return directionAnchorSlot("single")?.version.path || latestVersionForRole("anchor:single")?.path || pixelAnchorPath.trim() || "";
    }
    if (direction === "south") {
      return southAnchorSlot()?.version.path || latestVersionForRole("anchor:south")?.path || "";
    }
    return directionAnchorSlot(direction)?.version.path || latestVersionForRole(`anchor:${direction}`)?.path || "";
  }

  function sheetSourceSlot() {
    return resolveWorkflowSlot("pixel", "sheetSource", [currentSheetRole()], "动画 Sheet 源图");
  }

  function cutoutSourceSlot() {
    return resolveWorkflowSlot("pixel", "cutoutSource", [currentSheetRole()], "透明化源图") ?? sheetSourceSlot();
  }

  function videoSourceSlot() {
    return resolveWorkflowSlot("pixel", "videoSource", [currentVideoRole()], "动作视频源");
  }

  function normalizeSourceSlot() {
    return resolveWorkflowSlot("pixel", "normalizeSource", [currentCutoutRole(), currentSheetRole()], "归一化源图") ?? cutoutSourceSlot();
  }

  function uiConceptSlot() {
    return resolveWorkflowSlot("gameUi", "concept", ["ui:concept"], "UI 概念图");
  }

  function resolvePreviewSlot() {
    if (mainTab === "game_ui") return uiConceptSlot();
    if (mainTab !== "pixel") return null;
    if (pixelStage === "neutral_anchor") return southAnchorSlot();
    if (pixelStage === "direction_anchor") return directionAnchorSlot() ?? southAnchorSlot();
    if (pixelStage === "cutout") return cutoutSourceSlot();
    if (pixelStage === "normalize") return normalizeSourceSlot();
    if (pixelStage === "sheet") return directionAnchorSlot() ?? southAnchorSlot();
    return null;
  }

  async function updateSlotsAfterGeneration(group: WorkflowSlotGroup, keys: string[]) {
    const currentGroup = workflowSlots[group] ?? {};
    const nextGroup = { ...currentGroup };
    for (const key of keys) {
      if (currentGroup[key]?.mode !== "fixed") {
        nextGroup[key] = { mode: "auto" };
      }
    }
    await saveWorkflowSlots({ ...workflowSlots, [group]: nextGroup });
  }

  async function updateSlotAfterGeneration(group: WorkflowSlotGroup, key: string) {
    await updateSlotsAfterGeneration(group, [key]);
  }

  function roleMatcherExact(value: string): BrowserRoleMatcher {
    return { type: "exact", value };
  }

  function roleMatcherPrefix(value: string): BrowserRoleMatcher {
    return { type: "prefix", value };
  }

  function roleMatcherMatches(version: AssetImageVersion, matcher: BrowserRoleMatcher) {
    return matcher.type === "prefix" ? version.role.startsWith(matcher.value) : version.role === matcher.value;
  }

  function isPreviewableImageVersion(version: AssetImageVersion) {
    return /\.(png|jpe?g|webp|gif)$/i.test(version.path);
  }

  function uniqueVersions(versions: AssetImageVersion[]) {
    const seen = new Set<string>();
    return versions.filter((version) => {
      if (seen.has(version.id)) return false;
      seen.add(version.id);
      return true;
    });
  }

  function slotToInputVersion(slot: ResolvedSlot | null) {
    return slot?.version && isPreviewableImageVersion(slot.version) ? [slot.version] : [];
  }

  function versionsByMatchers(matchers: BrowserRoleMatcher[]) {
    if (!selectedAsset?.versions || matchers.length === 0) return [];
    return selectedAsset.versions.filter((version) => isPreviewableImageVersion(version) && matchers.some((matcher) => roleMatcherMatches(version, matcher)));
  }

  function inputVersionsFromPreviousOutput(slot: ResolvedSlot | null, previousOutputMatchers: BrowserRoleMatcher[]) {
    return uniqueVersions([...slotToInputVersion(slot), ...versionsByMatchers(previousOutputMatchers)]);
  }

  function activePixelStageForBrowser() {
    if (pixelKind === "tilemap") return "tilemap";
    return pixelStage;
  }

  function browserVersionDate(version: AssetImageVersion) {
    const date = new Date(version.createdAt);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function currentImageBrowserSpec() {
    const empty = {
      title: selectedAsset ? "当前工序图片" : "未选择资产",
      inputVersions: [] as AssetImageVersion[],
      outputVersions: [] as AssetImageVersion[]
    };
    if (!selectedAsset) return empty;

    if (mainTab === "game_ui") {
      const isWidgetAsset = uiWidgetType;
      const widgetOutputMatchers =
        uiWidgetType === "button" || uiWidgetType === "panel" || uiWidgetType === "icon" ? [roleMatcherPrefix(`ui_widget:${uiWidgetType}:`)] : [];
      return {
        title: isWidgetAsset ? `UI ${uiWidgetTypeLabel(uiWidgetType)}` : "游戏 UI",
        inputVersions: slotToInputVersion(uiConceptSlot()),
        outputVersions: versionsByMatchers([roleMatcherExact("ui:concept"), ...widgetOutputMatchers])
      };
    }

    if (mainTab !== "pixel") return empty;

    const activeStage = activePixelStageForBrowser();
    if (activeStage === "concept") {
      return {
        title: pixelKindCopy(pixelKind).conceptTitle,
        inputVersions: [],
        outputVersions: versionsByMatchers([roleMatcherExact("concept:box_art")])
      };
    }
    if (activeStage === "south_anchor") {
      return {
        title: pixelKind === "character" ? "正面基准图" : pixelKindCopy(pixelKind).anchorTitle,
        inputVersions: inputVersionsFromPreviousOutput(null, [roleMatcherExact("concept:box_art")]),
        outputVersions: versionsByMatchers([roleMatcherExact(pixelKind === "character" ? "anchor:south" : "anchor:single")])
      };
    }
    if (activeStage === "neutral_anchor") {
      return {
        title: "中性姿态修正",
        inputVersions: inputVersionsFromPreviousOutput(southAnchorSlot(), [roleMatcherExact("anchor:south")]),
        outputVersions: versionsByMatchers([roleMatcherExact("anchor:south")])
      };
    }
    if (activeStage === "direction_anchor") {
      const direction = ["west", "north", "east"].includes(pixelDirection) ? pixelDirection : "west";
      return {
        title: `${pixelDirectionLabel(direction)}基准图`,
        inputVersions: inputVersionsFromPreviousOutput(southAnchorSlot(), [roleMatcherExact("anchor:south")]),
        outputVersions: versionsByMatchers([roleMatcherExact(`anchor:${direction}`)])
      };
    }
    if (activeStage === "sheet") {
      const direction = currentSheetDirection();
      const directionSlot = directionAnchorSlot();
      return {
        title: `${currentPixelActionLabel()}序列图`,
        inputVersions: uniqueVersions([
          ...slotToInputVersion(directionSlot ?? southAnchorSlot()),
          ...versionsByMatchers([roleMatcherExact(`anchor:${direction}`)]),
          ...(directionSlot ? [] : versionsByMatchers([roleMatcherExact("anchor:south"), roleMatcherExact("anchor:single")]))
        ]),
        outputVersions: versionsByMatchers([roleMatcherExact(currentSheetRole())])
      };
    }
    if (activeStage === "cutout") {
      return {
        title: "背景透明化",
        inputVersions: inputVersionsFromPreviousOutput(cutoutSourceSlot(), [roleMatcherExact(currentSheetRole())]),
        outputVersions: versionsByMatchers([roleMatcherExact(currentCutoutRole())])
      };
    }
    if (activeStage === "normalize") {
      return {
        title: "归一化结果",
        inputVersions: inputVersionsFromPreviousOutput(normalizeSourceSlot(), [roleMatcherExact(currentCutoutRole()), roleMatcherExact(currentSheetRole())]),
        outputVersions: versionsByMatchers([
          roleMatcherExact(runtimeRole()),
          roleMatcherExact(previewRole()),
          roleMatcherExact(legacyRuntimeRole()),
          roleMatcherExact(legacyPreviewRole())
        ])
      };
    }
    return {
      title: `${tilemapStandardOption.label}地形集`,
      inputVersions: [],
      outputVersions: versionsByMatchers([
        roleMatcherExact("source:tilemap:wang-5x3"),
        roleMatcherExact("seed:tilemap-3x3"),
        roleMatcherExact("source:tilemap:outer-material"),
        roleMatcherExact("source:tilemap:primary-material"),
        roleMatcherExact("guide:tilemap:outer-material-grid"),
        roleMatcherExact("guide:tilemap:primary-material-grid"),
        roleMatcherExact("source:tilemap:materials"),
        roleMatcherExact("source:tilemap:wang-5x3-hard"),
        roleMatcherExact("guide:tilemap:wang-5x3-grid"),
        roleMatcherExact("guide:tilemap:wang-5x3-edit-reference"),
        roleMatcherExact("source:tilemap:wang-5x3-work"),
        roleMatcherExact("mask:tilemap:wang-5x3-boundary"),
        roleMatcherExact(currentTilemapRole()),
        roleMatcherExact(currentTilemapPreviewRole())
      ])
    };
  }

  function treeFolder(id: string, name: string, versions: AssetImageVersion[]): ImageVersionTreeNode {
    const children = uniqueVersions(versions).map((version) => ({
      id: `${id}:${version.id}`,
      name: versionDisplayLabel(version),
      kind: "file" as const,
      version,
      path: version.path,
      roleLabel: versionRoleLabel(version.role),
      dateLabel: browserVersionDate(version)
    }));
    return {
      id,
      name,
      kind: "folder",
      count: children.length,
      children:
        children.length > 0
          ? children
          : [
              {
                id: `${id}:empty`,
                name: id === "input" ? "当前阶段没有输入图片" : "当前阶段还没有输出图片",
                kind: "empty" as const
              }
            ]
    };
  }

  function currentImageBrowserTree() {
    const spec = currentImageBrowserSpec();
    return {
      title: spec.title,
      data: [treeFolder("input", "输入", spec.inputVersions), treeFolder("output", "输出", spec.outputVersions)]
    };
  }

  async function clearWorkflowSlotReferences(versionId: string) {
    let changed = false;
    const nextSlots: WorkflowSlots = { ...workflowSlots };
    (["pixel", "gameUi"] as WorkflowSlotGroup[]).forEach((group) => {
      const currentGroup = workflowSlots[group];
      if (!currentGroup) return;
      const nextGroup = { ...currentGroup };
      Object.entries(currentGroup).forEach(([key, value]) => {
        if (value?.mode === "fixed" && value.versionId === versionId) {
          nextGroup[key] = { mode: "auto" };
          changed = true;
        }
      });
      if (changed) {
        nextSlots[group] = nextGroup;
      }
    });
    if (changed) {
      await saveWorkflowSlots(nextSlots);
      pushLog("被删除版本正在被槽位引用，已恢复为自动最新");
    }
  }

  async function deleteAssetVersion(version: AssetImageVersion) {
    if (!selectedAsset) return;
    try {
      await api<AssetRecord>(
        `/assets/${encodeURIComponent(selectedAsset.id)}/versions/${encodeURIComponent(version.id)}?${new URLSearchParams({ project_root: projectRoot }).toString()}`,
        { method: "DELETE" }
      );
      await clearWorkflowSlotReferences(version.id);
      if (activePreviewVersionId === version.id || activePreviewPath === version.path) {
        setActivePreviewVersionId(null);
        setActivePreviewPath("");
        setActivePreviewLabel("");
      }
      await refreshProjectAssets(projectRoot);
      pushLog(`已删除版本：${versionDisplayLabel(version)}`);
    } catch (error) {
      pushLog(`删除版本失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function handleSpecializedManifest(manifest: Record<string, unknown>) {
    addAssetFromManifest(manifest);
    const nextAssets = await refreshProjectAssets(projectRoot);
    const assetId = String(manifest.id || "");
    const assetNameValue = manifestName(manifest);
    const record = nextAssets.find((asset) => asset.id === assetId) ?? nextAssets.find((asset) => asset.name === assetNameValue) ?? null;
    if (record && isPixelAsset(record)) {
      await savePixelAssetSettings(record.id, record.name);
    }
    return record;
  }

  async function registerImageVersion(assetNameValue: string, imagePath: string, role: string, label?: string) {
    const record = await api<AssetRecord>("/assets/images/register", {
      method: "POST",
      body: JSON.stringify({
        project_root: projectRoot,
        asset_name: assetNameValue,
        image_path: imagePath,
        role,
        label: label || role
      })
    });
    await refreshProjectAssets(projectRoot);
    return record;
  }

  async function waitForBackend() {
    setBackend("checking");
    let restartedForVersionMismatch = false;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      try {
        const health = await api<HealthResponse>("/health");
        if (
          health.status === "ok" &&
          health.apiContractVersion === EXPECTED_API_CONTRACT_VERSION &&
          health.capabilities?.codexOAuthCallback === "fixed-loopback-manual-fallback" &&
          health.capabilities?.openAiBaseUrl === true &&
          health.capabilities?.bundledVideoFfmpeg === true &&
          health.capabilities?.videoThumbnails === true &&
          health.capabilities?.gameUiMcp === true
        ) {
          setBackend("online");
          return true;
        }
        const actualVersion = health.apiContractVersion || "未提供";
        pushLog(`检测到本地服务版本不匹配：前端需要 ${EXPECTED_API_CONTRACT_VERSION}，后端是 ${actualVersion}`);
        if (!restartedForVersionMismatch) {
          restartedForVersionMismatch = true;
          const status = await startBackendWorker();
          if (status) setWorkerStatus(status);
          await new Promise((resolve) => window.setTimeout(resolve, 900));
          continue;
        }
        break;
      } catch {
        if (attempt === 2 || attempt === 10) {
          const status = await startBackendWorker();
          if (status) setWorkerStatus(status);
          if (status?.error) pushLog(`后端自动启动失败：${status.error}`);
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }
    }
    const status = await tauriCommand<BackendWorkerStatus>("backend_worker_status");
    if (status) setWorkerStatus(status);
    setBackend("offline");
    return false;
  }

  async function refreshModels() {
    const result = await api<ModelsResponse>("/models");
    setModelCacheDir(result.cacheDir);
    setModels(result.models);
    setModelDependencies(result.dependencies || []);
  }

  async function refreshRuntimeSettings() {
    const result = await api<RuntimeSettings>("/settings/runtime");
    setRuntimeSettings(result);
    setOpenAiBaseUrlDraft(result.openAiBaseUrl || "https://api.openai.com/v1");
    setOpenAiMergeEditImagesDraft(result.openAiMergeEditImages !== false);
    setUnrealMcpUrlDraft(result.unrealMcpUrl);
    setNetworkProxyDraft(result.networkProxy || "");
    setSeedanceEndpointDraft(result.seedanceEndpoint || DEFAULT_SEEDANCE_ENDPOINT);
    setSeedanceModelDraft(normalizeSeedanceModel(result.seedanceModel) || DEFAULT_SEEDANCE_MODEL);
    setSeedanceResolutionDraft(result.seedanceResolution || DEFAULT_SEEDANCE_RESOLUTION);
    if (result.codexOAuth.configured && !result.hasOpenAiApiKey) setImageProvider("codex_oauth");
    if (result.modelCacheDir) setModelCacheDir(result.modelCacheDir);
  }

  async function saveRuntimeSettings() {
    await runAction(
      "应用设置",
      () =>
        api<RuntimeSettings>("/settings/runtime", {
          method: "POST",
          body: JSON.stringify({
            openai_api_key: openAiKeyDraft || null,
            openai_base_url: openAiBaseUrlDraft,
            openai_merge_edit_images: openAiMergeEditImagesDraft,
            unreal_mcp_url: unrealMcpUrlDraft,
            huggingface_token: huggingFaceTokenDraft || null,
            network_proxy: networkProxyDraft,
            seedance_api_key: seedanceKeyDraft || null,
            seedance_endpoint: seedanceEndpointDraft,
            seedance_model: normalizeSeedanceModel(seedanceModelDraft),
            seedance_resolution: seedanceResolutionDraft
          })
        }),
      (result) => {
        setRuntimeSettings(result);
        setImageProvider(result.codexOAuth.configured && !result.hasOpenAiApiKey ? "codex_oauth" : imageProvider);
        setOpenAiKeyDraft("");
        setHuggingFaceTokenDraft("");
        setSeedanceKeyDraft("");
        checkUnrealStatus().catch((error) => pushLog(error.message));
      },
      { notify: false }
    );
  }

  function pathJoinForMcp(root: string, ...parts: string[]) {
    const normalizedRoot = root.trim().replace(/[\\/]+$/, "");
    const joined = [normalizedRoot, ...parts].filter(Boolean).join("\\");
    return joined.replace(/\//g, "\\");
  }

  function normalizeMcpPath(path: string) {
    return path.trim().replace(/\//g, "\\");
  }

  function absoluteMcpRoot() {
    return normalizeMcpPath(mcpRuntimePaths?.root || runtimeSettings?.workspaceRoot || "");
  }

  function pixelMcpPythonPath() {
    return normalizeMcpPath(mcpRuntimePaths?.python || pathJoinForMcp(absoluteMcpRoot(), ".venv", "Scripts", "python.exe"));
  }

  function pixelMcpBackendPath() {
    return normalizeMcpPath(mcpRuntimePaths?.backend || pathJoinForMcp(absoluteMcpRoot(), "backend"));
  }

  function pixelMcpConfigJson() {
    const root = absoluteMcpRoot();
    if (!root) return "";
    return JSON.stringify(
      {
        mcpServers: {
          "unreal-image-maker-pixel": {
            command: pixelMcpPythonPath(),
            args: ["-m", "uim_core.mcp_server"],
            cwd: root,
            env: {
              UIM_CURRENT_PROJECT: normalizeMcpPath(projectRoot || ""),
              PYTHONPATH: pixelMcpBackendPath(),
              NO_PROXY: "127.0.0.1,localhost",
              no_proxy: "127.0.0.1,localhost"
            }
          }
        }
      },
      null,
      2
    );
  }

  async function copyPixelMcpConfig() {
    const config = pixelMcpConfigJson();
    if (!config) {
      pushLog("MCP 配置复制失败：运行设置尚未加载");
      return;
    }
    try {
      await navigator.clipboard.writeText(config);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = config;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    pushLog("已复制 Pixel MCP stdio 配置");
  }

  async function refreshMcpRuntimePaths() {
    const result = await tauriCommand<McpRuntimePaths>("mcp_runtime_paths");
    if (result) setMcpRuntimePaths(result);
  }

  function rememberRecentProject(rootValue: string, nameValue: string) {
    const root = normalizeProjectRootInput(rootValue);
    if (!root) return;
    const name = nameValue.trim() || projectNameFromRoot(root);
    const record: RecentProject = {
      root,
      name,
      lastOpenedAt: new Date().toISOString()
    };
    setRecentProjects((current) => {
      const next = [record, ...current.filter((item) => item.root.toLowerCase() !== root.toLowerCase())].slice(0, 8);
      saveRecentProjects(next);
      return next;
    });
  }

  function forgetRecentProject(rootValue: string) {
    const root = normalizeProjectRootInput(rootValue).toLowerCase();
    setRecentProjects((current) => {
      const next = current.filter((item) => item.root.toLowerCase() !== root);
      saveRecentProjects(next);
      return next;
    });
  }

  function disconnectProject() {
    if (!project) return;
    const closedName = project.project.name || projectNameFromRoot(projectRoot);
    assetRefreshRequestRef.current += 1;
    workspaceRefreshRequestRef.current += 1;
    projectRootRef.current = "";
    setProject(null);
    setProjectRoot("");
    setProjectName("");
    setAssets([]);
    setWorkflowSlots({});
    setCurrentManifest(null);
    setLastResult(null);
    setActivePreviewVersionId(null);
    setActivePreviewPath("");
    setActivePreviewLabel("");
    setPendingDelete(null);
    setMainTab("pixel");
    setAssetName("新像素资产");
    setUiAssetName("新 UI 资产");
    pushLog(`已断开项目：${closedName}`);
  }

  async function ensureBackendOnlineForProjectAction() {
    if (backend === "online") return;
    if (await waitForBackendHealth(900)) {
      setBackend("online");
      return;
    }
    const online = await waitForBackend();
    if (!online) throw new Error("本地服务未连接，无法操作项目。请确认 Tauri 后端已启动。");
  }

  async function pickProjectFolder() {
    try {
      const selected = await openDialog({
        directory: true,
        multiple: false,
        defaultPath: normalizeProjectRootInput(projectRoot) || undefined,
        title: projectPanelMode === "create" ? "选择新项目文件夹" : "选择 UnrealImageMaker 项目文件夹"
      });
      if (!selected) return "";
      const root = normalizeProjectRootInput(Array.isArray(selected) ? selected[0] || "" : selected);
      setProjectRoot(root);
      if (projectPanelMode === "create") {
        setProjectName((current) => current.trim() || projectNameFromRoot(root));
      }
      return root;
    } catch (error) {
      throw new Error(
        `文件夹选择需要在 Tauri 窗口中使用，并启用官方 dialog 插件。${error instanceof Error && error.message ? ` ${error.message}` : ""}`
      );
    }
  }

  async function chooseAndCreateProject() {
    try {
      const root = await pickProjectFolder();
      if (root) await createProject(root);
    } catch (error) {
      pushLog(`选择项目文件夹失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function chooseAndOpenProject() {
    try {
      const root = await pickProjectFolder();
      if (root) await openProject(root);
    } catch (error) {
      pushLog(`选择项目文件夹失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function checkNetworkProxy() {
    await runAction(
      "测试网络代理",
      () => api<NetworkCheckResult>("/settings/network-check"),
      (result) => setNetworkCheck(result),
      { notify: false }
    );
  }

  async function createProject(rootValue = projectRoot) {
    await runAction("创建项目", async () => {
      await ensureBackendOnlineForProjectAction();
      const root = normalizeProjectRootInput(rootValue);
      const name = projectName.trim() || projectNameFromRoot(root);
      if (!root) throw new Error("请填写项目目录。");
      if (!name) throw new Error("请填写项目名。");
      assetRefreshRequestRef.current += 1;
      workspaceRefreshRequestRef.current += 1;
      projectRootRef.current = "";
      setProject(null);
      setProjectRoot(root);
      setProjectName(name);
      setAssets([]);
      setWorkflowSlots({});
      setCurrentManifest(null);
      const result = await api<ProjectOpenResult["project"]>("/projects", {
        method: "POST",
        body: JSON.stringify({ root, name, overwrite: true })
      });
      setProject({ project: result, lockedModels: [], missingModels: [] });
      projectRootRef.current = root;
      setProjectRoot(root);
      setProjectName(result.name || name);
      rememberRecentProject(root, result.name || name);
      await refreshProjectAssets(root);
      await refreshProjectWorkspace(root);
      return result;
    }, undefined, { notify: false });
  }

  async function openProject(rootValue = projectRoot, nameHint = "") {
    const root = normalizeProjectRootInput(rootValue);
    await runAction("打开项目", async () => {
      await ensureBackendOnlineForProjectAction();
      if (!root) throw new Error("请填写项目目录。");
      assetRefreshRequestRef.current += 1;
      workspaceRefreshRequestRef.current += 1;
      projectRootRef.current = "";
      setProject(null);
      setProjectRoot(root);
      setProjectName(nameHint || projectNameFromRoot(root));
      setAssets([]);
      setWorkflowSlots({});
      setCurrentManifest(null);
      const result = await api<ProjectOpenResult>("/projects/open", {
        method: "POST",
        body: JSON.stringify({ root })
      });
      setProject(result);
      projectRootRef.current = root;
      setProjectRoot(root);
      setProjectName(result.project.name || nameHint || projectNameFromRoot(root));
      rememberRecentProject(root, result.project.name || nameHint || projectNameFromRoot(root));
      await refreshProjectAssets(root);
      await refreshProjectWorkspace(root);
      return result;
    }, undefined, { notify: false });
  }

  async function generateSprite() {
    await runAction(
      "生成 Sprite",
      (streamSession) =>
        api<Record<string, unknown>>("/assets/sprite", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            prompt,
            asset_name: assetName,
            style_id: styleId,
            content_path: contentPath,
            image_provider: imageProvider,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        addAssetFromManifest(manifest);
        const outputPath = firstManifestPath(manifest);
        if (outputPath) {
          await registerImageVersion(manifestName(manifest), outputPath, "final", "final");
        } else {
          await refreshProjectAssets(projectRoot);
        }
      }
    );
  }

  async function startCodexOAuth() {
    await runAction(
      "开始 Codex OAuth",
      () => api<CodexOAuthFlow>("/auth/codex/start", { method: "POST" }),
      async (result) => {
        setCodexFlow(result);
        setCodexCallbackInput("");
        try {
          await openUrl(result.authorize_url);
        } catch (error) {
          const opened = window.open(result.authorize_url, "_blank", "noopener,noreferrer");
          if (!opened) {
            pushLog(`打开 OAuth 页面失败：${error instanceof Error ? error.message : String(error)}`);
          }
        }
        if (!result.auto_callback) {
          pushLog("OAuth 自动回调端口被占用，请粘贴浏览器最终回调网址完成绑定");
        }
        void pollCodexOAuth(result.state);
      },
      { notify: false }
    );
  }

  async function pollCodexOAuth(state: string) {
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      try {
        const result = await api<CodexOAuthPollResult>(`/auth/codex/poll/${encodeURIComponent(state)}`);
        if (result.status === "pending") continue;
        setCodexFlow(null);
        if (result.status === "success") {
          setRuntimeSettings((current) => (current ? { ...current, codexOAuth: result.codexOAuth } : current));
          setImageProvider("codex_oauth");
          pushLog("Codex OAuth 绑定完成");
          return;
        }
        pushLog(`Codex OAuth 绑定失败：${result.message || "未知错误"}`);
        return;
      } catch (error) {
        setCodexFlow(null);
        pushLog(`Codex OAuth 状态查询失败：${error instanceof Error ? error.message : String(error)}`);
        return;
      }
    }
    setCodexFlow(null);
    pushLog("Codex OAuth 绑定超时，请重新开始绑定");
  }

  async function completeCodexOAuthManually() {
    if (!codexFlow) {
      pushLog("没有正在进行的 Codex OAuth 会话");
      return;
    }
    await runAction(
      "完成 Codex OAuth",
      () =>
        api<CodexOAuthStatus>("/auth/codex/complete", {
          method: "POST",
          body: JSON.stringify({
            callback_input: codexCallbackInput,
            state: codexFlow.state
          })
        }),
      (result) => {
        setRuntimeSettings((current) => (current ? { ...current, codexOAuth: result } : current));
        setImageProvider("codex_oauth");
        setCodexFlow(null);
        setCodexCallbackInput("");
      },
      { notify: false }
    );
  }

  async function refreshCodexOAuth() {
    await runAction(
      "刷新 Codex OAuth",
      () => api<CodexOAuthStatus>("/auth/codex/refresh", { method: "POST" }),
      (result) => setRuntimeSettings((current) => (current ? { ...current, codexOAuth: result } : current)),
      { notify: false }
    );
  }

  async function disconnectCodexOAuth() {
    await runAction(
      "断开 Codex OAuth",
      () => api<CodexOAuthStatus>("/auth/codex/disconnect", { method: "POST" }),
      (result) => {
        setRuntimeSettings((current) => (current ? { ...current, codexOAuth: result } : current));
        if (imageProvider === "codex_oauth") setImageProvider("openai_api");
      },
      { notify: false }
    );
  }

  function currentProcessInput() {
    return absoluteProjectPath(projectRoot, processInput.trim());
  }

  function currentProcessAssetName() {
    return processAssetName.trim() || selectedAsset?.name || "Processed Image";
  }

  function currentProcessOutput(role: string) {
    return processOutput.trim() || projectPathForGenerated(projectRoot, currentProcessAssetName(), role);
  }

  async function processImage() {
    const inputPath = currentProcessInput();
    const outputPath = currentProcessOutput(processOperation);
    await runAction(
      "处理图片",
      () =>
        api<Record<string, unknown>>("/image/process", {
          method: "POST",
          body: JSON.stringify({ input_path: inputPath, output_path: outputPath, operation: processOperation, padding, scale, colors })
        }),
      async () => {
        setProcessOutput(outputPath);
        await registerImageVersion(currentProcessAssetName(), outputPath, processOperation, processOperation);
      }
    );
  }

  async function removeBackground() {
    const inputPath = currentProcessInput();
    const outputPath = currentProcessOutput("cutout");
    await runAction(
      "rembg 抠图",
      () =>
        api<Record<string, unknown>>("/rembg/remove", {
          method: "POST",
          body: JSON.stringify({ input_path: inputPath, output_path: outputPath, model_name: rembgModel })
        }),
      async () => {
        setProcessOutput(outputPath);
        await registerImageVersion(currentProcessAssetName(), outputPath, "cutout", "rembg");
      }
    );
  }

  function parseNumberList(value: string) {
    return value
      .split(/[,\s;]+/)
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isFinite(item));
  }

  function parseSamPoints(value: string) {
    const points = value
      .split(";")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => item.split(",").map((part) => Number(part.trim())))
      .filter((item) => item.length === 2 && item.every(Number.isFinite)) as Array<[number, number]>;
    return points.length ? points : null;
  }

  async function segmentWithSam() {
    const points = parseSamPoints(samPoints);
    const labels = parseNumberList(samLabels);
    const boxValues = parseNumberList(samBox);
    const inputPath = samImagePath.trim() || currentProcessInput();
    const outputPath = samMaskPath.trim() || projectPathForGenerated(projectRoot, currentProcessAssetName(), "mask");
    await runAction(
      "SAM 2.1 分割",
      () =>
        api<Record<string, unknown>>("/sam/segment", {
          method: "POST",
          body: JSON.stringify({
            image_path: inputPath,
            output_mask_path: outputPath,
            model_id: samModelId,
            points,
            labels: points && labels.length === points.length ? labels : null,
            box: boxValues.length === 4 ? boxValues : null
          })
        }),
      async () => {
        setSamImagePath(inputPath);
        setSamMaskPath(outputPath);
        await registerImageVersion(currentProcessAssetName(), outputPath, "mask", "SAM mask");
      }
    );
  }

  async function createSpritesheetManifest() {
    await runAction(
      "切分序列图",
      () =>
        api<Record<string, unknown>>("/manifests/spritesheet", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            sheet_path: sheetPath,
            asset_name: sheetName,
            style_id: styleId,
            cell_width: cellWidth,
            cell_height: cellHeight,
            content_path: contentPath
          })
        }),
      async (manifest) => {
        addAssetFromManifest(manifest);
        await refreshProjectAssets(projectRoot);
      }
    );
  }

  async function createUiManifest() {
    const states: Record<string, string> = {};
    if (uiNormal) states.normal = uiNormal;
    if (uiHover) states.hover = uiHover;
    if (uiPressed) states.pressed = uiPressed;
    if (uiDisabled) states.disabled = uiDisabled;
    const slice = nineSlice
      .split(",")
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isFinite(item));
    await runAction(
      "生成 UI Kit",
      () =>
        api<Record<string, unknown>>("/manifests/ui-kit", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: uiName,
            style_id: styleId,
            state_files: states,
            nine_slice: slice.length === 4 ? slice : null,
            content_path: `${contentPath}/UI`
          })
        }),
      async (manifest) => {
        addAssetFromManifest(manifest);
        await refreshProjectAssets(projectRoot);
      }
    );
  }

  function pixelKindLabel(kind: PixelKind) {
    return pixelKindCopy(kind).label;
  }

  function uiWidgetTypeLabel(type: UIWidgetType) {
    if (type === "button") return "按钮";
    if (type === "panel") return "面板";
    return "图标";
  }

  function modelStatusLabel(status: string) {
    if (status === "installed") return "已安装";
    if (status === "not_installed") return "未安装";
    if (status === "missing") return "缺失";
    return status;
  }

  function assetTypeLabel(type: string) {
    if (type === "sprite") return "精灵图";
    if (type === "texture") return "贴图";
    if (type === "ui_kit" || type === "ui") return "界面资产";
    if (type === "spritesheet") return "序列图";
    if (type === "tilemap") return "地形集";
    return type;
  }

  function normalizedPixelKind(value: unknown): PixelKind | null {
    return value === "character" || value === "weapon" || value === "decoration" || value === "tilemap" ? value : null;
  }

  function pixelKindFromAsset(asset: AssetRecord): PixelKind | null {
    const direct = normalizedPixelKind(asset.kind);
    if (direct) return direct;
    const manifest = asset.manifest ?? {};
    const manifestKind =
      normalizedPixelKind(manifest.kind) ||
      normalizedPixelKind(manifest.assetKind) ||
      normalizedPixelKind(manifest.asset_kind);
    if (manifestKind) return manifestKind;
    const processing = manifest.processing;
    if (processing && typeof processing === "object") {
      for (const value of Object.values(processing as Record<string, unknown>)) {
        if (!value || typeof value !== "object") continue;
        const kind = normalizedPixelKind((value as Record<string, unknown>).kind);
        if (kind) return kind;
      }
    }
    return null;
  }

  function isPixelAsset(asset: AssetRecord) {
    return pixelKindFromAsset(asset) !== null;
  }

  function isGameUiAsset(asset: AssetRecord) {
    return asset.kind === "game_ui";
  }

  function applyPixelKindSelection(kind: PixelKind, options: { resetStage?: boolean } = {}) {
    const currentSubject = pixelSubject.trim();
    const isDefaultSubject = Object.values(PIXEL_KIND_DEFAULT_SUBJECTS).some((subject) => subject && subject === currentSubject);
    const isDefaultI2vDescription = Object.values(DEFAULT_PIXEL_I2V_ACTION_DESCRIPTIONS).includes(pixelI2vActionDescription.trim());
    setPixelKind(kind);
    if (options.resetStage) {
      setPixelStage(kind === "tilemap" ? "tilemap_seed" : "concept");
    } else if (kind === "tilemap" && !["tilemap_seed", "tilemap_tileset"].includes(pixelStage)) {
      setPixelStage("tilemap_seed");
    } else if (kind !== "tilemap" && ["tilemap_seed", "tilemap_tileset"].includes(pixelStage)) {
      setPixelStage("concept");
    }
    if (kind !== "tilemap" && isDefaultSubject) {
      setPixelSubject(PIXEL_KIND_DEFAULT_SUBJECTS[kind]);
    }
    if (kind !== "tilemap" && isDefaultI2vDescription) {
      setPixelI2vActionDescription(DEFAULT_PIXEL_I2V_ACTION_DESCRIPTIONS[kind]);
    }
    if (kind !== "character") {
      setPixelDirection("south");
      setPixelAction("idle");
    }
    setPixelSheetMode(kind === "tilemap" ? "direct" : "video");
  }

  function versionRoleLabel(role?: string) {
    if (!role) return "图片";
    if (role === "source") return "源图";
    if (role === "final") return "成品图";
    if (role === "concept" || role === "box_art") return "概念图";
    if (role === "concept:box_art") return "概念图 / Box Art";
    if (role === "runtime_sheet") return "运行时序列图";
    if (role === "sheet") return "动作序列图";
    if (role.startsWith("sheet:")) {
      const [, action, direction] = role.split(":");
      return `动作序列图：${action || "动作"}${direction ? ` / ${pixelDirectionLabel(direction)}` : ""}`;
    }
    if (role.startsWith("cutout:")) {
      const [, action, direction] = role.split(":");
      return `透明化序列图：${action || "动作"}${direction ? ` / ${pixelDirectionLabel(direction)}` : ""}`;
    }
    if (role.startsWith("video:")) {
      const [, action, direction] = role.split(":");
      return `动作视频：${action || "动作"}${direction ? ` / ${pixelDirectionLabel(direction)}` : ""}`;
    }
    if (role.startsWith("runtime:")) return `运行时序列图：${role.slice("runtime:".length)}`;
    if (role === "seed:tilemap-3x3") return "旧地形风格参考图";
    if (role === "guide:tilemap:wang-5x3") return "5x3 Wang 约束图";
    if (role === "source:tilemap:outer-material") return "Outer 高分辨率材质";
    if (role === "source:tilemap:primary-material") return "Primary 高分辨率材质";
    if (role === "guide:tilemap:outer-material-grid") return "Outer 材质网格基准图";
    if (role === "guide:tilemap:primary-material-grid") return "Primary 材质网格基准图";
    if (role === "source:tilemap:materials") return "地形材质对";
    if (role === "source:tilemap:wang-5x3-hard") return "程序硬拼工作图";
    if (role === "guide:tilemap:wang-5x3-grid") return "WangTiles 网格基准图";
    if (role === "guide:tilemap:wang-5x3-edit-reference") return "WangTiles 上传前合并图";
    if (role === "source:tilemap:wang-5x3-work") return "边缘精修工作图";
    if (role === "mask:tilemap:wang-5x3-boundary") return "边界精修蒙版";
    if (role === "source:tilemap:wang-5x3") return "3行x5列 WangTiles图";
    if (role === "preview:tilemap:47-tile") return "47 图块测试拼图";
    if (role === "preview:tilemap:dual-grid-16") return "双网格测试拼图";
    if (role.startsWith("preview:")) return `预览图：${role.slice("preview:".length)}`;
    if (role === "tileset") return "地形集";
    if (role === "tileset:47") return "47 图块地形集";
    if (role === "tileset:dual-grid-16") return "双网格 16 地形集";
    if (role === "cutout") return "抠图结果";
    if (role === "mask") return "分割蒙版";
    if (role.startsWith("anchor:")) return `${pixelDirectionLabel(role.slice("anchor:".length))}基准图`;
    if (role.startsWith("ui:concept")) return "UI 概念图";
    if (role.startsWith("ui_html:")) return "UI HTML 原型";
    if (role.startsWith("ui_structure:")) return "UI 结构 JSON";
    if (role.startsWith("ui_widget:")) {
      const [, widgetType, state] = role.split(":");
      return `${uiWidgetTypeLabel((widgetType as UIWidgetType) || "button")}贴图${state ? ` / ${state}` : ""}`;
    }
    return role.replaceAll("_", " ");
  }

  function versionDisplayLabel(version: AssetImageVersion) {
    return versionRoleLabel(version.label || version.role);
  }

  function currentPixelActionLabel() {
    return displayActionLabel(currentPixelActionId());
  }

  function pixelDirectionDescription(direction: string) {
    if (direction === "south") return "south directly toward the camera";
    if (direction === "west") return "left in profile, body in a 3/4 left turn";
    if (direction === "east") return "right in profile, body in a 3/4 right turn";
    if (direction === "north") return "away from the camera, back view";
    return direction.replace("_", " ");
  }

  function pixelDirectionLabel(direction: string) {
    const labels: Record<string, string> = {
      south: "正面",
      west: "左侧",
      north: "背面",
      east: "右侧",
      north_west: "左后斜向",
      south_west: "左前斜向",
      north_east: "右后斜向（镜像）",
      south_east: "右前斜向（镜像）",
      single: "单方向"
    };
    return labels[direction] || direction;
  }

  function seedanceActionPrompt(direction = currentVideoDirection()) {
    if (pixelKind === "weapon") {
      return `Animate this single weapon into a short in-place state loop for a top-down 2D game:
${pixelI2vActionDescription}

Preserve the exact weapon design, sprite-like pixelated look, proportions, palette, silhouette, tip, handle, guard, and decorative details from the input image.
Keep the whole weapon fully visible in every frame.
Do not add a wielder, hand, arm, body, face, character, labels, arrows, or UI.
Do not change the weapon into a different item.

Keep the camera fixed and centered.
Keep the framing unchanged.
Keep the weapon centered on the same solid chroma background.
The background must remain pure #FF00FF magenta in every frame.
Do not change, shade, gradient, texture, shadow, or animate the #FF00FF background.
Keep the motion evenly paced with constant speed and stable timing.
Avoid sudden acceleration, slowdowns, pauses, jitter, or timing changes.
Do not turn the background into a floor, room, horizon, outdoor scene, perspective grid, shadow plane, or environment.

Motion:
- low-fidelity, readable, game-sprite reference motion
- clear beginning, peak, and recovery poses
- even-speed motion suitable for frame extraction
- subtle glint, charge, pulse, or restrained swing trail only when requested
- return cleanly to the starting silhouette for looping

One weapon only.
No scene.
No camera movement.
No zoom.
No large projectile or effect that hides the weapon silhouette.`;
    }
    if (pixelKind === "decoration") {
      return `Animate this single decoration prop into a short in-place idle loop for a top-down 2D game:
${pixelI2vActionDescription}

Preserve the exact prop design, sprite-like pixelated look, proportions, palette, silhouette, base, volume, and material details from the input image.
Keep the whole prop fully visible in every frame.
Do not add a character, hand, face, labels, arrows, UI, or extra props.
Do not change the prop into a different object.

Keep the camera fixed and centered.
Keep the framing unchanged.
Keep the prop centered on the same solid chroma background.
The background must remain pure #FF00FF magenta in every frame.
Do not change, shade, gradient, texture, shadow, or animate the #FF00FF background.
Keep the motion evenly paced with constant speed and stable timing.
Avoid sudden acceleration, slowdowns, pauses, jitter, or timing changes.
Do not turn the background into a floor, room, horizon, outdoor scene, perspective grid, shadow plane, or environment.

Motion:
- low-fidelity, readable, game-sprite reference motion
- clear beginning, peak, and recovery poses
- even-speed motion suitable for frame extraction
- subtle glow, float, flame flicker, pulse, or mechanical open-close motion only when requested
- return cleanly to the starting silhouette for looping

One decoration prop only.
No scene.
No camera movement.
No zoom.`;
    }
    const directionDescription = pixelDirectionDescription(direction);
    return `Animate this single character into this ${direction.toUpperCase()}-facing in-place action for a top-down 2D game:
${pixelI2vActionDescription}

The character must face ${directionDescription} for the entire clip.
Preserve the exact identity, sprite-like pixelated look, proportions, palette, costume, and silhouette from the input image.
Do not turn toward any other direction.
Do not pivot, rotate, or show a quarter-turn view.
Do not change body orientation at any point.

Keep the camera fixed and centered.
Keep the framing unchanged.
Keep the character centered on the same solid chroma background.
The background must remain pure #FF00FF magenta in every frame.
Do not change, shade, gradient, texture, shadow, or animate the #FF00FF background.
Keep the motion evenly paced with constant speed and stable timing.
Avoid sudden acceleration, slowdowns, pauses, jitter, or timing changes.
Do not turn the background into a floor, room, horizon, outdoor scene, perspective grid, shadow plane, or environment.

Motion:
- low-fidelity, readable, game-sprite reference motion
- clear beginning, peak, and recovery poses
- even-speed motion suitable for frame extraction
- motion stays centered and game-usable
- light clothing/equipment sway is allowed when relevant
- feet remain visible
- character does not translate across the frame

One character only.
No scene.
No extra props.
No labels.
No arrows.
No camera movement.
No zoom.
No unintended extra action beyond the requested motion.
No extra weapon swing, magic, fireball, spell effects, smoke, particles, glow, trails, or impacts unless explicitly requested in the action description.`;
  }

  async function generatePixelConcept() {
    await runAction(
      pixelKindCopy(pixelKind).conceptButton,
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/concept", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            subject: pixelSubject,
            asset_kind: pixelKind,
            style_id: "pixel_art",
            image_provider: imageProvider,
            content_path: `${contentPath}/Pixels`,
            output_size: pixelAnchorOutputSize,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        const output = firstManifestPath(manifest) || "";
        await handleSpecializedManifest(manifest);
        setPixelConceptPath(output);
        setPixelStage("south_anchor");
      }
    );
  }

  async function generatePixelAnchor(anchorStage: "south" | "neutral" | "direction") {
    const direction =
      pixelKind !== "character"
        ? "single"
        : anchorStage === "south" || anchorStage === "neutral"
          ? "south"
          : ["west", "north", "east"].includes(pixelDirection)
            ? pixelDirection
            : "west";
    const referenceAnchor = anchorStage === "neutral" || (pixelKind === "character" && direction !== "south") ? anchorPathForDirection("south") || null : null;
    const conceptReference = anchorStage === "south" && pixelAnchorUseConcept ? anchorConceptReferencePath() : "";
    const mirrorFrom = pixelKind === "character" && anchorStage === "direction" && direction === "east" && pixelMirrorEastFromWest ? "west" : null;
    await runAction(
      anchorStage === "neutral" ? "修正中性姿态基准图" : anchorStage === "direction" && mirrorFrom ? "镜像右侧基准图" : anchorStage === "direction" ? "生成方向基准图" : "生成正面基准图",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/anchor", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            subject: pixelSubject,
            asset_kind: pixelKind,
            direction,
            style_id: "pixel_art",
            image_provider: imageProvider,
            content_path: `${contentPath}/Pixels`,
            concept_path: conceptReference || null,
            reference_anchor_path: referenceAnchor,
            anchor_stage: anchorStage,
            dynamic_effect: pixelDynamicEffect,
            logical_frame_size: `${pixelCellSize}x${pixelCellSize}`,
            output_size: pixelAnchorOutputSize,
            mirror_from: mirrorFrom,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        const output = firstManifestPath(manifest) || "";
        await handleSpecializedManifest(manifest);
        setPixelAnchorPath(output);
        if (anchorStage === "south" || anchorStage === "neutral") await updateSlotAfterGeneration("pixel", "southAnchor");
        if (anchorStage === "direction") await updateSlotAfterGeneration("pixel", "directionAnchor");
        if (anchorStage === "south") setPixelStage("neutral_anchor");
        if (anchorStage === "neutral") setPixelStage("direction_anchor");
        if (anchorStage === "direction") setPixelStage("sheet");
      }
    );
  }

  async function generatePixelSheet() {
    const direction = pixelKind === "character" ? pixelDirection : "single";
    const resolvedAction = pixelAction === "custom" ? assetIdFromName(pixelCustomActionName) : pixelAction;
    const mirrorFrom = pixelKind === "character" && direction === "east" && pixelMirrorEastFromWest ? "west" : null;
    await runAction(
      mirrorFrom ? "镜像右侧动作序列图" : "生成动作序列图",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/sheet", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            subject: pixelSubject,
            asset_kind: pixelKind,
            action: resolvedAction,
            direction,
            style_id: "pixel_art",
            image_provider: imageProvider,
            content_path: `${contentPath}/Pixels`,
            columns: pixelColumns,
            rows: pixelRows,
            cell_size: pixelWorkCellSize,
            reference_path: anchorPathForDirection(direction) || null,
            attack_name: pixelAttackName,
            effect_color: pixelEffectColor,
            projectile_or_effect: pixelProjectileEffect,
            action_description: pixelAction === "custom" ? pixelActionDescription : "",
            mirror_from: mirrorFrom,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        const output = firstManifestPath(manifest) || "";
        await handleSpecializedManifest(manifest);
        setPixelSheetPath(output);
        setPixelCutoutPath("");
        await updateSlotsAfterGeneration("pixel", ["sheetSource", "cutoutSource", "normalizeSource"]);
        setPixelStage("cutout");
      }
    );
  }

  async function importPixelSheet() {
    try {
      const selected = await openDialog({
        multiple: false,
        directory: false,
        title: "选择像素序列帧图片",
        filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }]
      });
      const sheetPath = Array.isArray(selected) ? selected[0] : selected;
      if (!sheetPath || typeof sheetPath !== "string") return;
      const direction = currentSheetDirection();
      await runAction(
        "导入像素序列帧",
        () =>
          api<Record<string, unknown>>("/specialized/pixel/sheet-import", {
            method: "POST",
            body: JSON.stringify({
              project_root: projectRoot,
              asset_name: assetName,
              sheet_path: sheetPath,
              asset_kind: pixelKind,
              action: currentPixelActionId(),
              direction,
              style_id: "pixel_art",
              content_path: `${contentPath}/Pixels`,
              columns: pixelColumns,
              rows: pixelRows,
              cell_size: pixelWorkCellSize
            })
          }),
        async (manifest) => {
          const output = firstManifestPath(manifest) || "";
          await handleSpecializedManifest(manifest);
          setPixelSheetPath(output);
          setPixelCutoutPath("");
          await updateSlotsAfterGeneration("pixel", ["sheetSource", "cutoutSource", "normalizeSource"]);
          setPixelStage("cutout");
        }
      );
    } catch (error) {
      pushLog(`导入像素序列帧失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function removePixelSheetBackground() {
    const source = cutoutSourceSlot()?.version.path || pixelSheetPath.trim() || "";
    await runAction(
      "逐帧透明化序列图背景",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/cutout", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            sheet_path: source,
            asset_name: assetName,
            action: currentPixelActionId(),
            direction: currentSheetDirection(),
            columns: pixelColumns,
            rows: pixelRows,
            cell_width: pixelWorkCellSize,
            cell_height: pixelWorkCellSize,
            style_id: "pixel_art",
            content_path: `${contentPath}/Pixels`,
            model_name: rembgModel,
            mask_mode: pixelMaskMode,
            decontaminate_edges: pixelDecontaminateEdges,
            debug_artifacts: pixelDebugArtifacts,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        const output = firstManifestPath(manifest) || "";
        await handleSpecializedManifest(manifest);
        setPixelCutoutPath(output);
        await updateSlotAfterGeneration("pixel", "normalizeSource");
        setPixelStage("normalize");
      }
    );
  }

  async function normalizePixelSheet() {
    const source = pixelCutoutPath.trim() || normalizeSourceSlot()?.version.path || pixelSheetPath.trim() || "";
    const resolvedAction = pixelAction === "custom" ? assetIdFromName(pixelCustomActionName) : pixelAction;
    await runAction(
      "归一化运行时序列图",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/normalize", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            sheet_path: source,
            asset_name: assetName,
            action: resolvedAction,
            direction: currentSheetDirection(),
            source_cell_width: pixelWorkCellSize,
            source_cell_height: pixelWorkCellSize,
            cell_width: pixelCellSize,
            cell_height: pixelCellSize,
            style_id: "pixel_art",
            content_path: `${contentPath}/Pixels`,
            chroma_key: [255, 0, 255],
            pixel_restore_mode: pixelRestoreMode,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        await handleSpecializedManifest(manifest);
      }
    );
  }

  function updateBatchTask(taskId: string, patch: Partial<PixelBatchTask>) {
    setPixelBatchQueue((current) => current.map((task) => (task.id === taskId ? { ...task, ...patch } : task)));
  }

  function appendBatchTaskLog(taskId: string, message: string) {
    setPixelBatchQueue((current) => current.map((task) => (task.id === taskId ? { ...task, logs: [...task.logs, message].slice(-24) } : task)));
  }

  async function runBatchApiStep<T>(taskId: string, label: string, action: (streamSession: string) => Promise<T>) {
    const streamSession = crypto.randomUUID();
    let polling = true;
    const pollTask = (async () => {
      let next = 0;
      while (polling) {
        try {
          const result = await api<StreamEventResponse>(`/events/stream/${encodeURIComponent(streamSession)}?${new URLSearchParams({ after: String(next) }).toString()}`, undefined, false);
          next = result.next;
          for (const event of result.events) {
            const readable = readableStreamEvent(event.message);
            appendBatchTaskLog(taskId, readable);
            pushLog(`${label}：${readable}`);
          }
        } catch {
          // Stream polling is best-effort for queue feedback.
        }
        await new Promise((resolve) => window.setTimeout(resolve, 300));
      }
    })();
    try {
      const result = await action(streamSession);
      for (const event of streamEventsFromResult(result)) {
        const readable = readableStreamEvent(event);
        appendBatchTaskLog(taskId, readable);
        pushLog(`${label}：${readable}`);
      }
      return result;
    } finally {
      polling = false;
      await pollTask;
      api(`/events/stream/${encodeURIComponent(streamSession)}`, { method: "DELETE" }, false).catch(() => undefined);
    }
  }

  function batchAnchorForDirection(direction: PixelMatrixDirection) {
    return latestVersionForRole(`anchor:${direction}`)?.path || latestVersionForRole("anchor:south")?.path || latestVersionForRole("anchor:single")?.path || "";
  }

  async function generateSheetForCell(cell: PixelMatrixCellState, taskId: string) {
    const referencePath = batchAnchorForDirection(cell.direction);
    const mirrorFrom = pixelKind === "character" && cell.direction === "east" && pixelMirrorEastFromWest ? "west" : null;
    return runBatchApiStep(taskId, `${cell.actionLabel}/${cell.directionLabel} 生成 sheet`, (streamSession) =>
      api<Record<string, unknown>>("/specialized/pixel/sheet", {
        method: "POST",
        body: JSON.stringify({
          project_root: projectRoot,
          asset_name: assetName,
          subject: pixelSubject,
          asset_kind: pixelKind,
          action: cell.actionId,
          direction: cell.direction,
          style_id: "pixel_art",
          image_provider: imageProvider,
          content_path: `${contentPath}/Pixels`,
          columns: pixelColumns,
          rows: pixelRows,
          cell_size: pixelWorkCellSize,
          reference_path: referencePath || null,
          attack_name: pixelAttackName,
          effect_color: pixelEffectColor,
          projectile_or_effect: pixelProjectileEffect,
          action_description: knownActionLabel(cell.actionId) ? "" : pixelActionDescription,
          mirror_from: mirrorFrom,
          stream_session: streamSession
        })
      })
    );
  }

  async function cutoutCellSheet(cell: PixelMatrixCellState, taskId: string, sourcePath: string) {
    return runBatchApiStep(taskId, `${cell.actionLabel}/${cell.directionLabel} 背景透明化`, (streamSession) =>
      api<Record<string, unknown>>("/specialized/pixel/cutout", {
        method: "POST",
        body: JSON.stringify({
          project_root: projectRoot,
          sheet_path: sourcePath,
          asset_name: assetName,
          action: cell.actionId,
          direction: cell.direction,
          columns: pixelColumns,
          rows: pixelRows,
          cell_width: pixelWorkCellSize,
          cell_height: pixelWorkCellSize,
          style_id: "pixel_art",
          content_path: `${contentPath}/Pixels`,
          model_name: rembgModel,
          mask_mode: pixelMaskMode,
          decontaminate_edges: pixelDecontaminateEdges,
          debug_artifacts: pixelDebugArtifacts,
          stream_session: streamSession
        })
      })
    );
  }

  async function normalizeCellSheet(cell: PixelMatrixCellState, taskId: string, sourcePath: string) {
    return runBatchApiStep(taskId, `${cell.actionLabel}/${cell.directionLabel} 归一化`, (streamSession) =>
      api<Record<string, unknown>>("/specialized/pixel/normalize", {
        method: "POST",
        body: JSON.stringify({
          project_root: projectRoot,
          sheet_path: sourcePath,
          asset_name: assetName,
          action: cell.actionId,
          direction: cell.direction,
          source_cell_width: pixelWorkCellSize,
          source_cell_height: pixelWorkCellSize,
          cell_width: pixelCellSize,
          cell_height: pixelCellSize,
          style_id: "pixel_art",
          content_path: `${contentPath}/Pixels`,
          chroma_key: [255, 0, 255],
          pixel_restore_mode: pixelRestoreMode,
          stream_session: streamSession
        })
      })
    );
  }

  function batchStepsForCell(operation: PixelBatchOperation, cell: PixelMatrixCellState): PixelBatchStep[] {
    if (operation === "generate_missing") return cell.sheet ? [] : ["sheet"];
    if (operation === "cutout") return ["cutout"];
    if (operation === "normalize") return ["normalize"];
    return ["cutout", "normalize"];
  }

  async function executePixelBatchTask(task: PixelBatchTask) {
    updateBatchTask(task.id, { status: "running", error: undefined });
    appendBatchTaskLog(task.id, "开始执行");
    let cell = pixelMatrixCellState(task.actionKey, task.direction);
    let sheetPath = cell.sheet?.path || "";
    let cutoutPath = cell.cutout?.path || "";
    for (const step of task.steps) {
      updateBatchTask(task.id, { currentStep: step });
      if (step === "sheet") {
        const manifest = await generateSheetForCell(cell, task.id);
        await handleSpecializedManifest(manifest);
        sheetPath = firstManifestPath(manifest) || sheetPath;
        appendBatchTaskLog(task.id, `sheet 完成：${sheetPath}`);
      }
      if (step === "cutout") {
        const source = sheetPath || cell.sheet?.path;
        if (!source) throw new Error("缺少可透明化的 sheet");
        const manifest = await cutoutCellSheet(cell, task.id, source);
        await handleSpecializedManifest(manifest);
        cutoutPath = firstManifestPath(manifest) || cutoutPath;
        appendBatchTaskLog(task.id, `透明化完成：${cutoutPath}`);
      }
      if (step === "normalize") {
        const source = cutoutPath || cell.cutout?.path || sheetPath || cell.sheet?.path;
        if (!source) throw new Error("缺少可归一化的 sheet/cutout");
        const manifest = await normalizeCellSheet(cell, task.id, source);
        await handleSpecializedManifest(manifest);
        appendBatchTaskLog(task.id, "归一化完成");
      }
      cell = pixelMatrixCellState(task.actionKey, task.direction);
    }
    updateBatchTask(task.id, { status: "done", currentStep: undefined });
  }

  async function runPixelBatch(operation: PixelBatchOperation, onlyTask?: PixelBatchTask) {
    const cells = onlyTask ? [pixelMatrixCellState(onlyTask.actionKey, onlyTask.direction)] : selectedPixelMatrixCells();
    const tasks = cells
      .map((cell) => ({
        id: onlyTask?.id || crypto.randomUUID(),
        actionKey: cell.actionKey,
        actionId: cell.actionId,
        direction: cell.direction,
        steps: onlyTask?.steps || batchStepsForCell(operation, cell),
        status: "queued" as PixelBatchTaskStatus,
        logs: onlyTask?.id ? [...onlyTask.logs, "重新排队"] : []
      }))
      .filter((task) => task.steps.length > 0);
    if (!tasks.length) {
      pushLog("没有需要执行的批处理任务。");
      return;
    }
    if (onlyTask) {
      setPixelBatchQueue((current) => current.map((task) => (task.id === onlyTask.id ? tasks[0] : task)));
    } else {
      setPixelBatchQueue(tasks);
    }
    setBusy("像素批处理");
    try {
      for (const task of tasks) {
        try {
          await executePixelBatchTask(task);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          updateBatchTask(task.id, { status: "failed", currentStep: undefined, error: message });
          appendBatchTaskLog(task.id, `失败：${message}`);
          pushLog(`${task.actionId}/${task.direction} 批处理失败：${message}`);
        }
      }
      await refreshProjectAssets(projectRoot);
      await updateSlotsAfterGeneration("pixel", ["sheetSource", "cutoutSource", "normalizeSource"]);
    } finally {
      setBusy(null);
    }
  }

  async function generateSeedanceVideo() {
    const direction = currentVideoDirection();
    const anchor = anchorPathForDirection(direction);
    const action = currentPixelActionId();
    await runAction(
      "生成图生视频动作",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/seedance-walk", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            anchor_path: anchor,
            action,
            direction,
            model: currentSeedanceModel(),
            resolution: currentSeedanceResolution(),
            prompt: seedanceActionPrompt(direction),
            seconds: pixelSeedanceSeconds,
            stream_session: streamSession
          })
        }),
      async (result) => {
        const path = String(result.path || "");
        if (path) {
          setPixelVideoPath(path);
          await refreshProjectAssets(projectRoot);
          await updateSlotAfterGeneration("pixel", "videoSource");
        }
      }
    );
  }

  function currentVideoSourcePath() {
    return pixelVideoPath.trim() || videoSourceSlot()?.version.path || "";
  }

  function videoSheetLayoutForFrameCount(frameCount: number) {
    const safeFrameCount = Math.max(1, frameCount);
    const columns = Math.min(5, safeFrameCount);
    const rows = Math.max(1, Math.ceil(safeFrameCount / columns));
    return { columns, rows };
  }

  function openVideoFramePicker() {
    const source = currentVideoSourcePath();
    if (!source) {
      pushLog("请先生成或填写动作视频路径。");
      return;
    }
    setVideoFramePickerOpen(true);
  }

  function captureCurrentVideoFrame(video: HTMLVideoElement) {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 144;
      canvas.height = 144;
      const context = canvas.getContext("2d");
      if (!context || !video.videoWidth || !video.videoHeight) return "";
      const scale = Math.min(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
      const width = Math.max(1, Math.round(video.videoWidth * scale));
      const height = Math.max(1, Math.round(video.videoHeight * scale));
      const x = Math.floor((canvas.width - width) / 2);
      const y = Math.floor((canvas.height - height) / 2);
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(video, x, y, width, height);
      return canvas.toDataURL("image/png");
    } catch {
      return "";
    }
  }

  function waitForDecodedVideoFrame(video: HTMLVideoElement) {
    return new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        resolve();
      };
      const timeout = window.setTimeout(finish, 450);
      const frameVideo = video as HTMLVideoElement & { requestVideoFrameCallback?: (callback: () => void) => number };
      if (frameVideo.requestVideoFrameCallback) {
        frameVideo.requestVideoFrameCallback(() => finish());
      } else {
        window.requestAnimationFrame(() => window.requestAnimationFrame(finish));
      }
    });
  }

  function seekVideoTo(video: HTMLVideoElement, time: number) {
    return new Promise<void>((resolve) => {
      const duration = Number(video.duration || videoPickerDuration || 0);
      const target = Math.max(0, duration ? Math.min(time, duration) : time);
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        video.removeEventListener("seeked", finish);
        waitForDecodedVideoFrame(video).then(resolve);
      };
      const timeout = window.setTimeout(finish, 1200);
      video.addEventListener("seeked", finish);
      video.currentTime = target;
      setVideoPickerCurrentTime(target);
    });
  }

  function clampVideoPickerTime(time: number, duration = Number(videoFramePickerRef.current?.duration || videoPickerDuration || 0)) {
    if (!Number.isFinite(time)) return 0;
    return Math.max(0, duration ? Math.min(time, duration) : time);
  }

  function seekVideoPickerPreview(time: number) {
    const target = clampVideoPickerTime(time);
    clearVideoSelectionPreview();
    const video = videoFramePickerRef.current;
    if (video) {
      video.pause();
      video.currentTime = target;
    }
    setVideoPickerCurrentTime(target);
  }

  function updateVideoRangeStart(value: number) {
    const duration = Number(videoFramePickerRef.current?.duration || videoPickerDuration || 0);
    const nextStart = clampVideoPickerTime(value, duration);
    const nextEnd = Math.max(nextStart, clampVideoPickerTime(videoRangeEnd || duration, duration));
    setVideoRangeStart(nextStart);
    setVideoRangeEnd(nextEnd);
    seekVideoPickerPreview(nextStart);
  }

  function updateVideoRangeEnd(value: number) {
    const duration = Number(videoFramePickerRef.current?.duration || videoPickerDuration || 0);
    const nextEnd = clampVideoPickerTime(value, duration);
    const nextStart = Math.min(clampVideoPickerTime(videoRangeStart, duration), nextEnd);
    setVideoRangeStart(nextStart);
    setVideoRangeEnd(nextEnd);
    seekVideoPickerPreview(nextEnd);
  }

  function currentVideoRange(duration = Number(videoFramePickerRef.current?.duration || videoPickerDuration || 0)) {
    const start = clampVideoPickerTime(Math.min(videoRangeStart, videoRangeEnd || duration), duration);
    const end = clampVideoPickerTime(Math.max(videoRangeStart, videoRangeEnd || duration), duration);
    return { start, end: Math.max(start, end) };
  }

  function makeVideoFrameSelection(time: number, thumbnail = ""): VideoFrameSelection {
    return {
      id: crypto.randomUUID(),
      time: Number(time.toFixed(3)),
      thumbnail,
      selected: false,
      loopHint: false
    };
  }

  function videoFrameCacheSourceKey() {
    return currentVideoSourcePath() || "inline-video";
  }

  function videoFrameCacheTimeKey(time: number, source = videoFrameCacheSourceKey()) {
    return `${source}#${Number(time.toFixed(3)).toFixed(3)}`;
  }

  function videoLoopScoreCacheKey(firstTime: number, candidateTime: number) {
    return `loop-score-v2#${videoFrameCacheTimeKey(firstTime)}>${videoFrameCacheTimeKey(candidateTime)}`;
  }

  function primeVideoThumbnailCacheFromSelections(selections: VideoFrameSelection[]) {
    const sourceKey = videoFrameCacheSourceKey();
    for (const selection of selections) {
      if (selection.thumbnail) {
        videoFrameThumbnailCacheRef.current.set(videoFrameCacheTimeKey(selection.time, sourceKey), selection.thumbnail);
      }
    }
  }

  async function captureVideoFrameThumbnails(times: number[]) {
    if (times.length === 0) return new Map<number, string>();
    const sourceKey = videoFrameCacheSourceKey();
    const uniqueTimes = Array.from(new Set(times.map((time) => Number(time.toFixed(3)))));
    const thumbnailsByTime = new Map<number, string>();
    const missingTimes: number[] = [];
    for (const time of uniqueTimes) {
      const cached = videoFrameThumbnailCacheRef.current.get(videoFrameCacheTimeKey(time, sourceKey));
      if (cached) {
        thumbnailsByTime.set(time, cached);
      } else {
        missingTimes.push(time);
      }
    }
    if (missingTimes.length === 0) return thumbnailsByTime;
    const source = currentVideoSourcePath();
    if (!source) {
      throw new Error("没有视频源，无法用 ffmpeg 截取缩略图。");
    }
    if (source) {
      try {
        const result = await api<VideoThumbnailResponse>("/specialized/pixel/video-thumbnails", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            video_path: source,
            frame_times: missingTimes,
            thumbnail_size: 384
          })
        });
        for (const frame of result.frames || []) {
          const time = Number(frame.time.toFixed(3));
          thumbnailsByTime.set(time, frame.thumbnail);
          videoFrameThumbnailCacheRef.current.set(videoFrameCacheTimeKey(time, sourceKey), frame.thumbnail);
        }
        if (missingTimes.every((time) => thumbnailsByTime.has(time))) return thumbnailsByTime;
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        if (detail === "Not Found" || detail.includes("404")) {
          throw new Error("后端缺少 ffmpeg 缩略图接口，说明当前前后端版本不一致。请重启 Tauri/后端后再取帧。");
        }
        throw new Error(`后端 ffmpeg 缩略图截取失败：${detail}`);
      }
    }
    throw new Error(`后端 ffmpeg 缩略图返回不完整：需要 ${missingTimes.length} 帧，实际 ${thumbnailsByTime.size} 帧。`);
  }

  async function hydrateVideoFrameSelectionThumbnails(times: number[]) {
    const thumbnailsByTime = await captureVideoFrameThumbnails(times);
    if (thumbnailsByTime.size === 0) return;
    setVideoFrameSelections((current) =>
      current.map((selection) => ({ ...selection, thumbnail: selection.thumbnail || thumbnailsByTime.get(Number(selection.time.toFixed(3))) || "" }))
    );
  }

  function clearVideoSelectionPreview() {
    videoSelectionPreviewingRef.current = false;
    videoLoopPreviewingRef.current = false;
    setVideoSelectionPreviewing(false);
    setVideoLoopPreviewing(false);
    if (videoSelectionPreviewTimerRef.current !== null) {
      window.clearTimeout(videoSelectionPreviewTimerRef.current);
      videoSelectionPreviewTimerRef.current = null;
    }
    setVideoSelectionPreviewIndex(null);
  }

  function stepVideoFrame(delta: number) {
    const video = videoFramePickerRef.current;
    if (!video) return;
    clearVideoSelectionPreview();
    video.pause();
    const frameStep = 1 / 24;
    const duration = Number(video.duration || videoPickerDuration || 0);
    const nextTime = Math.max(0, Math.min(duration || Number.POSITIVE_INFINITY, Number(video.currentTime || 0) + delta * frameStep));
    video.currentTime = nextTime;
    setVideoPickerCurrentTime(nextTime);
  }

  function videoPreviewFrameDelay() {
    const fps = Math.max(1, Math.min(60, Number(videoAutoFps) || 12));
    return Math.max(16, Math.round(1000 / fps));
  }

  function playVideoSelectionPreview() {
    const video = videoFramePickerRef.current;
    if (!video || videoFrameSelections.length === 0) return;
    if (videoSelectionPreviewingRef.current) {
      clearVideoSelectionPreview();
      return;
    }
    clearVideoSelectionPreview();
    video.pause();
    const selections = [...videoFrameSelections];
    const frameDelay = videoPreviewFrameDelay();
    let index = 0;
    videoSelectionPreviewingRef.current = true;
    setVideoSelectionPreviewing(true);
    const showNext = () => {
      if (!videoSelectionPreviewingRef.current) return;
      const selectionIndex = index % selections.length;
      const selection = selections[selectionIndex];
      setVideoSelectionPreviewIndex(selectionIndex);
      if (!selection.thumbnail) video.currentTime = selection.time;
      setVideoPickerCurrentTime(selection.time);
      index += 1;
      videoSelectionPreviewTimerRef.current = window.setTimeout(showNext, frameDelay);
    };
    showNext();
  }

  function selectedLoopFrameIndex(frames = videoFrameSelections) {
    const selectedIndex = frames.findIndex((selection) => selection.loopHint && selection.id === selectedLoopFrameId);
    if (selectedIndex >= 0) return selectedIndex;
    return frames.findIndex((selection) => selection.loopHint);
  }

  function handleVideoFrameTileClick(index: number) {
    const selection = videoFrameSelections[index];
    if (selection?.loopHint) {
      setSelectedLoopFrameId(selection.id);
      seekVideoFrameSelection(selection.time);
      return;
    }
    toggleVideoFrameSelection(index);
  }

  function playVideoLoopPreview() {
    const video = videoFramePickerRef.current;
    const loopIndex = selectedLoopFrameIndex();
    if (!video || loopIndex < 2) {
      pushLog("先寻找循环帧，再播放循环。");
      return;
    }
    if (videoLoopPreviewingRef.current) {
      clearVideoSelectionPreview();
      return;
    }
    clearVideoSelectionPreview();
    video.pause();
    const selections = videoFrameSelections.slice(0, loopIndex).map((selection, index) => ({ ...selection, originalIndex: index }));
    const frameDelay = videoPreviewFrameDelay();
    let index = 0;
    videoLoopPreviewingRef.current = true;
    setVideoLoopPreviewing(true);
    const showNext = () => {
      if (!videoLoopPreviewingRef.current) return;
      const selection = selections[index % selections.length];
      setVideoSelectionPreviewIndex(selection.originalIndex);
      if (!selection.thumbnail) video.currentTime = selection.time;
      setVideoPickerCurrentTime(selection.time);
      index += 1;
      videoSelectionPreviewTimerRef.current = window.setTimeout(showNext, frameDelay);
    };
    showNext();
  }

  function addCurrentVideoFrame() {
    const video = videoFramePickerRef.current;
    const time = Math.max(0, Number(video?.currentTime ?? videoPickerCurrentTime));
    if (!Number.isFinite(time)) return;
    const normalizedTime = Number(time.toFixed(3));
    if (videoFrameSelections.some((selection) => Math.abs(selection.time - normalizedTime) < 0.04)) {
      pushLog("这个时间点已经接近已选帧。");
      return;
    }
    const thumbnail = video ? captureCurrentVideoFrame(video) : "";
    setVideoFrameSelections((current) => [...current, makeVideoFrameSelection(normalizedTime, thumbnail)]);
  }

  function removeVideoFrameSelection(index: number) {
    clearVideoSelectionPreview();
    setVideoFrameSelections((current) => {
      const removed = current[index];
      if (removed?.id === selectedLoopFrameId) setSelectedLoopFrameId(null);
      return current.filter((_, currentIndex) => currentIndex !== index);
    });
  }

  function toggleVideoFrameSelection(index: number) {
    setVideoFrameSelections((current) => current.map((selection, currentIndex) => (currentIndex === index ? { ...selection, selected: !selection.selected } : selection)));
  }

  function setAllVideoFrameSelections(selected: boolean) {
    setVideoFrameSelections((current) => current.map((selection) => ({ ...selection, selected })));
  }

  function removeSelectedVideoFrames() {
    clearVideoSelectionPreview();
    setVideoFrameSelections((current) => {
      const selectedLoopRemoved = current.some((selection) => selection.selected && selection.id === selectedLoopFrameId);
      if (selectedLoopRemoved) setSelectedLoopFrameId(null);
      return current.filter((selection) => !selection.selected);
    });
  }

  function trimVideoFramesToLoopPoint() {
    const loopIndex = selectedLoopFrameIndex();
    if (loopIndex <= 1) {
      pushLog("还没有可裁剪的循环点。");
      return;
    }
    clearVideoSelectionPreview();
    setVideoFrameSelections((current) =>
      current.slice(0, loopIndex).map((selection) => ({
        ...selection,
        loopHint: false,
        loopScore: undefined
      }))
    );
    setSelectedLoopFrameId(null);
    pushLog(`已删除循环终点第 ${loopIndex + 1} 帧及后续帧，保留前 ${loopIndex} 帧用于循环。`);
  }

  function moveVideoFrameSelection(from: number, to: number) {
    if (from === to || from < 0 || to < 0) return;
    setVideoFrameSelections((current) => {
      if (from >= current.length || to >= current.length) return current;
      const next = [...current];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });
  }

  function handleVideoFrameDragStart(event: React.DragEvent<HTMLElement>, index: number) {
    event.dataTransfer.setData("text/plain", String(index));
    event.dataTransfer.effectAllowed = "move";
  }

  function handleVideoFrameDrop(event: React.DragEvent<HTMLElement>, index: number) {
    event.preventDefault();
    const from = Number(event.dataTransfer.getData("text/plain"));
    if (Number.isInteger(from)) moveVideoFrameSelection(from, index);
  }

  function seekVideoFrameSelection(time: number) {
    const video = videoFramePickerRef.current;
    clearVideoSelectionPreview();
    if (video) {
      video.currentTime = Math.max(0, time);
      setVideoPickerCurrentTime(Math.max(0, time));
    }
  }

  async function autoSelectVideoFramesByFps() {
    const video = videoFramePickerRef.current;
    const duration = Number(video?.duration || videoPickerDuration);
    const fps = Math.max(1, Math.min(60, Number(videoAutoFps) || 8));
    if (!Number.isFinite(duration) || duration <= 0) return;
    const { start, end } = currentVideoRange(duration);
    const step = 1 / fps;
    const tailGuard = Math.max(0.001, Math.min(0.1, step * 0.5));
    const sampleEnd = Math.max(0, Math.min(end, duration - tailGuard));
    const sampleStart = Math.min(start, sampleEnd);
    const times: number[] = [];
    const maxCandidateFrames = 240;
    for (let time = sampleStart; time <= sampleEnd + 0.0001; time += step) {
      times.push(Number(time.toFixed(3)));
      if (times.length >= maxCandidateFrames) break;
    }
    clearVideoSelectionPreview();
    setSelectedLoopFrameId(null);
    setVideoFrameThumbnailsLoading(true);
    pushLog(`按 ${fps} FPS 从当前区间取到 ${times.length} 帧，正在生成缩略图${times.length >= maxCandidateFrames ? "，已达到上限 240 帧" : ""}。`);
    try {
      const thumbnailsByTime = await captureVideoFrameThumbnails(times);
      setVideoFrameSelections(times.map((time) => makeVideoFrameSelection(time, thumbnailsByTime.get(Number(time.toFixed(3))) || "")));
      pushLog(`已生成 ${times.length} 个选帧，缩略图 ${thumbnailsByTime.size} 张。`);
    } finally {
      setVideoFrameThumbnailsLoading(false);
    }
  }

  function loadImageElement(src: string) {
    return new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("无法读取帧缩略图"));
      image.src = src;
    });
  }

  async function thumbnailFrameMetrics(thumbnail: string) {
    const image = await loadImageElement(thumbnail);
    const sourceCanvas = document.createElement("canvas");
    sourceCanvas.width = 96;
    sourceCanvas.height = 96;
    const sourceContext = sourceCanvas.getContext("2d");
    if (!sourceContext) return { histogram: [], pixels: [] };
    sourceContext.drawImage(image, 0, 0, 96, 96);
    const sourceData = sourceContext.getImageData(0, 0, 96, 96).data;
    const colorBins = new Map<string, number>();
    const sampleBorder = (x: number, y: number) => {
      const offset = (y * 96 + x) * 4;
      const key = `${Math.round(sourceData[offset] / 16)},${Math.round(sourceData[offset + 1] / 16)},${Math.round(sourceData[offset + 2] / 16)}`;
      colorBins.set(key, (colorBins.get(key) || 0) + 1);
    };
    for (let index = 0; index < 96; index += 1) {
      sampleBorder(index, 0);
      sampleBorder(index, 95);
      sampleBorder(0, index);
      sampleBorder(95, index);
    }
    const backgroundBin = [...colorBins.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || "15,15,15";
    const background = backgroundBin.split(",").map((value) => Math.max(0, Math.min(255, Number(value) * 16 + 8)));
    let minX = 96;
    let minY = 96;
    let maxX = -1;
    let maxY = -1;
    for (let y = 0; y < 96; y += 1) {
      for (let x = 0; x < 96; x += 1) {
        const offset = (y * 96 + x) * 4;
        const distance = Math.hypot(sourceData[offset] - background[0], sourceData[offset + 1] - background[1], sourceData[offset + 2] - background[2]);
        if (sourceData[offset + 3] > 8 && distance > 42) {
          minX = Math.min(minX, x);
          minY = Math.min(minY, y);
          maxX = Math.max(maxX, x);
          maxY = Math.max(maxY, y);
        }
      }
    }
    const hasForeground = maxX >= minX && maxY >= minY;
    const padding = 5;
    const cropX = hasForeground ? Math.max(0, minX - padding) : 0;
    const cropY = hasForeground ? Math.max(0, minY - padding) : 0;
    const cropRight = hasForeground ? Math.min(95, maxX + padding) : 95;
    const cropBottom = hasForeground ? Math.min(95, maxY + padding) : 95;
    const cropWidth = Math.max(1, cropRight - cropX + 1);
    const cropHeight = Math.max(1, cropBottom - cropY + 1);
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 64;
    const context = canvas.getContext("2d");
    if (!context) return { histogram: [], pixels: [] };
    context.fillStyle = "rgb(255, 255, 255)";
    context.fillRect(0, 0, 64, 64);
    context.drawImage(sourceCanvas, cropX, cropY, cropWidth, cropHeight, 0, 0, 64, 64);
    const data = context.getImageData(0, 0, 64, 64).data;
    const histogram = Array.from({ length: 256 }, () => 0);
    const pixels: number[] = [];
    for (let index = 0; index < data.length; index += 4) {
      const gray = Math.max(0, Math.min(255, Math.round(data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114)));
      const distance = Math.hypot(data[index] - background[0], data[index + 1] - background[1], data[index + 2] - background[2]);
      const weight = distance > 42 ? 1 : 0;
      histogram[gray] += weight;
      pixels.push(weight ? gray : 255);
    }
    return { histogram, pixels };
  }

  async function cachedThumbnailFrameMetrics(selection: VideoFrameSelection) {
    const cacheKey = videoFrameCacheTimeKey(selection.time);
    const cached = videoFrameMetricCacheRef.current.get(cacheKey);
    if (cached) return cached;
    const metrics = await thumbnailFrameMetrics(selection.thumbnail);
    videoFrameMetricCacheRef.current.set(cacheKey, metrics);
    return metrics;
  }

  function histogramCorrelation(left: number[], right: number[]) {
    if (!left.length || left.length !== right.length) return -1;
    const leftMean = left.reduce((sum, value) => sum + value, 0) / left.length;
    const rightMean = right.reduce((sum, value) => sum + value, 0) / right.length;
    let numerator = 0;
    let leftEnergy = 0;
    let rightEnergy = 0;
    for (let index = 0; index < left.length; index += 1) {
      const leftDelta = left[index] - leftMean;
      const rightDelta = right[index] - rightMean;
      numerator += leftDelta * rightDelta;
      leftEnergy += leftDelta * leftDelta;
      rightEnergy += rightDelta * rightDelta;
    }
    const denominator = Math.sqrt(leftEnergy * rightEnergy);
    return denominator > 0 ? numerator / denominator : 1;
  }

  function pixelSimilarity(left: number[], right: number[]) {
    if (!left.length || left.length !== right.length) return -1;
    let totalDifference = 0;
    for (let index = 0; index < left.length; index += 1) {
      totalDifference += Math.abs(left[index] - right[index]);
    }
    return 1 - totalDifference / (left.length * 255);
  }

  function cachedVideoLoopScore(first: VideoFrameSelection, candidate: VideoFrameSelection, firstMetrics: VideoFrameMetrics, candidateMetrics: VideoFrameMetrics) {
    const cacheKey = videoLoopScoreCacheKey(first.time, candidate.time);
    const cached = videoLoopScoreCacheRef.current.get(cacheKey);
    if (cached) return cached;
    const histogram = histogramCorrelation(firstMetrics.histogram, candidateMetrics.histogram);
    const spatial = pixelSimilarity(firstMetrics.pixels, candidateMetrics.pixels);
    const score = spatial * 0.82 + Math.max(0, histogram) * 0.18;
    const result = { score, spatial, histogram };
    videoLoopScoreCacheRef.current.set(cacheKey, result);
    return result;
  }

  async function findVideoLoopFrame() {
    let queue = videoFrameSelections;
    if (queue.length < 3) {
      pushLog("至少需要 3 帧才能寻找循环闭合点。");
      return;
    }
    primeVideoThumbnailCacheFromSelections(queue);
    const sourceKey = videoFrameCacheSourceKey();
    const timesNeedingThumbnails = queue
      .filter((selection) => !selection.thumbnail && !videoFrameThumbnailCacheRef.current.get(videoFrameCacheTimeKey(selection.time, sourceKey)))
      .map((selection) => selection.time);
    const thumbnailsByTime = await captureVideoFrameThumbnails(timesNeedingThumbnails);
    queue = queue.map((selection) => ({
      ...selection,
      thumbnail:
        thumbnailsByTime.get(Number(selection.time.toFixed(3))) ||
        videoFrameThumbnailCacheRef.current.get(videoFrameCacheTimeKey(selection.time, sourceKey)) ||
        selection.thumbnail
    }));
    primeVideoThumbnailCacheFromSelections(queue);
    if (queue.some((selection) => !selection.thumbnail)) {
      pushLog("部分选帧还没有缩略图，无法完整计算循环候选。");
      return;
    }
    const metrics = await Promise.all(queue.map((selection) => cachedThumbnailFrameMetrics(selection)));
    const firstMetrics = metrics[0];
    let best: { index: number; score: number; spatial: number; histogram: number } | null = null;
    const minScore = Math.max(0, Math.min(1, videoLoopMinScore));
    const candidates = new Map<number, { score: number; spatial: number; histogram: number }>();
    for (let index = 2; index < metrics.length; index += 1) {
      const { score, spatial, histogram } = cachedVideoLoopScore(queue[0], queue[index], firstMetrics, metrics[index]);
      if (score >= minScore) {
        candidates.set(index, { score, spatial, histogram });
      }
      if (!best || score > best.score) {
        best = { index, score, spatial, histogram };
      }
    }
    if (!best) {
      setVideoFrameSelections(queue.map((selection) => ({ ...selection, loopHint: false, loopScore: undefined })));
      pushLog("帧数太少，无法寻找循环闭合点。");
      return;
    }
    const selectedCandidate = [...candidates.entries()].reduce<{ index: number; result: VideoLoopScore } | null>(
      (current, [index, result]) => (!current || result.score > current.result.score ? { index, result } : current),
      null
    );
    const selectedCandidateIndex = selectedCandidate?.index ?? null;
    setVideoFrameSelections(
      queue.map((selection, index) => ({
        ...selection,
        loopHint: candidates.has(index),
        loopScore: candidates.get(index)?.score
      }))
    );
    setSelectedLoopFrameId(selectedCandidateIndex !== null ? queue[selectedCandidateIndex]?.id ?? null : null);
    pushLog(
      selectedCandidate
        ? `找到 ${candidates.size} 个循环候选，默认选择相似度最高的第 ${selectedCandidate.index + 1} 帧，综合 ${selectedCandidate.result.score.toFixed(3)}。最佳综合 ${best.score.toFixed(3)}，像素 ${best.spatial.toFixed(3)}，颜色 ${best.histogram.toFixed(3)}。缓存命中 ${queue.length - timesNeedingThumbnails.length}/${queue.length} 帧。`
        : `最接近首帧的是第 ${best.index + 1} 帧，但综合 ${best.score.toFixed(3)} 低于阈值 ${minScore.toFixed(2)}，请人工确认。缓存命中 ${queue.length - timesNeedingThumbnails.length}/${queue.length} 帧。`
    );
  }

  async function exportVideoFrameQueue(exportType: VideoDebugExportType) {
    const source = currentVideoSourcePath();
    if (!source || videoFrameSelections.length === 0) {
      pushLog("没有可导出的选帧队列。");
      return;
    }
    const layout = videoSheetLayoutForFrameCount(videoFrameSelections.length);
    const labelMap: Record<VideoDebugExportType, string> = {
      png_sequence: "导出选帧 PNG",
      gif: "导出选帧 GIF",
      sheet: "导出临时 Sheet"
    };
    await runAction(
      labelMap[exportType],
      () =>
        api<Record<string, unknown>>("/specialized/pixel/video-debug-export", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            video_path: source,
            action: currentPixelActionId(),
            direction: currentVideoDirection(),
            export_type: exportType,
            style_id: "pixel_art",
            content_path: `${contentPath}/Pixels`,
            columns: layout.columns,
            rows: layout.rows,
            cell_size: pixelWorkCellSize,
            frame_times: videoFrameSelections.map((selection) => selection.time)
          })
        }),
      async (manifest) => {
        await handleSpecializedManifest(manifest);
        await refreshProjectAssets(projectRoot);
      }
    );
  }

  async function generatePixelSheetFromVideo() {
    const source = pixelVideoPath.trim() || videoSourceSlot()?.version.path || "";
    const action = currentPixelActionId();
    const direction = currentVideoDirection();
    if (videoFrameSelections.length === 0) {
      pushLog("请先在视频选帧弹窗里加入至少一帧。");
      return;
    }
    const layout = videoSheetLayoutForFrameCount(videoFrameSelections.length);
    await runAction(
      "视频抽帧打包序列图",
      () =>
        api<Record<string, unknown>>("/specialized/pixel/video-sheet", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            video_path: source,
            action,
            direction,
            style_id: "pixel_art",
            content_path: `${contentPath}/Pixels`,
            columns: layout.columns,
            rows: layout.rows,
            cell_size: pixelWorkCellSize,
            frame_times: videoFrameSelections.map((selection) => selection.time)
          })
        }),
      async (manifest) => {
        const output = firstManifestPath(manifest) || "";
        await handleSpecializedManifest(manifest);
        setPixelSheetPath(output);
        setPixelCutoutPath("");
        setPixelColumns(layout.columns);
        setPixelRows(layout.rows);
        await updateSlotsAfterGeneration("pixel", ["sheetSource", "cutoutSource", "normalizeSource"]);
        setPixelStage("cutout");
      }
    );
  }

  async function generateTilemapSeedConcept() {
    await runAction(
      "生成材质样例",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/tilemap-material-samples", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            subject: pixelTilemapSubject,
            outer_material: pixelTilemapOuterMaterial,
            primary_material: pixelTilemapPrimaryMaterial,
            tile_size: pixelTileSize,
            style_id: "pixel_art",
            image_provider: imageProvider,
            content_path: `${contentPath}/Tiles`,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        const record = await handleSpecializedManifest(manifest);
        const files = Array.isArray(manifest.files) ? manifest.files as Array<{ role?: string; path?: string }> : [];
        const outerFile = files.find((file) => file.role === "source:tilemap:outer-material");
        const primaryFile = files.find((file) => file.role === "source:tilemap:primary-material");
        const outputPath = outerFile?.path || primaryFile?.path || firstManifestPath(manifest) || "";
        if (outerFile?.path) setPixelTilemapOuterPath(outerFile.path);
        if (primaryFile?.path) setPixelTilemapPrimaryPath(primaryFile.path);
        if (outputPath) {
          setPixelTilemapSeedPath(outputPath);
          const version = record?.versions?.find((item) => item.path === outputPath);
          setActivePreviewVersionId(version?.id ?? null);
          setActivePreviewPath(outputPath);
          setActivePreviewLabel(`${record?.name || assetName} / ${version ? versionDisplayLabel(version) : "材质样例"}`);
          setPixelStage("tilemap_tileset");
        }
      }
    );
  }

  async function composeTilemapFromSeed() {
    await runAction(
      "生成 Dual-Grid 16 地形集",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/pixel/tilemap-dual-grid-generate", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            outer_material_path: pixelTilemapOuterPath || pixelTilemapSeedPath,
            primary_material_path: pixelTilemapPrimaryPath,
            subject: pixelTilemapSubject,
            tile_size: pixelTileSize,
            outer_material: pixelTilemapOuterMaterial,
            primary_material: pixelTilemapPrimaryMaterial,
            style_id: "pixel_art",
            image_provider: imageProvider,
            content_path: `${contentPath}/Tiles`,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        const record = await handleSpecializedManifest(manifest);
        const files = Array.isArray(manifest.files) ? manifest.files as Array<{ role?: string; path?: string }> : [];
        const previewFile = files.find((file) => file.role === "preview:tilemap:dual-grid-16");
        const tilesetFile = files.find((file) => file.role === "tileset:dual-grid-16");
        const outputPath = previewFile?.path || tilesetFile?.path || firstManifestPath(manifest) || "";
        if (outputPath) {
          const version = record?.versions?.find((item) => item.path === outputPath);
          setActivePreviewVersionId(version?.id ?? null);
          setActivePreviewPath(outputPath);
          setActivePreviewLabel(`${record?.name || assetName} / ${version ? versionDisplayLabel(version) : "Dual-Grid 16"}`);
        }
      }
    );
  }

  async function createTilemapManifest() {
    const endpoint = pixelTilemapStandard === "dual-grid-16" ? "/specialized/pixel/tilemap-dual-grid" : "/specialized/pixel/tilemap-47";
    await runAction(
      `生成 ${tilemapStandardOption.label}规则清单`,
      () =>
        api<Record<string, unknown>>(endpoint, {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: assetName,
            tileset_path: pixelTileSetPath,
            tile_size: pixelTileSize,
            style_id: "pixel_art",
            content_path: `${contentPath}/Tiles`
          })
        }),
      async (manifest) => {
        await handleSpecializedManifest(manifest);
      }
    );
  }

  async function generateUiConcept() {
    await runAction(
      "生成 UI 概念图",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/ui/concept", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: uiAssetName,
            game_description: uiGameDescription,
            layout: uiLayout,
            style_id: "semi_realistic_ui",
            image_provider: imageProvider,
            content_path: `${contentPath}/UI`,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        const output = firstManifestPath(manifest) || "";
        setUiConceptPath(output);
        const record = await handleSpecializedManifest(manifest);
        showGameUiConceptPreview(record, output);
        await updateSlotAfterGeneration("gameUi", "concept");
      }
    );
  }

  async function importUiConcept() {
    try {
      const selected = await openDialog({
        multiple: false,
        directory: false,
        title: "选择 UI 概念图",
        filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }]
      });
      const conceptPath = Array.isArray(selected) ? selected[0] : selected;
      if (!conceptPath || typeof conceptPath !== "string") return;
      await runAction(
        "导入 UI 概念图",
        () =>
          api<Record<string, unknown>>("/specialized/ui/concept-import", {
            method: "POST",
            body: JSON.stringify({
              project_root: projectRoot,
              asset_name: uiAssetName,
              concept_path: conceptPath,
              style_id: "semi_realistic_ui",
              content_path: `${contentPath}/UI`
            })
          }),
        async (manifest) => {
          const output = firstManifestPath(manifest) || "";
          setUiConceptPath(output);
          const record = await handleSpecializedManifest(manifest);
          showGameUiConceptPreview(record, output);
          await updateSlotAfterGeneration("gameUi", "concept");
        }
      );
    } catch (error) {
      pushLog(`导入 UI 概念图失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function generateUiWidget() {
    const slice = nineSlice
      .split(",")
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isFinite(item));
    await runAction(
      "生成 UI 控件贴图",
      (streamSession) =>
        api<Record<string, unknown>>("/specialized/ui/widget", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            asset_name: uiAssetName,
            widget_type: uiWidgetType,
            widget_description: uiWidgetDescription,
            concept_path: uiConceptPath.trim() || uiConceptSlot()?.version.path || null,
            style_id: "semi_realistic_ui",
            image_provider: imageProvider,
            content_path: `${contentPath}/UI`,
            nine_slice: uiWidgetType === "panel" && slice.length === 4 ? slice : null,
            stream_session: streamSession
          })
        }),
      async (manifest) => {
        await handleSpecializedManifest(manifest);
      }
    );
  }

  async function refreshGameUiWorkspace() {
    if (backend !== "online") return;
    const query = new URLSearchParams({ project_root: projectRoot }).toString();
    const [htmlResult, structuresResult, kitsResult] = await Promise.all([
      api<{ htmlPrototypes: GameUiHtmlPrototypeSummary[] }>(`/game-ui/html-prototypes?${query}`),
      api<{ structures: GameUiStructureSummary[] }>(`/game-ui/structures?${query}`),
      api<{ kits: GameUiTextureKitSummary[] }>(`/game-ui/texture-kits?${query}`)
    ]);
    setGameUiHtmlPrototypes(htmlResult.htmlPrototypes || []);
    setGameUiStructures(structuresResult.structures || []);
    setGameUiTextureKits(kitsResult.kits || []);
    if (!gameUiStructurePath && structuresResult.structures?.[0]?.path) setGameUiStructurePath(structuresResult.structures[0].path);
    const firstSelectableKit = kitsResult.kits?.find((kit) => kit.path) || kitsResult.kits?.[0];
    if (!gameUiSelectedKitPath && firstSelectableKit) setGameUiSelectedKitPath(gameUiKitSelectionValue(firstSelectableKit));
  }

  function gameUiConceptVersionChoices() {
    const targetAssetId = assetIdFromName(uiAssetName);
    const asset = assets.find((item) => item.id === targetAssetId) ?? (selectedAsset?.id === targetAssetId ? selectedAsset : null) ?? selectedAsset;
    return (asset?.versions ?? [])
      .filter((version) => version.role === "ui:concept")
      .sort((left, right) => compareVersionTime(right, left))
      .map((version) => ({ asset: asset!, version }));
  }

  async function loadGameUiHtmlContent(htmlPath: string) {
    const query = new URLSearchParams({ project_root: projectRoot, html_path: htmlPath }).toString();
    const result = await api<{ path: string; html: string }>(`/game-ui/html-content?${query}`);
    setGameUiHtmlPath(result.path);
    setGameUiHtmlDraft(result.html);
  }

  async function selectGameUiHtmlPrototype(value: string) {
    const prototype = gameUiHtmlPrototypes.find((item) => item.screenName === value || item.path === value);
    setGameUiScreenName(value);
    if (!prototype) {
      setGameUiHtmlPath("");
      return;
    }
    setGameUiScreenName(prototype.screenName);
    await loadGameUiHtmlContent(prototype.path);
  }

  function selectGameUiKitName(value: string) {
    const kit = gameUiTextureKits.find((item) => item.kitName === value || item.path === value);
    setGameUiKitName(kit?.kitName || value);
    if (kit) setGameUiSelectedKitPath(gameUiKitSelectionValue(kit));
  }

  function gameUiKitSelectionValue(kit: GameUiTextureKitSummary) {
    return kit.path || `in-progress:${kit.kitName}`;
  }

  function selectedGameUiTextureKit() {
    return gameUiTextureKits.find((kit) => gameUiKitSelectionValue(kit) === gameUiSelectedKitPath);
  }

  function gameUiSelectedChromaHex() {
    return (gameUiChromaPreset === "custom" ? gameUiCustomChromaHex : gameUiChromaPreset).trim().toUpperCase();
  }

  function gameUiSelectedChromaRgb() {
    const hex = gameUiSelectedChromaHex();
    const match = hex.match(/^#?([0-9A-F]{6})$/i);
    if (!match) return null;
    const raw = match[1];
    return [Number.parseInt(raw.slice(0, 2), 16), Number.parseInt(raw.slice(2, 4), 16), Number.parseInt(raw.slice(4, 6), 16)];
  }

  async function selectGameUiConceptVersion(versionId: string) {
    const found = gameUiConceptVersionChoices().find((item) => item.version.id === versionId);
    if (!found) {
      setUiConceptPath("");
      await setWorkflowSlot("gameUi", "concept", { mode: "auto" });
      return;
    }
    setUiConceptPath(found.version.path);
    setActivePreviewVersionId(found.version.id);
    setActivePreviewPath(found.version.path);
    setActivePreviewLabel(`${found.asset.name} / ${versionDisplayLabel(found.version)}`);
    await setWorkflowSlot("gameUi", "concept", { mode: "fixed", assetId: found.asset.id, versionId: found.version.id });
  }

  function showGameUiConceptPreview(record: AssetRecord | null, outputPath: string) {
    if (!outputPath) return;
    const version = record?.versions?.find((item) => item.path === outputPath && item.role === "ui:concept");
    setActivePreviewVersionId(version?.id ?? null);
    setActivePreviewPath(outputPath);
    setActivePreviewLabel(`${record?.name || uiAssetName} / ${version ? versionDisplayLabel(version) : "UI 概念图"}`);
  }

  async function copyGameUiDslPrompt() {
    await runAction(
      "复制 UI DSL 提示词",
      () => api<{ prompt: string }>(`/game-ui/dsl-prompt?${new URLSearchParams({ project_root: projectRoot }).toString()}`),
      async (result) => {
        try {
          await navigator.clipboard.writeText(result.prompt);
        } catch {
          const textarea = document.createElement("textarea");
          textarea.value = result.prompt;
          textarea.style.position = "fixed";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand("copy");
          textarea.remove();
        }
        pushLog("已复制 Game UI DSL 提示词");
      },
      { notify: false }
    );
  }

  async function saveGameUiHtml() {
    await runAction(
      "保存 UI HTML",
      () =>
        api<{ path: string }>("/game-ui/html", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            screen_name: gameUiScreenName,
            html: gameUiHtmlDraft
          })
        }),
      async (result) => {
        setGameUiHtmlPath(result.path);
        await refreshGameUiWorkspace();
        await refreshProjectAssets(projectRoot);
      }
    );
  }

  async function deleteGameUiHtml() {
    if (!gameUiHtmlPath) {
      pushLog("请先选择要删除的 HTML 原型");
      return;
    }
    await runAction(
      "删除 UI HTML",
      () =>
        api<{ deleted: string; removedVersions: number }>("/game-ui/html/delete", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            html_path: gameUiHtmlPath
          })
        }),
      async (result) => {
        setGameUiHtmlPath("");
        setGameUiHtmlDraft("");
        pushLog(`已删除 HTML 原型 ${result.deleted}，移除 ${result.removedVersions} 个资产版本引用`);
        await refreshGameUiWorkspace();
        await refreshProjectAssets(projectRoot);
      },
      { notify: false }
    );
  }

  async function bakeGameUiHtml() {
    await runAction(
      "烘焙 UI HTML",
      () =>
        api<{ path: string; structure: Record<string, unknown> }>("/game-ui/bake-html", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            screen_name: gameUiScreenName,
            html_path: gameUiHtmlPath.trim() || null,
            width: 1920,
            height: 1080
          })
        }),
      async (result) => {
        setGameUiStructurePath(result.path);
        await refreshGameUiWorkspace();
        await refreshProjectAssets(projectRoot);
      }
    );
  }

  async function deleteGameUiStructure() {
    if (!gameUiStructurePath) {
      pushLog("请先选择要删除的结构 JSON");
      return;
    }
    await runAction(
      "删除 UI 结构 JSON",
      () =>
        api<{ deleted: string; removedVersions: number }>("/game-ui/structure/delete", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            structure_path: gameUiStructurePath
          })
        }),
      async (result) => {
        setGameUiStructurePath("");
        setGameUiPreviewData(null);
        pushLog(`已删除结构 JSON ${result.deleted}，移除 ${result.removedVersions} 个资产版本引用`);
        await refreshGameUiWorkspace();
        await refreshProjectAssets(projectRoot);
      },
      { notify: false }
    );
  }

  async function registerGameUiTextureKit() {
    await runAction(
      "登记 UI 贴图组",
      () =>
        api<{ path: string }>("/game-ui/texture-kit/register", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            kit_name: gameUiKitName,
            files: JSON.parse(gameUiKitFilesJson),
            content_path: `${contentPath}/UI`
          })
        }),
      async (result) => {
        setGameUiSelectedKitPath(result.path);
        await refreshGameUiWorkspace();
      }
    );
  }

  async function generateGameUiTextureKit() {
    const chromaKey = gameUiSelectedChromaRgb();
    if (!chromaKey) {
      pushLog("Key Color 必须是 #RRGGBB 格式");
      return;
    }
    await runAction(
      "生成 UI 贴图组",
      (streamSession) =>
        api<{ path: string }>("/game-ui/texture-kit/generate", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            kit_name: gameUiKitName,
            concept_path: uiConceptPath.trim() || uiConceptSlot()?.version.path || null,
            widget_tokens: JSON.parse(gameUiWidgetTokensJson),
            provider: imageProvider,
            content_path: `${contentPath}/UI`,
            coverage: "default_full",
            mask_mode: "hybrid",
            decontaminate_edges: true,
            debug_artifacts: gameUiTextureDebugArtifacts,
            max_concurrency: gameUiTextureMaxConcurrency,
            chroma_key: chromaKey,
            stream_session: streamSession
          })
        }),
      async (result) => {
        setGameUiSelectedKitPath(result.path);
        await refreshGameUiWorkspace();
        await refreshProjectAssets(projectRoot);
      }
    );
  }

  async function exportGameUiUmg() {
    const selectedKit = selectedGameUiTextureKit();
    if (!selectedKit?.path) {
      pushLog("请先选择已登记的 UI 贴图组");
      return;
    }
    await runAction(
      "一键导出到 UE",
      () =>
        api<Record<string, unknown>>("/game-ui/export-umg", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            screen_name: gameUiScreenName,
            structure_path: gameUiStructurePath,
            texture_kit_path: selectedKit.path,
            content_path: `${contentPath}/UI`
          })
        }),
      (result) => {
        const widgetPath = typeof result.widgetPath === "string" ? result.widgetPath : "";
        if (result.mode === "mcp") {
          const mcp = result.mcp && typeof result.mcp === "object" ? (result.mcp as Record<string, unknown>) : {};
          const count = typeof mcp.widgetCount === "number" ? `，控件 ${mcp.widgetCount} 个` : "";
          pushLog(`已通过 MCP 写入 UE：${widgetPath}${count}`);
          return;
        }
        const script = typeof result.script === "string" ? result.script : "";
        const error = typeof result.mcpError === "string" ? result.mcpError : "未连接到 UE MCP";
        pushLog(`未写入 UE，已生成备用导入脚本：${script}；MCP：${error}`);
      }
    );
  }

  async function openGameUiSkinPreview() {
    const selectedKit = selectedGameUiTextureKit();
    if (!gameUiStructurePath || !selectedKit?.path) {
      pushLog("请先选择结构 JSON 和已登记的 UI 贴图组");
      return;
    }
    setGameUiPreviewLoading(true);
    setGameUiPreviewOpen(true);
    await runAction(
      "加载 UI 应用预览",
      () => {
        const query = new URLSearchParams({
          project_root: projectRoot,
          structure_path: gameUiStructurePath,
          texture_kit_path: selectedKit.path
        });
        return api<GameUiPreviewData>(`/game-ui/preview-data?${query.toString()}`);
      },
      (result) => setGameUiPreviewData(result),
      { notify: false }
    ).finally(() => setGameUiPreviewLoading(false));
  }

  function requestClearGameUiTextureKit() {
    const target = selectedGameUiTextureKit();
    if (!target) {
      pushLog("请先选择要清空的 UI 贴图组");
      return;
    }
    setGameUiClearTextureKitTarget(target);
  }

  async function clearGameUiTextureKit(target: GameUiTextureKitSummary) {
    await runAction(
      "清空 UI 贴图组",
      () =>
        api<{ deleted: string; kitName: string; deletedFiles: string[]; deletedDirs: string[] }>("/game-ui/texture-kit/clear", {
          method: "POST",
          body: JSON.stringify({
            project_root: projectRoot,
            texture_kit_path: target.path || "",
            kit_name: target.kitName
          })
        }),
      async (result) => {
        if (gameUiSelectedKitPath === gameUiKitSelectionValue(target)) setGameUiSelectedKitPath("");
        setGameUiPreviewData(null);
        pushLog(`已清空 UI 贴图组 ${result.kitName}：删除 ${result.deletedFiles.length} 个文件、${result.deletedDirs.length} 个目录`);
        await refreshGameUiWorkspace();
        await refreshProjectAssets(projectRoot);
      }
    );
  }

  async function deleteCurrentUiConcept() {
    const resolved = uiConceptSlot();
    if (!resolved) {
      pushLog("请先选择要删除的 UI 概念图");
      return;
    }
    await runAction(
      "删除 UI 概念图",
      () =>
        api<AssetRecord>(
          `/assets/${encodeURIComponent(resolved.asset.id)}/versions/${encodeURIComponent(resolved.version.id)}?${new URLSearchParams({ project_root: projectRoot }).toString()}`,
          { method: "DELETE" }
        ),
      async () => {
        await clearWorkflowSlotReferences(resolved.version.id);
        await setWorkflowSlot("gameUi", "concept", { mode: "auto" });
        if (uiConceptPath === resolved.version.path) setUiConceptPath("");
        await refreshProjectAssets(projectRoot);
        pushLog(`已删除 UI 概念图版本：${versionDisplayLabel(resolved.version)}`);
      },
      { notify: false }
    );
  }

  async function validateCurrentManifest() {
    if (!currentManifest) {
      pushLog("没有可校验的 manifest");
      return;
    }
    await runAction(
      "校验资产清单",
      () =>
        api<ValidationResult>("/manifests/validate", {
          method: "POST",
          body: JSON.stringify({ project_root: projectRoot, manifest: currentManifest })
        }),
      (result) => {
        setValidationResult(result);
        setMainTab("assets");
      },
      { notify: false }
    );
  }

  async function exportUnrealScript() {
    if (!currentManifest) {
      pushLog("没有可导出的 manifest");
      return;
    }
    await runAction("生成 Unreal 脚本", () =>
      api<Record<string, unknown>>("/unreal/python-script", {
        method: "POST",
        body: JSON.stringify({ project_root: projectRoot, manifest: currentManifest })
      })
    );
  }

  async function checkUnrealStatus() {
    await runAction(
      "检测 Unreal MCP",
      () => api<UnrealMcpStatus>("/unreal/mcp/status"),
      (result) => setUnrealStatus(result),
      { notify: false }
    );
  }

  async function installMarker(modelId: string) {
    await runAction(
      `登记 ${modelId}`,
      () => api<Record<string, unknown>>("/models/install-marker", { method: "POST", body: JSON.stringify({ model_id: modelId }) }),
      () => refreshModels().catch((error) => pushLog(error.message)),
      { notify: false }
    );
  }

  async function deleteModel(modelId: string) {
    await runAction(
      `删除 ${modelId}`,
      () => api<Record<string, unknown>>("/models/delete", { method: "POST", body: JSON.stringify({ model_id: modelId }) }),
      () => refreshModels().catch((error) => pushLog(error.message)),
      { notify: false }
    );
  }

  async function downloadSam(modelId: string) {
    await runAction(
      `下载 ${modelId}`,
      () => api<Record<string, unknown>>("/sam/download", { method: "POST", body: JSON.stringify({ model_id: modelId }) }),
      () => refreshModels().catch((error) => pushLog(error.message)),
      { notify: false }
    );
  }

  useEffect(() => {
    refreshMcpRuntimePaths().catch((error) => pushLog(error.message));
    waitForBackend().then((online) => {
      if (online) {
        refreshModels().catch((error) => pushLog(error.message));
        refreshRuntimeSettings().catch((error) => pushLog(error.message));
        checkUnrealStatus().catch((error) => pushLog(error.message));
      }
    });
  }, []);

  useEffect(() => {
    if (backend !== "online" || !project || !projectRoot) return;
    const timer = window.setInterval(() => {
      refreshProjectWorkspace(projectRoot).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [backend, projectRoot, project?.project.id]);

  useEffect(() => {
    if (backend !== "online" || !project || !projectRoot) return;
    refreshGameUiWorkspace().catch(() => undefined);
  }, [backend, projectRoot, project?.project.id]);

  useEffect(() => {
    if (!selectedAsset) return;
    if (selectedAsset.manifest) setCurrentManifest((current) => (current === selectedAsset.manifest ? current : selectedAsset.manifest!));
    const selectedPixelKind = pixelKindFromAsset(selectedAsset);
    if (selectedPixelKind) applyPixelKindSelection(selectedPixelKind);
    setPixelConceptPath(latestVersionForRole("concept:box_art", selectedAsset)?.path || "");
    applyPixelAssetSettings(selectedAsset);
  }, [selectedAsset?.id, selectedAssetManifestSignature, selectedAssetSettingsSignature]);

  useEffect(() => {
    const element = consoleOutputRef.current;
    if (!element || !consolePinnedToBottomRef.current) return;
    element.scrollTop = element.scrollHeight;
  }, [log]);

  useEffect(() => {
    if (!videoFramePickerOpen) clearVideoSelectionPreview();
    return () => clearVideoSelectionPreview();
  }, [videoFramePickerOpen]);

  useEffect(() => {
    const element = videoPreviewStageRef.current;
    if (!element || !videoFramePickerOpen) return;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setVideoPreviewStageSize({ width: Math.max(0, rect.width), height: Math.max(0, rect.height) });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [videoFramePickerOpen, videoSelectionPreviewing, videoLoopPreviewing]);

  useEffect(() => {
    if (!gameUiPreviewOpen) {
      setGameUiPreviewCanvasWidth(0);
      return;
    }
    const element = gameUiPreviewCanvasRef.current;
    if (!element) return;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setGameUiPreviewCanvasWidth(Math.max(0, rect.width));
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [gameUiPreviewOpen, gameUiPreviewData]);

  useEffect(() => {
    setPixelSheetPath("");
    setPixelCutoutPath("");
  }, [pixelKind, pixelDirection, pixelAction, pixelCustomActionName]);

  useEffect(() => {
    setPixelMatrixSelection([]);
  }, [activeAssetId, pixelKind]);

  useEffect(() => {
    setActivePreviewVersionId(null);
    setActivePreviewPath("");
    setActivePreviewLabel("");
  }, [mainTab, activeAssetId, pixelKind, pixelStage, pixelDirection, pixelAction, pixelSheetMode, pixelCustomActionName, uiWidgetType]);

  useEffect(() => {
    if (pixelStage === "direction_anchor" && pixelKind === "character" && !["west", "north", "east"].includes(pixelDirection)) {
      setPixelDirection("west");
    }
  }, [pixelStage, pixelKind, pixelDirection]);

  function TopTabs() {
    return (
      <nav className="top-tabs" aria-label="主功能">
        {tabs.map((tab) => (
          <button
            aria-selected={mainTab === tab.id}
            className={mainTab === tab.id ? "active" : ""}
            key={tab.id}
            onClick={() => setMainTab(tab.id)}
            role="tab"
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </nav>
    );
  }

  function RailContext() {
    if (mainTab === "pixel") {
      return (
        <div className="rail-facts">
          <span>
            <strong>流程</strong>
            <small>{pixelKindLabel(pixelKind)}</small>
          </span>
          <span>
            <strong>动作</strong>
            <small>{pixelKind === "tilemap" ? `${tilemapStandardOption.label}地形` : `${currentPixelActionLabel()} / ${pixelKind === "character" ? pixelDirectionLabel(pixelDirection) : "单方向"}`}</small>
          </span>
          <span>
            <strong>Seedance</strong>
            <small>{runtimeSettings?.seedanceConfigured ? "已配置" : "可选"}</small>
          </span>
        </div>
      );
    }

    if (mainTab === "game_ui") {
      return (
        <div className="rail-facts">
          <span>
            <strong>阶段</strong>
            <small>{uiConceptPath ? "控件贴图" : "界面概念图"}</small>
          </span>
          <span>
            <strong>控件</strong>
            <small>{uiWidgetTypeLabel(uiWidgetType)}</small>
          </span>
          <span>
            <strong>生成方式</strong>
            <small>{imageProvider === "codex_oauth" ? "ChatGPT 订阅" : "OpenAI 密钥"}</small>
          </span>
        </div>
      );
    }

    if (mainTab === "export") {
      return (
        <div className="rail-facts">
          <span>
            <strong>Unreal</strong>
            <small>{unrealStatus?.mode || "未知"}</small>
          </span>
          <span>
            <strong>内容路径</strong>
            <small>{contentPath}</small>
          </span>
          <span>
            <strong>问题</strong>
            <small>{issueCount}</small>
          </span>
        </div>
      );
    }

    if (mainTab === "models") {
      return (
        <div className="rail-facts">
          <span>
            <strong>已安装</strong>
            <small>{installedCount} / {models.length}</small>
          </span>
          <span>
            <strong>缓存目录</strong>
            <small>{modelCacheDir || runtimeSettings?.modelCacheDir || "-"}</small>
          </span>
          <span>
            <strong>缺失锁定</strong>
            <small>{project?.missingModels?.length ?? 0}</small>
          </span>
        </div>
      );
    }

    if (mainTab === "settings") {
      return (
        <div className="rail-facts">
          <span>
            <strong>OpenAI</strong>
            <small>{runtimeSettings?.hasOpenAiApiKey ? "已配置" : "未设置"}</small>
          </span>
          <span>
            <strong>Codex OAuth</strong>
            <small>{codexOAuth?.configured ? codexOAuth.email || "已绑定" : "未绑定"}</small>
          </span>
          <span>
            <strong>HF Token</strong>
            <small>{runtimeSettings?.hasHuggingFaceToken ? "已配置" : "可选"}</small>
          </span>
        </div>
      );
    }

    return (
      <div className="rail-facts">
        <span>
          <strong>已选资产</strong>
          <small>{selectedAsset?.name || "-"}</small>
        </span>
        <span>
          <strong>清单</strong>
          <small>{currentManifest ? "已生成" : "无"}</small>
        </span>
        <span>
          <strong>问题</strong>
          <small>{issueCount}</small>
        </span>
      </div>
    );
  }

  function selectAssetFromTree(asset: AssetRecord) {
    const selectedPixelKind = pixelKindFromAsset(asset);
    if (isGameUiAsset(asset) && !selectedPixelKind) {
      setMainTab("game_ui");
      setUiAssetName(asset.name);
      setGameUiScreenName(asset.name);
    } else if (selectedPixelKind) {
      setMainTab("pixel");
      setAssetName(asset.name);
      applyPixelKindSelection(selectedPixelKind);
    } else {
      setAssetName(asset.name);
    }
    if (asset.manifest) setCurrentManifest(asset.manifest);
  }

  function latestAssetThumbnailPath(asset: AssetRecord) {
    return asset.versions?.find(isPreviewableImageVersion)?.path || asset.path || "";
  }

  async function clearWorkflowSlotAssetReferences(assetId: string) {
    let changed = false;
    const nextSlots: WorkflowSlots = { ...workflowSlots };
    (["pixel", "gameUi"] as WorkflowSlotGroup[]).forEach((group) => {
      const currentGroup = workflowSlots[group];
      if (!currentGroup) return;
      const nextGroup = { ...currentGroup };
      Object.entries(currentGroup).forEach(([key, value]) => {
        if (value?.mode === "fixed" && value.assetId === assetId) {
          nextGroup[key] = { mode: "auto" };
          changed = true;
        }
      });
      if (changed) {
        nextSlots[group] = nextGroup;
      }
    });
    if (changed) {
      await saveWorkflowSlots(nextSlots);
      pushLog("被删除资产正在被槽位引用，已恢复为自动最新");
    }
  }

  async function deleteAssetFromTree(asset: AssetRecord) {
    try {
      await api<Record<string, unknown>>(
        `/assets/${encodeURIComponent(asset.id)}?${new URLSearchParams({ project_root: projectRoot }).toString()}`,
        { method: "DELETE" }
      );
      await clearWorkflowSlotAssetReferences(asset.id);
      const nextAssets = await refreshProjectAssets(projectRoot);
      if (selectedAsset?.id === asset.id) {
        const nextAsset = nextAssets[0] ?? null;
        if (nextAsset) {
          if (mainTab === "game_ui") {
            setUiAssetName(nextAsset.name);
          } else {
            setAssetName(nextAsset.name);
          }
          if (nextAsset.manifest) setCurrentManifest(nextAsset.manifest);
        } else {
          if (mainTab === "game_ui") {
            setUiAssetName("新 UI 资产");
          } else {
            setAssetName("新像素资产");
          }
          setCurrentManifest(null);
        }
        setActivePreviewVersionId(null);
        setActivePreviewPath("");
        setActivePreviewLabel("");
      }
      pushLog(`已删除资产：${asset.name}`);
    } catch (error) {
      pushLog(`删除资产失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  function AssetPreview(options: { overridePath?: string; overrideName?: string } = {}) {
    const PreviewPanel = AssetPreviewPanel as React.ComponentType<typeof options>;
    return (
      <Suspense fallback={null}>
        <PreviewPanel {...options} />
      </Suspense>
    );
  }

  function WorkerAlert() {
    if (!workerBlocked) return null;
    return (
      <div className="worker-alert" role="status">
        <div>
          <strong>本地服务未连接，生产动作暂不可用</strong>
          <span>应用会自动拉起本地 FastAPI 服务。若重试后仍离线，请查看 stderr 日志。</span>
          {workerStatus?.stderr_log && <code>{workerStatus.stderr_log}</code>}
        </div>
        <button className="secondary-action" onClick={() => waitForBackend()}>
          <RefreshCw size={15} />
          重连
        </button>
      </div>
    );
  }

  function SlotPicker({
    group,
    slotKey,
    label,
    roles,
    description
  }: {
    group: WorkflowSlotGroup;
    slotKey: string;
    label: string;
    roles: string[];
    description: string;
  }) {
    const asset = slotAsset();
    const versions = slotVersions(roles, asset);
    const resolved = resolveWorkflowSlot(group, slotKey, roles, label);
    const savedSlot = workflowSlots[group]?.[slotKey];
    const fixedVersionExists = Boolean(
      savedSlot?.assetId &&
        savedSlot.versionId &&
        assets.find((item) => item.id === savedSlot.assetId)?.versions?.some((version) => version.id === savedSlot.versionId && roleMatches(version, roles))
    );
    const selectValue = savedSlot?.mode === "fixed" && fixedVersionExists ? savedSlot.versionId || "" : "__auto";

    return (
      <section className="slot-card" aria-label={label}>
        <div className="slot-preview">
          {resolved ? (
            <img src={previewUrlForPath(projectRoot, resolved.version.path)} alt={label} />
          ) : (
            <FileImage size={24} />
          )}
        </div>
        <div className="slot-body">
          <div className="slot-title">
            <strong>{label}</strong>
            <span>{resolved?.mode === "fixed" ? "固定版本" : "自动最新"}</span>
          </div>
          <p>{description}</p>
          <label className="field compact">
            <span>输入版本</span>
            <select
              value={selectValue}
              onChange={(event) => {
                const versionId = event.target.value;
                const nextValue =
                  versionId === "__auto" || !asset
                    ? { mode: "auto" as const }
                    : { mode: "fixed" as const, assetId: asset.id, versionId };
                setWorkflowSlot(group, slotKey, nextValue).catch((error) => pushLog(error.message));
              }}
            >
              <option value="__auto">自动使用最新匹配版本</option>
              {versions.map((version) => (
                <option key={version.id} value={version.id}>
                  {versionDisplayLabel(version)} · {versionRoleLabel(version.role)}
                </option>
              ))}
            </select>
          </label>
          <small className="slot-path">{resolved?.version.path || `当前资产没有 ${roles.map(versionRoleLabel).join(" / ")} 版本`}</small>
        </div>
      </section>
    );
  }

  function PageTitle() {
    const active = tabs.find((tab) => tab.id === mainTab);
    const titleMap: Record<MainTab, string> = {
      pixel: "像素序列帧",
      game_ui: "游戏 UI",
      assets: "资产与清单",
      export: "Unreal 导出",
      models: "本地模型管理器",
      settings: "运行设置"
    };
    return (
      <header className="workspace-header">
        <div>
          <div className="section-kicker">当前工作台</div>
          <h2>{titleMap[mainTab]}</h2>
        </div>
        <div className="workspace-actions">
          {active?.icon}
        </div>
      </header>
    );
  }

  function MainPage() {
    if (mainTab === "pixel") return <PixelPage />;
    if (mainTab === "game_ui") return <GameUiPage />;
    if (mainTab === "assets") return <AssetsPage />;
    if (mainTab === "export") return <ExportPage />;
    if (mainTab === "models") return <ModelsPage />;
    return <SettingsPage />;
  }

  function gameUiNodeHasCanvasLayout(node: GameUiPreviewNode) {
    return Boolean(node.anchors?.minimum && node.anchors?.maximum && node.offsets);
  }

  function gameUiNodeLocalBox(node: GameUiPreviewNode, parentWidth: number, parentHeight: number): GameUiPreviewBox {
    if (!gameUiNodeHasCanvasLayout(node)) {
      return {
        x: Number(node.x || 0),
        y: Number(node.y || 0),
        width: Number(node.width || 1),
        height: Number(node.height || 1)
      };
    }
    const min = node.anchors?.minimum || { x: 0, y: 0 };
    const max = node.anchors?.maximum || min;
    const offsets = node.offsets || {};
    const alignment = node.alignment || {};
    const minX = Number(min.x ?? 0);
    const minY = Number(min.y ?? 0);
    const maxX = Number(max.x ?? minX);
    const maxY = Number(max.y ?? minY);
    const leftOffset = Number(offsets.left ?? 0);
    const topOffset = Number(offsets.top ?? 0);
    const rightOffset = Number(offsets.right ?? node.width ?? 1);
    const bottomOffset = Number(offsets.bottom ?? node.height ?? 1);
    const stretchX = minX !== maxX;
    const stretchY = minY !== maxY;
    const width = stretchX ? Math.max(1, parentWidth * maxX - (parentWidth * minX + leftOffset) - rightOffset) : Math.max(1, rightOffset);
    const height = stretchY ? Math.max(1, parentHeight * maxY - (parentHeight * minY + topOffset) - bottomOffset) : Math.max(1, bottomOffset);
    return {
      x: parentWidth * minX + leftOffset - width * Number(alignment.x ?? 0),
      y: parentHeight * minY + topOffset - height * Number(alignment.y ?? 0),
      width,
      height
    };
  }

  function flattenGameUiPreviewNodes(root: GameUiPreviewNode | undefined, refWidth: number, refHeight: number) {
    const nodes: GameUiPreviewLayoutNode[] = [];
    const visit = (node: GameUiPreviewNode | undefined, parentX: number, parentY: number, parentWidth: number, parentHeight: number) => {
      if (!node) return;
      for (const child of node.children || []) {
        const localBox = gameUiNodeLocalBox(child, parentWidth, parentHeight);
        const usesCanvasLayout = gameUiNodeHasCanvasLayout(child);
        const box = {
          x: usesCanvasLayout ? parentX + localBox.x : localBox.x,
          y: usesCanvasLayout ? parentY + localBox.y : localBox.y,
          width: localBox.width,
          height: localBox.height
        };
        nodes.push({ node: child, box });
        visit(child, box.x, box.y, box.width, box.height);
      }
    };
    visit(root, 0, 0, Number(root?.width || refWidth), Number(root?.height || refHeight));
    return nodes;
  }

  function gameUiTextureStateUrl(token: string, states: string[]) {
    const texture = gameUiPreviewData?.textureKit.textures?.[token];
    for (const state of states) {
      const path = texture?.states?.[state]?.path;
      if (path) return previewUrlForPath(projectRoot, path);
    }
    return "";
  }

  function gameUiTextureTokenAvailable(token: string) {
    const states = gameUiPreviewData?.textureKit.textures?.[token]?.states;
    return Boolean(states && Object.keys(states).length > 0);
  }

  function gameUiColorOrFallback(color: string | undefined, fallback: string) {
    const value = (color || "").trim();
    if (!value) return fallback;
    if (/^#[0-9a-f]{8}$/i.test(value) && value.slice(7, 9).toLowerCase() === "00") return fallback;
    if (value === "transparent" || value === "rgba(0, 0, 0, 0)" || value === "rgba(0,0,0,0)") return fallback;
    return value;
  }

  function gameUiShouldFallbackToDefaultToken(node: GameUiPreviewNode, type: string, hasExplicitToken: boolean) {
    if (!["panel", "image"].includes(type)) return true;
    const width = Number(node.width || 0);
    const height = Number(node.height || 0);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return hasExplicitToken;
    return width <= 520 && height <= 220;
  }

  function gameUiNodeToken(node: GameUiPreviewNode, fallbackType?: string) {
    const type = fallbackType || node.type || "";
    const explicit = node.styleToken || "";
    if (explicit && gameUiTextureTokenAvailable(explicit)) return explicit;
    if (type === "text") return "";
    if (!gameUiShouldFallbackToDefaultToken(node, type, Boolean(explicit))) return "";
    const fallback = GAME_UI_DEFAULT_STYLE_TOKENS[type] || "";
    return fallback && gameUiTextureTokenAvailable(fallback) ? fallback : "";
  }

  function renderGameUiPreviewNode(item: GameUiPreviewLayoutNode, refWidth: number, refHeight: number, previewScale: number, index: number) {
    const node = item.node;
    const box = item.box;
    const type = node.type || "panel";
    const token = gameUiNodeToken(node);
    const state =
      type === "checkbox" ? (node.checked ? "checked" : "unchecked") :
        type === "dropdown" ? "normal" :
          "normal";
    const textureUrl = token ? gameUiTextureStateUrl(token, [state, "normal", "unchecked"]) : "";
    const left = Math.max(0, (box.x / refWidth) * 100);
    const top = Math.max(0, (box.y / refHeight) * 100);
    const width = Math.max(0.1, (box.width / refWidth) * 100);
    const height = Math.max(0.1, (box.height / refHeight) * 100);
    const shouldShowText = ["text", "button", "input", "dropdown"].includes(type);
    const text = shouldShowText ? node.text || (type === "dropdown" ? node.options?.[0] || "" : "") : "";
    const useBoxSkin = Boolean(textureUrl && GAME_UI_BOX_STYLE_TOKENS.has(token));
    const borderImageWidth = type === "button" ? "12px" : type === "input" || type === "dropdown" ? "10px" : "16px";
    const scaledFontSize = Math.max(4, (node.fontSize || 18) * previewScale);
    const style: React.CSSProperties = {
      left: `${left}%`,
      top: `${top}%`,
      width: `${width}%`,
      height: `${height}%`,
      color: node.fontColor || "#f8fafc",
      borderWidth: useBoxSkin ? borderImageWidth : undefined,
      borderImageSource: useBoxSkin ? `url("${textureUrl}")` : undefined,
      borderImageSlice: useBoxSkin ? "25% fill" : undefined,
      borderImageRepeat: useBoxSkin ? "stretch" : undefined,
      borderImageWidth: useBoxSkin ? borderImageWidth : undefined,
      backgroundColor: textureUrl ? "transparent" : gameUiColorOrFallback(node.color, "rgba(20, 25, 34, 0.48)"),
      backgroundImage: textureUrl && !useBoxSkin ? `url("${textureUrl}")` : undefined,
      textAlign: (node.textAlign as React.CSSProperties["textAlign"]) || "center",
      fontWeight: node.fontWeight || undefined,
      fontSize: `${scaledFontSize.toFixed(2)}px`
    };
    const fillUrl = type === "slider" ? gameUiTextureStateUrl("sliderFill", ["normal"]) : "";
    const thumbUrl = type === "slider" ? gameUiTextureStateUrl("sliderThumb", ["normal"]) : "";
    const scrollThumbUrl = type === "scroll" ? gameUiTextureStateUrl("scrollThumb", ["normal"]) : "";
    const arrowUrl = type === "dropdown" ? gameUiTextureStateUrl("dropdownArrow", ["normal"]) : "";
    const value = Math.max(0, Math.min(1, Number(node.value ?? 0.5)));

    return (
      <div
        key={`${node.name || type}-${index}`}
        className={`game-ui-preview-node game-ui-preview-node-${type}${textureUrl ? " skinned" : " unskinned"}`}
        style={style}
        title={`${node.name || "unnamed"} · ${type}${token ? ` · ${token}` : ""}`}
      >
        {type === "slider" && (
          <>
            <span className="game-ui-preview-slider-fill" style={{ width: `${value * 100}%`, backgroundImage: fillUrl ? `url("${fillUrl}")` : undefined }} />
            <span className="game-ui-preview-slider-thumb" style={{ left: `${value * 100}%`, backgroundImage: thumbUrl ? `url("${thumbUrl}")` : undefined }} />
          </>
        )}
        {type === "scroll" && <span className="game-ui-preview-scroll-thumb" style={{ backgroundImage: scrollThumbUrl ? `url("${scrollThumbUrl}")` : undefined }} />}
        {type === "dropdown" && arrowUrl && <span className="game-ui-preview-dropdown-arrow" style={{ backgroundImage: `url("${arrowUrl}")` }} />}
        {text && <span className="game-ui-preview-node-text">{text}</span>}
      </div>
    );
  }

  function selectedStructureNameFromPath(path: string) {
    return gameUiStructures.find((item) => item.path === path)?.screenName || path.split(/[\\/]/).pop()?.replace(/\.uim-ui\.json$/i, "");
  }

  function selectedKitNameFromPath(path: string) {
    return gameUiTextureKits.find((item) => item.path === path)?.kitName || path.split(/[\\/]/).pop()?.replace(/\.uim-uikit\.json$/i, "");
  }

  const appContextValue = {
    DEFAULT_VIDEO_LOOP_MIN_SCORE,
    RailContext,
    activeAssetName,
    activePreviewPath,
    activePreviewVersionId,
    activeStreamSession,
    addCurrentVideoFrame,
    assetTreeData,
    assetTreeSelectionId,
    assetTypeLabel,
    assets,
    autoSelectVideoFramesByFps,
    backend,
    busy,
    cancelActiveTask,
    cancelRequested,
    checkUnrealStatus,
    chooseAndCreateProject,
    chooseAndOpenProject,
    clampVideoPickerTime,
    clearGameUiTextureKit,
    clearVideoSelectionPreview,
    consoleOutputRef,
    createProject,
    currentImageBrowserTree,
    currentManifest,
    deleteAssetFromTree,
    deleteAssetVersion,
    disconnectProject,
    endPreviewResize,
    exportUnrealScript,
    exportVideoFrameQueue,
    findVideoLoopFrame,
    flattenGameUiPreviewNodes,
    forgetRecentProject,
    formatRecentProjectTime,
    formatVideoTime,
    gameUiClearTextureKitTarget,
    gameUiColorOrFallback,
    gameUiPreviewCanvasRef,
    gameUiPreviewCanvasWidth,
    gameUiPreviewData,
    gameUiPreviewLoading,
    gameUiPreviewOpen,
    handleConsoleScroll,
    handleVideoFrameDragStart,
    handleVideoFrameDrop,
    handleVideoFrameTileClick,
    hydrateVideoFrameSelectionThumbnails,
    issueCount,
    lastResult,
    latestAssetThumbnailPath,
    log,
    movePreviewResize,
    openProject,
    pendingDelete,
    playVideoLoopPreview,
    playVideoSelectionPreview,
    previewHeight,
    previewName,
    previewPath,
    project,
    projectName,
    projectNameFromRoot,
    projectPanelMode,
    recentProjects,
    removeSelectedVideoFrames,
    removeVideoFrameSelection,
    renderGameUiPreviewNode,
    seekVideoFrameSelection,
    selectAssetFromTree,
    selectedAsset,
    selectedKitNameFromPath,
    selectedLoopFrameId,
    selectedLoopFrameIndex,
    selectedStructureNameFromPath,
    setAllVideoFrameSelections,
    setGameUiClearTextureKitTarget,
    setGameUiPreviewOpen,
    setPendingDelete,
    setProjectName,
    setProjectPanelMode,
    setSelectedLoopFrameId,
    setVideoAutoFps,
    setVideoFramePickerOpen,
    setVideoFrameSelections,
    setVideoLoopMinScore,
    setVideoPickerCurrentTime,
    setVideoPickerDuration,
    setVideoPreviewNaturalSize,
    setVideoRangeEnd,
    setVideoRangeStart,
    setVideoSourceAspectRatio,
    startPreviewResize,
    stepVideoFrame,
    taskProgress,
    trimVideoFramesToLoopPoint,
    unrealStatus,
    updateVideoRangeEnd,
    updateVideoRangeStart,
    validateCurrentManifest,
    validationResult,
    versionDisplayLabel,
    videoAutoFps,
    videoFramePickerOpen,
    videoFramePickerRef,
    videoFrameThumbnailsLoading,
    videoLoopMinScore,
    videoLoopPreviewing,
    videoPickerCurrentTime,
    videoPickerDuration,
    videoPreviewNaturalSize,
    videoPreviewStageRef,
    videoPreviewStageSize,
    videoRangeEnd,
    videoRangeStart,
    videoSelectionPreviewIndex,
    videoSelectionPreviewing,
    videoSourceAspectRatio,
    workerBlocked,
    AssetPreview,
    CommandCombobox,
    DEFAULT_GAME_UI_TEXTURE_BATCH_COUNT,
    DEFAULT_GAME_UI_TEXTURE_STATE_COUNT,
    DEFAULT_GAME_UI_TEXTURE_TOKEN_COUNT,
    DEFAULT_SEEDANCE_ENDPOINT,
    DEFAULT_SEEDANCE_MODEL,
    DEFAULT_SEEDANCE_RESOLUTION,
    EditableCommandCombobox,
    GAME_UI_CHROMA_PRESETS,
    PIXEL_MASK_MODE_OPTIONS,
    PIXEL_RESTORE_MODE_OPTIONS,
    SEEDANCE_MODEL_OPTIONS,
    SlotPicker,
    TILEMAP_STANDARD_OPTIONS,
    WorkerAlert,
    absoluteMcpRoot,
    anchorConceptReferencePath,
    anchorOutputOptions,
    anchorPathForDirection,
    applyPixelKindSelection,
    assetIdFromName,
    assetName,
    bakeGameUiHtml,
    browserVersionDate,
    checkNetworkProxy,
    codexCallbackInput,
    codexFlow,
    codexOAuth,
    completeCodexOAuthManually,
    composeTilemapFromSeed,
    contentPath,
    copyGameUiDslPrompt,
    copyPixelMcpConfig,
    createTilemapManifest,
    currentCutoutRole,
    currentPixelActionId,
    currentPixelActionLabel,
    currentSeedanceModel,
    currentSeedanceResolution,
    currentSheetDirection,
    currentSheetRole,
    currentVideoDirection,
    currentVideoSourcePath,
    cutoutSourceSlot,
    defaultSeedanceModel,
    defaultSeedanceResolution,
    deleteCurrentUiConcept,
    deleteGameUiHtml,
    deleteGameUiStructure,
    deleteModel,
    disabled,
    disconnectCodexOAuth,
    downloadSam,
    exportGameUiUmg,
    gameUiAdvancedTokensOpen,
    gameUiChromaPreset,
    gameUiConceptVersionChoices,
    gameUiCustomChromaHex,
    gameUiHtmlDraft,
    gameUiHtmlPath,
    gameUiHtmlPrototypes,
    gameUiKitFilesJson,
    gameUiKitName,
    gameUiKitSelectionValue,
    gameUiScreenName,
    gameUiSelectedChromaHex,
    gameUiSelectedChromaRgb,
    gameUiSelectedKitPath,
    gameUiStructurePath,
    gameUiStructures,
    gameUiTab,
    gameUiTextureDebugArtifacts,
    gameUiTextureKits,
    gameUiTextureMaxConcurrency,
    gameUiWidgetTokensJson,
    generateGameUiTextureKit,
    generatePixelAnchor,
    generatePixelConcept,
    generatePixelSheet,
    generatePixelSheetFromVideo,
    generateSeedanceVideo,
    generateTilemapSeedConcept,
    generateUiConcept,
    handlePixelMatrixCellClick,
    huggingFaceTokenDraft,
    imageProvider,
    importPixelSheet,
    importUiConcept,
    installMarker,
    installedCount,
    knownActionLabel,
    mcpRuntimePaths,
    modelCacheDir,
    modelDependencies,
    modelStatusLabel,
    models,
    networkCheck,
    networkProxyDraft,
    normalizePixelSheet,
    normalizeSourceSlot,
    openAiBaseUrlDraft,
    openAiKeyDraft,
    openAiMergeEditImagesDraft,
    openGameUiSkinPreview,
    openVideoFramePicker,
    pixelAction,
    pixelActionDescription,
    pixelActionMenuOpen,
    pixelActionOptions,
    pixelActionQuery,
    pixelAnchorOutputSize,
    pixelAnchorUseConcept,
    pixelAttackName,
    pixelBatchQueue,
    pixelCellSize,
    pixelColumns,
    pixelConceptPath,
    pixelCustomActionName,
    pixelCutoutPath,
    pixelDebugArtifacts,
    pixelDecontaminateEdges,
    pixelDirection,
    pixelDirectionLabel,
    pixelDynamicEffect,
    pixelEffectColor,
    pixelI2vActionDescription,
    pixelKind,
    pixelKindCopy,
    pixelKindLabel,
    pixelMaskMode,
    pixelMatrixActionLabel,
    pixelMatrixActions,
    pixelMatrixCellKey,
    pixelMatrixCellState,
    pixelMatrixDirections,
    pixelMatrixSelection,
    pixelMcpBackendPath,
    pixelMcpPythonPath,
    pixelMirrorEastFromWest,
    pixelPreviewOpen,
    pixelProjectileEffect,
    pixelRestoreMode,
    pixelRows,
    pixelSeedanceSeconds,
    pixelSheetMode,
    pixelSheetPath,
    pixelStage,
    pixelSubject,
    pixelTileSetPath,
    pixelTileSize,
    pixelTilemapOuterMaterial,
    pixelTilemapOuterPath,
    pixelTilemapPrimaryMaterial,
    pixelTilemapPrimaryPath,
    pixelTilemapSeedPath,
    pixelTilemapStandard,
    pixelTilemapSubject,
    pixelVideoPath,
    previewUrlForPath,
    projectRoot,
    pushLog,
    refreshCodexOAuth,
    refreshGameUiWorkspace,
    refreshModels,
    registerGameUiTextureKit,
    rembgModel,
    removePixelSheetBackground,
    requestClearGameUiTextureKit,
    runAction,
    runPixelBatch,
    runtimeSettings,
    saveGameUiHtml,
    saveRuntimeSettings,
    seedanceEndpointDraft,
    seedanceKeyDraft,
    seedanceModelDraft,
    seedanceResolutionDraft,
    seedanceResolutionOptions,
    selectGameUiConceptVersion,
    selectGameUiHtmlPrototype,
    selectGameUiKitName,
    selectedGameUiTextureKit,
    setActivePreviewLabel,
    setActivePreviewPath,
    setActivePreviewVersionId,
    setAssetName,
    setCodexCallbackInput,
    setContentPath,
    setGameUiAdvancedTokensOpen,
    setGameUiChromaPreset,
    setGameUiCustomChromaHex,
    setGameUiHtmlDraft,
    setGameUiHtmlPath,
    setGameUiKitFilesJson,
    setGameUiSelectedKitPath,
    setGameUiStructurePath,
    setGameUiTab,
    setGameUiTextureDebugArtifacts,
    setGameUiTextureMaxConcurrency,
    setGameUiWidgetTokensJson,
    setHuggingFaceTokenDraft,
    setImageProvider,
    setNetworkProxyDraft,
    setOpenAiBaseUrlDraft,
    setOpenAiKeyDraft,
    setOpenAiMergeEditImagesDraft,
    setPixelActionDescription,
    setPixelActionFromId,
    setPixelActionMenuOpen,
    setPixelActionQuery,
    setPixelAnchorUseConcept,
    setPixelAttackName,
    setPixelColumns,
    setPixelConceptPath,
    setPixelCustomActionName,
    setPixelDebugArtifacts,
    setPixelDecontaminateEdges,
    setPixelDirection,
    setPixelDynamicEffect,
    setPixelEffectColor,
    setPixelI2vActionDescription,
    setPixelMaskMode,
    setPixelMatrixSelection,
    setPixelMirrorEastFromWest,
    setPixelPreviewOpen,
    setPixelProjectileEffect,
    setPixelRestoreMode,
    setPixelRows,
    setPixelSeedanceResolution,
    setPixelSeedanceSeconds,
    setPixelSheetMode,
    setPixelStage,
    setPixelSubject,
    setPixelTileSetPath,
    setPixelTileSize,
    setPixelTilemapOuterMaterial,
    setPixelTilemapOuterPath,
    setPixelTilemapPrimaryMaterial,
    setPixelTilemapPrimaryPath,
    setPixelTilemapSeedPath,
    setPixelTilemapStandard,
    setPixelTilemapSubject,
    setPixelVideoPath,
    setRembgModel,
    setSeedanceEndpointDraft,
    setSeedanceKeyDraft,
    setSeedanceResolutionDraft,
    setTilemapImportOpen,
    setUiAssetName,
    setUiGameDescription,
    setUiLayout,
    setUnrealMcpUrlDraft,
    startCodexOAuth,
    tilemapImportOpen,
    tilemapStandardOption,
    togglePixelMatrixCell,
    uiAssetName,
    uiConceptSlot,
    uiGameDescription,
    uiLayout,
    unrealMcpUrlDraft,
    updatePixelAnchorOutputSize,
    updatePixelCellSize,
    updatePixelSeedanceModel,
    updateSeedanceModelDraft,
    useDismissableCombobox,
    versionRoleLabel,
    videoFrameSelections,
    videoSheetLayoutForFrameCount,
    videoSourceSlot
  };

  return (
    <AppContext.Provider value={appContextValue}>
      <main className="app-shell">
      <Suspense fallback={null}>
        <ProjectSidebar />
      </Suspense>
      <section className="workbench-shell">
        {TopTabs()}
        <div className="workbench-body">
          <section className="main-workspace">
            {PageTitle()}
            <div className="workspace-scroll">
              <Suspense fallback={null}>
                {MainPage()}
              </Suspense>
            </div>
          </section>
          <Suspense fallback={null}>
            <RightPanel />
          </Suspense>
        </div>
      </section>
      <Suspense fallback={null}>
        <AppDialogs />
      </Suspense>
      </main>
    </AppContext.Provider>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
