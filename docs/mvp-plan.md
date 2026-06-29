# UnrealImageMaker MVP 方案

## MVP 目标

构建 UnrealImageMaker 的第一个可用版本，验证它作为资产生产管线工具的核心闭环。

MVP 必须跑通以下流程：

```text
生成图片
  -> 抠图 / 分割
  -> 后处理和校验
  -> 写出 JSON manifest
  -> 导入或导出到 Unreal Engine
```

第一版应避免不必要的 UE 插件开发。优先使用 Unreal MCP；当 MCP 覆盖不足时，生成 Unreal Python 脚本作为兜底。

## 第一版范围

### 包含

- `.uim` 项目目录格式。
- JSON 资产 manifest。
- `gpt-image-2` 生成 / 编辑适配器。
- Codex OAuth / ChatGPT 订阅实验生成适配器，作为无 OpenAI API Key 时的可选入口。
- `rembg` 本地抠图适配器。
- `SAM 2.1` 本地分割适配器。
- RMBG 2.0 可选配置入口，但不作为默认依赖。
- 基础图片后处理。
- 基础资产质量校验。
- Unreal MCP bridge。
- Unreal 导出目录和 manifest 输出。
- 第一批工作流：
  - 单张 sprite / icon。
  - spritesheet 切分和元数据。
  - UI button / panel 资产生成元数据。

### 已确认的实现决策

- 第一版目标平台：`Windows 11 + NVIDIA CUDA`。rembg 允许 CPU fallback；SAM 2.1 的 CPU 路径只作为调试路径，不承诺实际体验。
- 桌面技术栈：`Tauri 2 + React + TypeScript + Python FastAPI worker`。
- Python / AI 运行环境：软件管理自己的 Python venv，不依赖用户系统 Python。
- `.uim` 形态：目录型项目，不是单文件。以后如有需要，再增加归档打包功能。
- 模型存储策略：模型默认只下载到软件共享 `model-cache`。`.uim` 项目只通过 `models.lock.json` 锁定模型 ID、版本、来源、许可和 checksum。项目迁移到另一台电脑后，由软件根据 `models.lock.json` 自动补齐缺失模型。MVP 不实现把模型复制进项目的可移植打包功能。
- OpenAI API Key 存储：默认放系统凭据库，支持环境变量覆盖，不写入 `.uim` 项目文件。
- ChatGPT 订阅接入策略：作为独立 `Codex OAuth` provider，不和普通 OpenAI API Key 混用。使用 OpenAI 账号态 OAuth PKCE 绑定，保存 access token、refresh token、account id、邮箱和过期时间到本软件用户数据目录；`.uim` 项目和 manifest 只记录使用的 provider / model，不保存凭据。
- `gpt-image-2` 第一版能力边界：优先保证 prompt 生成闭环，参考图 / 局部编辑先预留接口，视接入复杂度决定是否进入第一版。
- rembg 运行方式：作为 Python worker 内部库运行，复用 session；暂不单独起 rembg HTTP server。
- SAM 2.1 第一版交互：先支持框选和点选 mask，不做复杂画笔编辑。
- Spritesheet MVP 范围：先做固定网格切分 + alpha 边界修正，自由散布多物体自动分组放到第二阶段。
- UI MVP 深度：第一版只生成 / 导入按钮状态图、面板图、九宫格 metadata 和 Unreal manifest；不自动创建完整 Common UI style asset。
- Unreal 导入策略：MCP 优先，Python 脚本兜底；不把 AI 逻辑放进 UE，不做 UE 插件。
- Unreal 项目写入方式：先导出到 Unreal 项目的暂存目录或用户指定目录，再通过 MCP / Python 导入 Content；不直接手写 `.uasset`。
- 第一版资产类型优先级：`单张 sprite / icon` -> `spritesheet` -> `UI button / panel`。

### 暂不包含

- 完整 UE 编辑器插件。
- 完整 Common UI 资产创建。
- 完整 Godot adapter。
- 本地 diffusion / ComfyUI 生成。
- 团队协作。
- Marketplace 打包。
- 复杂的引擎内可视化编辑器。

## MVP 项目目录结构

```text
MyAssetProject.uim/
  project.uim.json
  models.lock.json
  profiles/
    pixel_art.json
    hand_drawn_cartoon.json
    semi_realistic_ui.json
  assets/
  exports/
    unreal/
  cache/
```

## 核心 TODO List

### 1. 项目系统

