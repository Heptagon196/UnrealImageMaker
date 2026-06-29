# UnrealImageMaker 长期方案

## 产品定位

UnrealImageMaker 是一个 AI 辅助的 2D 游戏资产生产管线工具，而不是单纯的图片生成器。

它的核心职责是把 AI 生成图或用户提供的图片，转化为游戏引擎可直接使用的资产，并保留可复现的元数据、处理流程、校验结果和导入说明。

第一目标引擎是 Unreal Engine。系统必须抽象出独立的引擎适配层，方便以后接入 Godot 或其他游戏引擎。

## 最终目标

最终产品需要支持 2D 游戏制作资产的端到端生产：

- 生成、编辑、处理、校验并导出 sprite、spritesheet、tile、prop、UI 图标、UI 面板、按钮和完整 UI kit。
- 自动抠图、清理透明边缘、切分 spritesheet、推断帧边界，并生成引擎导入所需的元数据。
- 通过 Unreal MCP、Unreal Python 脚本和可选 UE 编辑器插件导出资产到 Unreal Engine。
- 保存所有生成、模型、prompt、seed、处理步骤和引擎导入元数据，方便资产重新生成、审计和重导入。
- 让核心资产管线保持引擎无关。

## 核心模型栈

第一版核心模型组合：

- `gpt-image-2`：负责云端图片生成和图片编辑。
- `Codex OAuth / ChatGPT 订阅`：作为实验性的账号态生成入口，用于用户希望通过 ChatGPT 订阅而不是 OpenAI API Key 使用 Codex 图像能力的场景。它必须保持为独立 provider，不得和普通 OpenAI API Key provider 混用；凭据只保存在软件用户数据目录。
- `rembg`：负责默认本地背景移除和轻量 alpha 生成。
- `SAM 2.1`：负责本地精细分割、交互式 mask 修正和多物体 sprite 提取。
- `RMBG 2.0`：作为可选高质量抠图后端，可以通过 rembg 或专用适配器接入，但需要处理授权问题。

未来可以增加其他可选生成后端：

- ComfyUI
- SDXL
- SD 3.5
- FLUX
- 自定义 LoRA 工作流
- 其他本地或云端模型服务

## 风格配置

风格必须是一等管线概念，不能只做成 prompt 下拉框。

每个风格配置需要定义：

- Prompt 模板和负面约束。
- 默认模型路由。
- 默认图片尺寸和比例。
- 后处理链。
- 质量校验规则。
- 引擎导入设置。

初始内置风格：

- 像素风 2D
- 手绘 / 卡通 2D
- 半写实 UI 图标
- 自定义项目风格

## 资产项目格式

项目使用目录型 `.uim` 格式。`.uim` 项目属于 UnrealImageMaker 自身，不属于目标游戏项目。

推荐结构：

```text
MyAssetProject.uim/
  project.uim.json
  models.lock.json
  profiles/
  assets/
    hero_run/
      asset.uim.json
      source/
      generated/
      masks/
      manifests/
      exports/
  exports/
    unreal/
    godot/
  cache/
```

`project.uim.json` 保存项目级设置、目标引擎、默认风格配置、输出路径和模型策略。

`models.lock.json` 保存项目使用的精确模型 ID、版本、许可、校验和本地路径。

## Manifest 策略

所有生成资产都要编译成 JSON manifest。引擎适配器只消费 manifest，不直接消费某个 AI 模型的专用输出。

Manifest 层是最重要的长期抽象边界。

需要定义的 manifest 类型：

- `TextureManifest`
- `SpriteSheetManifest`
- `AnimationManifest`
- `UIKitManifest`
- `NineSliceManifest`

顶层结构示例：

```json
{
  "schema": "uim.asset_manifest.v1",
  "assetType": "spritesheet",
  "id": "hero_run",
  "displayName": "Hero Run",
  "styleProfile": "pixel_art",
  "files": [],
  "frames": [],
  "processing": {},
  "targets": {
    "unreal": {
      "contentPath": "/Game/UIM/Hero",
      "create": ["Texture2D", "PaperSprite", "PaperFlipbook"]
    }
  }
}
```

