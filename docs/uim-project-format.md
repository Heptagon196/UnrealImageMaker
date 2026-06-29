# `.uim` 项目格式

`.uim` 是 UnrealImageMaker 的目录型项目格式，不是单文件格式。

```text
MyAssetProject.uim/
  project.uim.json
  models.lock.json
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
- `target_engines`：目标引擎列表，MVP 默认为 `["unreal"]`。
- `model_cache`：模型缓存策略，MVP 固定为软件共享缓存。
- `settings`：扩展设置。

## `models.lock.json`

锁定项目使用的模型信息，但不保存模型本体。

另一台电脑打开项目时，软件根据 `models.lock.json` 检查本机 `model-cache`，缺失时提示下载同版本模型。

字段：

- `id`：模型 ID。
- `version`：模型版本。
- `source`：模型来源。
- `license`：授权说明。
- `checksum`：可选校验值。
