# `.uim` 项目格式

`.uim` 是 UnrealImageMaker 的目录型项目格式，不是单文件格式。

```text
MyAssetProject.uim/
  project.uim.json
  profiles/
  assets/
  exports/
    unreal/
  cache/
```

## `project.uim.json`

保存项目自身配置：

- `schema`：项目 schema，例如 `uim.project.v1`。
- `id`：项目 UUID。
- `name`：项目显示名。
- `default_style`：默认风格配置 ID。
- `target_engines`：目标引擎列表，当前主要面向 `["unreal"]`。
- `model_cache`：模型缓存策略；当前运行时使用软件共享缓存。
- `settings`：扩展设置。

## `models.lock.json`

可选文件，用于记录项目曾使用的模型信息，但不保存模型本体。

当前正式工作流不依赖本地分割模型；如果项目存在 `models.lock.json`，运行时可以用它检查本机模型缓存是否缺失。

字段：

- `id`：模型 ID。
- `version`：模型版本。
- `source`：模型来源。
- `license`：授权说明。
- `checksum`：可选校验值。