- [x] 定义 `project.uim.json` schema。
- [x] 定义 `models.lock.json` schema。
- [x] 实现项目创建、打开和保存逻辑。
- [x] 实现项目目录脚手架。
- [x] 增加软件级模型缓存位置。
- [x] 项目默认只记录模型锁定信息，不复制大型模型。
- [x] 打开项目时，根据 `models.lock.json` 检查本机 `model-cache`，并提示补齐缺失模型。

### 2. Manifest Schema

- [x] 定义通用 manifest 字段：
  - `schema`
  - `assetType`
  - `id`
  - `displayName`
  - `styleProfile`
  - `files`
  - `processing`
  - `targets`
- [x] 定义 `TextureManifest`。
- [x] 定义 `SpriteSheetManifest`。
- [x] 定义 `AnimationManifest`。
- [x] 定义 `UIKitManifest`。
- [x] 定义 `NineSliceManifest`。
- [x] 增加 manifest 版本策略。
- [x] 增加 manifest 校验。

### 3. 风格配置

- [x] 创建内置 `pixel_art` 配置。
- [x] 创建内置 `hand_drawn_cartoon` 配置。
- [x] 创建内置 `semi_realistic_ui` 配置。
- [x] 增加 prompt 模板字段。
- [x] 增加默认处理链字段。
- [x] 增加每个风格对应的 Unreal 导入设置。
- [x] 增加每个风格对应的质量校验规则。

### 4. 图片生成适配器

- [x] 实现 `gpt-image-2` provider 接口。
- [x] 实现 `Codex OAuth / ChatGPT 订阅` 实验 provider 接口。
- [x] 增加 OAuth PKCE 开始、完成、刷新、断开绑定 API。
- [x] 增加前端 provider 选择和 Codex OAuth 绑定面板。
- [x] 支持 prompt 生成图片。
- [x] 在可用时支持图片编辑 / 参考图输入。
- [x] 保存 prompt、model、size、quality、request ID 和生成元数据。
- [x] 将生成图片保存到资产目录的 `generated/`。
- [x] 处理 API 错误和被拒请求。
- [x] 尽量估算或记录云端生成成本。

### 5. 本地背景移除

- [x] 实现 rembg 安装 / 状态检测。
- [x] 实现 rembg model manager 条目。
- [x] 支持默认模型选择：
  - `u2netp`：快速预览。
  - `isnet-general-use` 或 `birefnet-general-lite`：默认通用抠图。
  - `isnet-anime`：卡通 / 动漫资产。
- [x] 以 Python 库或本地 HTTP 服务方式运行 rembg。
- [x] 将 alpha 输出保存到 `masks/`，将处理后的 PNG 保存到 `generated/`。
- [x] 批处理时复用 rembg session，提升性能。

### 6. SAM 2.1 分割

- [x] 实现 SAM 2.1 model manager 条目：
  - `sam2.1_hiera_tiny`
  - `sam2.1_hiera_small`
  - `sam2.1_hiera_base_plus`
  - `sam2.1_hiera_large`
- [x] 按需下载 checkpoint。
- [x] 默认使用 `sam2.1_hiera_small`。
- [x] 对低显存用户推荐 `tiny`。
- [x] 支持点选 prompt 分割。
- [x] 支持框选 prompt 分割。
- [x] 保存 mask 和修正后的 alpha 输出。
- [x] SAM 只用于精细修正或多物体提取，不默认处理每一张图。

### 7. 可选 RMBG 2.0

- [x] 增加默认禁用的 RMBG 2.0 后端选项。
- [x] 增加授权提示和配置字段。
- [x] 支持用户提供 Hugging Face token 或本地模型路径。
- [x] 不让 RMBG 2.0 阻塞 MVP。

### 8. 图片处理

- [x] 裁剪透明边界。
- [x] 增加可配置 padding。
- [x] 为 sprite 增加边缘扩展。
- [x] 清理 alpha halo。
- [x] 生成 bounding box。
- [x] 推断 sprite pivot。
- [x] 支持像素风 nearest scaling。
- [x] 预留像素风调色板量化。
- [x] 导出最终 PNG 文件。

### 9. Spritesheet 管线

- [x] 支持固定网格 spritesheet 切分。
- [x] 支持基于 alpha 边界的帧检测。
- [x] 保存帧矩形。
- [x] 保存帧 pivot。
- [x] 保存动画序列元数据。
- [x] 校验帧尺寸一致性。
- [x] 生成 `SpriteSheetManifest`。
- [x] 生成 Unreal 目标说明：Texture2D、PaperSprite、PaperFlipbook。

