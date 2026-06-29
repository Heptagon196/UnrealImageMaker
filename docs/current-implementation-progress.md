# UnrealImageMaker 当前实现进度评估

评估日期：2026-06-26

## 总体结论

当前项目已经不是早期原型，基本处在 MVP / 内测可运行阶段。

前端可以生产构建，后端测试通过，也已经生成了 Tauri 安装包产物。核心的本地项目、资产管理、图片生成入口、图像处理、manifest、专项像素 / UI 工作流和 Unreal Python 导出兜底都已经成型。

按实现深度估算，当前 MVP 完成度约为 70% - 80%。主要剩余风险集中在 Unreal 真导入闭环、真实外部模型 / 云端服务端到端验证、质量校验深度、模型安装体验和发布前工程整理。

## 已经完成或基本可用

### 桌面应用外壳

- 已搭建 Tauri 2 + React + TypeScript 桌面应用。
- Tauri 启动时会尝试拉起 Python FastAPI 后端 worker。
- 已配置前端构建、Tauri 打包资源和 CSP。
- 已生成安装包：
  - `src-tauri/target/release/bundle/msi/UnrealImageMaker_0.1.0_x64_en-US.msi`
  - `src-tauri/target/release/bundle/nsis/UnrealImageMaker_0.1.0_x64-setup.exe`

### 前端工作台

- 已有主工作区和主要页面：
  - 像素 Spritesheet
  - 游戏 UI
  - 资产
  - 导出
  - 设置
- 已有项目 / 当前资产 / 资产版本 / 预览 / 队列 / 日志等工作台结构。
- Playwright smoke 报告显示桌面和移动视口没有水平溢出。

### 后端 API

后端已经提供较完整的 FastAPI 路由，覆盖：

- 健康检查和事件流。
- 运行设置和网络检查。
- Codex OAuth 开始、轮询、完成、刷新、断开。
- `.uim` 项目创建和打开。
- 项目资产列表、资产版本注册、排序、删除。
- 模型列表、模型 marker、删除、lock。
- rembg 背景移除。
- SAM 2.1 下载和分割。
- 图片处理。
- sprite、spritesheet、UI kit manifest。
- 像素专项生产。
- UI 专项生产。
- Unreal Python 脚本生成。
- Unreal MCP 状态检查。

### 项目格式和 Manifest

- `.uim` 目录型项目已实现。
- `project.uim.json`、`models.lock.json`、asset index、manifest 都已有代码路径。
- 已定义并支持：
  - texture
  - spritesheet
  - animation
  - ui_kit
  - nine_slice
- Manifest 校验已有基础规则。

### AI 生成 Provider

- OpenAI image provider 有实际 HTTP 调用路径。
- Codex OAuth / ChatGPT 订阅实验 provider 有 OAuth、token、SSE 解析和图片结果提取路径。
- 支持 prompt 生成和参考图编辑路径，但真实效果仍依赖外部服务实测。

### 本地图像处理

- 已实现透明边界裁剪。
- 已实现 alpha halo 清理。
- 已实现边缘扩展。
- 已实现 nearest scaling。
- 已预留 / 实现调色板量化函数。
- 已实现固定网格 spritesheet 切分。
- 已实现 alpha 帧检测。

### rembg / SAM

- rembg adapter 有真实库调用路径，并复用 session。
- SAM 2.1 adapter 有 checkpoint 下载、状态检查和点选 / 框选分割路径。
- SAM runtime 依赖属于 optional，需要实机安装和验证。

### 专项工作流

- 像素角色 / 武器 / 装饰 / 地形集方向已有专项 prompt 和流程。
- 已支持概念图、anchor、spritesheet、normalize、47-tile manifest、Seedance walk video 入口。
- 游戏 UI 已支持概念图和 widget 生成流程。
- 之前专项重设计 code review 中发现的问题已修复并有测试覆盖。

### Unreal 导出

