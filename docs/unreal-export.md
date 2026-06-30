# Unreal 导出方案

项目不直接手写 `.uasset`。

推荐流程：

```text
UnrealImageMaker asset manifest
  -> 生成 PNG / JSON
  -> 导出到 Unreal 暂存目录或用户指定目录
  -> Unreal MCP 优先导入
  -> MCP 不足时生成 Unreal Python 脚本
```

## Python 兜底脚本

后端会根据 manifest 生成 Unreal Python 脚本。脚本使用 `unreal.AssetImportTask` 导入图片，并设置基础 Texture2D 属性。

## 插件策略

当前不内置 UE 插件。后续插件只负责更好的编辑器入口、菜单、右键动作、Data Validation 和更深 Common UI / Paper2D 集成。