## 引擎适配层

引擎适配层负责把 `.uim` manifest 转换为具体引擎资产。

初始适配器：

- Unreal Adapter
- 通用 PNG/JSON Adapter

未来适配器：

- Godot Adapter
- 如有必要，再考虑 Unity Adapter

核心图片管线不能依赖 Unreal 专用类。所有 Unreal 专用行为都放在 Unreal Adapter 中。

## Unreal 集成策略

第一版可运行版本不强制依赖 UE 插件。

推荐顺序：

1. Unreal MCP Bridge
2. 生成 Unreal Python 导入脚本作为兜底方案
3. 后续再提供可选 UE 编辑器插件，用于更深的编辑器体验

MCP 能做的地方优先使用 MCP：

- 创建 Content 目录。
- 查询、加载、保存和更新资产。
- 在支持范围内创建和编译 UMG Widget Blueprint。
- 设置已暴露的资产属性。

以下能力可能需要 Unreal Python 或插件补齐：

- 如果 MCP 覆盖不够，创建 Paper2D sprite 和 flipbook。
- 更细的 Texture Import Task 设置。
- Reimport Handler。
- Common UI style 资产细节。
- 编辑器菜单、工具栏按钮、Content Browser 右键操作、自定义资产工厂和数据校验。

插件是增强路径，不是核心依赖。

## 本地模型管理

大型离线模型应该按需下载。

默认行为：

- 安装包不内置大型模型。
- 只有用户启用本地抠图时，才下载 rembg 模型。
- 只有用户启用精细分割时，才下载 SAM 2.1 checkpoint。
- RMBG 2.0 需要用户显式启用，因为它涉及授权处理。

模型默认存储在软件工作区的共享缓存中，并由项目锁定实际版本：

```text
UnrealImageMaker/
  model-cache/
  projects/
```

当需要打包成可迁移项目时，可以把当前项目所需模型复制进项目目录。

## 资产质量校验

质量校验是产品的重要功能。工具应在资产进入引擎前发现常见生产问题。

示例：

- 透明边缘脏污。
- 黑边或白边 alpha halo。
- 像素风资产出现抗锯齿污染。
- 帧尺寸不一致。
- sprite pivot 不稳定。
- spritesheet 帧越界。
- 缺少 padding 或边缘扩展。
- 九宫格边界无法干净拉伸。
- UI 不同状态尺寸不一致。
- Unreal 导入设置和当前风格配置冲突。

## 主要工作流

### Sprite / Icon

```text
Prompt 或参考图
  -> gpt-image-2 生成 / 编辑
  -> rembg 提取 alpha
  -> 可选 SAM 2.1 修正
  -> trim / padding / 校验
  -> manifest
  -> Unreal 导入
```

### Spritesheet

```text
生成或导入 sheet
  -> 切分帧
  -> 可选 SAM 2.1 多物体分割
  -> 推断帧框和 pivot
  -> 校验帧一致性
  -> manifest
  -> Unreal Texture2D / PaperSprite / PaperFlipbook 导入
```

### UI Kit

```text
生成按钮 / 面板 / 图标集
  -> 提取状态
  -> 检测或手动设置九宫格数据
  -> 导出多尺寸图片
  -> manifest
  -> Unreal Texture2D / Slate Brush / UMG / Common UI 资产
```

## 安全、成本和授权

产品必须明确展示：

- 云端生成成本估算和失败情况。
- API key 存储策略。
- 哪些用户素材会上传到云端模型。
- 当前工作流是否能完全本地运行。
- 模型许可和商业使用状态。
- Prompt、seed、模型和生成历史，方便审计。

## 长期成功标准

项目成功的标志是用户可以：

- 创建一个 AI 资产项目。
- 生成一整套可用于游戏制作的 2D 资产。
- 检查和修正 mask 与帧元数据。
- 使用正确导入设置把资产导出到 Unreal。
- 在不破坏引擎引用的前提下重新生成或修改资产。
- 在未来新增引擎适配器，而不需要重写 AI 或图片处理核心。