- 已实现 Unreal Python 导入脚本生成。
- 脚本使用 `unreal.AssetImportTask` 导入图片，并设置基础 Texture2D 属性。
- Unreal MCP bridge 当前可检查 HTTP endpoint 健康状态。

## 当前验证结果

本次检查实际运行：

- `npm.cmd run build`：通过。
- `npm.cmd run backend:test`：42 个测试通过。

已知非阻断提示：

- 前端构建提示单个 chunk 超过 500 kB。
- 后端测试出现 OAuth 测试 socket `ResourceWarning`。
- 后端测试出现 Pillow `Image.getdata` deprecation warning。

这些目前不阻塞构建或测试通过。

## 主要未完成项和风险

### Unreal 集成仍偏兜底方案

Unreal MCP 目前主要做 endpoint 健康检查，尚未真正实现产品级 MCP 导入动作。

当前更可靠的路径是生成 Unreal Python 脚本。文档中提到的以下能力还需要继续补齐：

- 通过 MCP 创建目标 Content 目录。
- 通过 MCP 导入或创建资产。
- 创建 PaperSprite / PaperFlipbook。
- 更完整地设置 Texture import 属性。
- 创建基础 UMG Widget Blueprint。
- Common UI style 资产暂未进入真正完整实现。

### 质量校验深度不足

当前已有基础 manifest 和文件 / 帧一致性校验，但距离文档里设想的生产级校验还有差距。

仍需加强：

- 透明边缘脏污检测。
- alpha 输出为空检测。
- alpha halo / 黑白边检测。
- 像素风抗锯齿风险检测。
- sprite frame 边界和 pivot 稳定性检测。
- UI 状态尺寸和九宫格可拉伸性检测。
- Unreal 导入目标路径和导入设置冲突检测。

### 外部服务需要端到端实测

以下路径代码存在，但本次没有做真实外部调用验证：

- OpenAI API 图像生成 / 编辑。
- Codex OAuth 账号态图像生成。
- rembg optional runtime 和模型下载。
- SAM 2.1 optional runtime、checkpoint、CUDA 路径。
- Seedance image-to-video。
- Unreal Editor Python 实际执行。
- Unreal MCP 实际资产导入。

### 模型管理还不是完整产品体验

当前模型管理已有 registry、状态、lock、marker、删除和 SAM checkpoint 下载能力。

但还需要加强：

- 统一安装 / 修复 / 重新下载体验。
- 下载进度。
- checksum 实际校验。
- rembg 模型状态与真实缓存目录的更准确映射。
- RMBG 2.0 授权和本地路径配置闭环。

### 工程状态

- `.git` 目录存在但为空，当前不是有效 Git 仓库。
- 不能通过 Git 历史、分支、提交或 diff 判断实现进度。
- `node_modules`、`.venv`、构建产物和安装包都在本地工作区中，发布前需要明确归档 / 忽略 / 打包策略。

## 建议下一阶段优先级

1. 跑通一个真实端到端 demo：
   - 创建 `.uim` 项目。
   - 生成或导入一张 sprite。
   - rembg 处理。
   - 生成 manifest。
   - 生成 Unreal Python 脚本。
   - 在 Unreal Editor 中导入并确认纹理资产可用。

2. 把 Unreal 导入从“脚本兜底”推进到“可验证桥接”：
   - 先固定 Unreal Python 路径。
   - 再逐步补 MCP 实际动作。

3. 补齐质量校验的高价值项：
   - 文件存在。
   - alpha 空图。
   - 帧尺寸一致。
   - UI 状态尺寸一致。
   - Unreal content path 校验。

4. 做一次真实模型路径验证：
   - rembg CPU 路径。
   - SAM 2.1 tiny / small 下载和一次点选分割。

5. 整理发布工程：
   - 修复或重新初始化 Git。
   - 明确哪些目录进入源码管理。
   - 明确安装包是否内置 `.venv`。
   - 补发布说明和用户启动说明。

