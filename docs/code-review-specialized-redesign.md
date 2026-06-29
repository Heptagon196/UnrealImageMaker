# UnrealImageMaker 专项化重设计 Code Review

## Review Round 1

### 发现的问题

1. **UI 概念图 manifest 会被现有校验判定为无效**
   - 位置：`backend/uim_core/specialized.py:create_ui_concept`、`backend/uim_core/manifest.py:validate_manifest`
   - 问题：`create_ui_concept` 写出 `asset_type="ui_kit"`，但概念图阶段没有 `uiStates`。当前 `validate_manifest` 对所有 `ui_kit` 都强制要求 `uiStates`，所以 UI 概念图生成后如果进入资产校验会报错。
   - 风险：游戏 UI 两阶段流程第一步生成的核心资产无法通过本软件自己的 manifest 校验。
   - 状态：已修复并由 `backend:test` 覆盖

2. **生成 UI 控件贴图会覆盖同一资产的 UI 概念图信息**
   - 位置：`backend/uim_core/specialized.py:create_ui_widget`
   - 问题：控件生成直接重写 `assets/{asset_id}/manifests/manifest.json`，且 `processing` 只包含 `widgets` 和 `conceptPath`，会丢掉先前 `uiConcept` 的 prompt、布局、模型和流式事件。
   - 风险：UI 概念图和控件贴图之间的可追溯关系被破坏，后续 UE 导出和审查无法看到完整 UI 工作流。
   - 状态：已修复并由 `backend:test` 覆盖

3. **角色镜像方向没有实现，East / NorthEast / SouthEast 仍会调用 AI 生成**
   - 位置：`backend/uim_core/specialized.py:create_pixel_anchor`、`create_animation_sheet`，`src/main.tsx:PixelSpritesheetPage`
   - 问题：计划要求 East、NorthEast、SouthEast 由 West、NorthWest、SouthWest 镜像生成，当前只是把方向传进 prompt，仍然走图片 provider。
   - 风险：成本增加，而且对称方向一致性变差；UI 上标注了 mirror，但实际行为不一致。
   - 状态：已修复并由 `backend:test` 覆盖

4. **Seedance walk 视频输出路径固定，会覆盖同方向旧视频**
   - 位置：`backend/uim_core/specialized.py:create_seedance_walk_video`
   - 问题：输出文件名固定为 `walk_{direction}_{asset_id_from_name(direction)}.mp4`。同一资产同一方向重复生成会覆盖旧文件，资产版本索引也会因路径重复只保留最新版本。
   - 风险：丢失历史版本，违背现有“每次生成都保留版本”的资产流程。
   - 状态：已修复并由 `backend:test` 覆盖

5. **UI 控件类型未校验，未知类型会静默当作 icon**
   - 位置：`backend/uim_core/specialized.py:create_ui_widget`
   - 问题：`widget_type` 只通过条件表达式分支，非 `button` / `panel` 的输入都会落到 `icon`。
   - 风险：前端或外部 API 调错参数时不会失败，manifest 语义和用户意图不一致。
   - 状态：已修复并由 `backend:test` 覆盖

### 修复验证

- `npm.cmd run backend:test`：31 tests OK
- `npm.cmd run build`：通过

## Review Round 2

### 发现的问题

1. **参考图传给不支持 image edit 的 provider 时会被静默忽略**
   - 位置：`backend/uim_core/specialized.py:_generate_image`
   - 问题：`reference_path` 只有在 provider 是 `OpenAIImageProvider` 时才走 `edit`，否则会直接调用 `generate`。这会让 Codex OAuth 路径下的 UI 控件贴图或 spritesheet 看起来引用了概念图/anchor，实际完全没有使用参考图。
   - 风险：用户得到风格不一致的资产，而且日志和 manifest 不会提示参考图被忽略。
   - 状态：已修复并由 `backend:test` 覆盖

2. **Seedance walk 允许空或不存在的 anchor 路径进入 provider**
   - 位置：`backend/uim_core/api.py:api_seedance_walk`、`backend/uim_core/specialized.py:create_seedance_walk_video`、`src/main.tsx:PixelSpritesheetPage`
   - 问题：前端 Seedance 按钮只判断角色类型，不要求 anchor。后端收到空路径时会把 `Path("")` 当作当前目录传给 provider。
   - 风险：错误信息会变成 provider/network 层错误，用户无法判断是缺少 anchor。
   - 状态：已修复并由 `backend:test` 覆盖

3. **47-tile manifest 可登记不存在的 tileset 图片**
   - 位置：`backend/uim_core/specialized.py:create_tilemap_47_manifest`
   - 问题：函数只把路径转成项目相对路径，不检查文件是否存在。
   - 风险：资产列表出现无法预览、无法导出的 Tilemap 资产，问题被推迟到后续校验或 UE 导出。
   - 状态：已修复并由 `backend:test` 覆盖

### 修复验证

- `npm.cmd run backend:test`：34 tests OK
- `npm.cmd run build`：通过

## Review Round 3

### 复查范围

- `backend/uim_core/specialized.py`：专项生成、镜像、归一化、UI manifest 合并、Seedance 输出。
- `backend/uim_core/api.py`：专项 API 请求模型、运行时设置、路径解析。
- `src/main.tsx`：主导航、专项页面按钮状态、资产刷新、日志事件。
- `backend/tests/test_specialized_pipelines.py`：前两轮问题的回归覆盖。

### 结论

- 未发现新的需要修改的问题。
- 前两轮问题均已有对应修复和测试覆盖。
- 已知非阻断项：`backend:test` 输出 Pillow `getdata` deprecation warning，以及 OAuth 测试里的 socket `ResourceWarning`。它们不是本轮专项化改动引入的功能 bug，当前不影响测试通过或运行路径。

### 最终验证

- `npm.cmd run backend:test`：34 tests OK
- `npm.cmd run build`：通过
