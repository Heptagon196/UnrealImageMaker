# Manifest Schema

UnrealImageMaker 的所有资产都编译成 JSON manifest。引擎适配器只消费 manifest，不直接消费 AI 模型输出。

## 通用字段

- `schema`：当前为 `uim.asset_manifest.v1`。
- `assetType`：`texture`、`spritesheet`、`animation`、`ui_kit` 或 `nine_slice`。
- `id`：资产 ID。
- `displayName`：显示名。
- `styleProfile`：风格配置 ID。
- `files`：资产文件列表。
- `frames`：sprite 帧列表。
- `animations`：动画序列列表。
- `uiStates`：UI 状态列表。
- `nineSlice`：九宫格边界。
- `processing`：生成和后处理元数据。
- `targets`：引擎导出目标。

## Unreal Target

```json
{
  "targets": {
    "unreal": {
      "contentPath": "/Game/UIM",
      "create": ["Texture2D", "PaperSprite", "PaperFlipbook"]
    }
  }
}
```

MVP 阶段由 Unreal MCP 优先处理导入；MCP 覆盖不足时生成 Unreal Python 脚本。