### 10. UI 资产管线

- [x] 生成或导入按钮状态：
  - normal
  - hovered
  - pressed
  - disabled
- [x] 生成或导入面板图片。
- [x] 保存九宫格边界元数据。
- [x] 校验不同状态的尺寸一致性。
- [x] 生成 `UIKitManifest`。
- [x] 生成 Unreal 目标说明：Texture2D 和 UMG / Slate Brush 用法。
- [x] 如果 MCP / Python 支持不足，完整 Common UI style 创建留到后续里程碑。

### 11. Unreal Adapter

- [x] 实现 Unreal MCP 连接检测。
- [x] 通过 MCP 创建目标 Content 目录。
- [x] 将生成文件导入或复制到 Unreal 项目的导入暂存位置。
- [x] 在可行范围内通过 MCP 创建 / 保存资产。
- [x] 在可行范围内设置纹理导入属性：
  - sRGB
  - mipmaps
  - compression
  - texture group
  - filter mode
- [x] 在可行范围内通过 MCP 创建基础 UMG Widget Blueprint。
- [x] 对缺失操作生成 Unreal Python 导入脚本。
- [x] 记录所有 Unreal 导入动作。
- [x] AI / 模型逻辑不得放进 Unreal。

### 12. 质量校验

- [x] 校验透明边缘脏污。
- [x] 校验 alpha 输出为空。
- [x] 校验 sprite 帧边界。
- [x] 校验像素风抗锯齿风险。
- [x] 校验 UI 状态尺寸不一致。
- [x] 校验 Unreal 目标路径缺失。
- [x] 导出前显示警告。

### 13. 桌面应用外壳

- [x] 选择应用框架并搭建项目。
- [x] 推荐技术栈：
  - Tauri 2
  - React / TypeScript
  - Python FastAPI worker
- [x] 实现项目浏览器。
- [x] 实现资产列表。
- [x] 实现生成表单。
- [x] 实现处理预览。
- [x] 实现 manifest inspector。
- [x] 实现 Unreal 导出面板。
- [x] 实现模型管理面板。

### 14. 模型管理器

- [x] 跟踪模型状态：
  - `not_installed`
  - `downloading`
  - `installed`
  - `update_available`
  - `broken`
- [x] 跟踪本地路径。
- [x] 跟踪 checksum。
- [x] 跟踪 license。
- [x] 跟踪推荐 VRAM。
- [x] 增加删除模型操作。
- [x] 增加修复 / 重新下载操作。

### 15. 文档

- [x] 记录 `.uim` 项目格式。
- [x] 记录 manifest schemas。
- [x] 记录本地模型下载行为。
- [x] 记录 Unreal MCP 设置方法。
- [x] 记录 Unreal Python 兜底导入流程。
- [x] 记录模型授权说明。

## MVP 里程碑

### Milestone 1：本地项目和 Manifest

- 可以创建项目。
- 可以加载风格配置。
- 一个示例资产可以生成有效 manifest。

### Milestone 2：图片生成和背景移除

- `gpt-image-2` 可以生成图片。
- rembg 可以生成透明 PNG。
- 后处理可以保存最终 PNG 和元数据。

### Milestone 3：SAM 修正

- SAM 2.1 模型可以按需下载。
- 用户可以通过点选或框选生成 mask。
- 修正后的 mask 可以更新处理后资产。

### Milestone 4：Spritesheet 导出

- 固定网格 spritesheet 切分可用。
- 可以保存帧元数据和 pivot。
- 可以生成 Unreal 目标 manifest。

### Milestone 5：Unreal Bridge

- Unreal MCP 连接可用。
- 可以创建目标 Content 目录。
- 可以通过 MCP 或生成的 Python 兜底脚本保存 / 导入资产。

### Milestone 6：UI 资产第一版

- 可以生成或导入按钮状态图和面板图。
- 可以手动设置九宫格元数据。
- 可以为 Unreal 导出 UI manifest。

## 第一批关键决策

- 先用 MCP，后做插件。
- AI 管线放在 Unreal 外部。
- 所有生产元数据使用 JSON 保存。
- 离线模型只在用户启用本地处理后下载。
- rembg 作为默认背景移除层。
- SAM 2.1 只用于精细分割和修正路径。
- RMBG 2.0 因为授权和部署复杂度，作为可选项。
