# 本地模型管理

MVP 的模型策略：

- 大型模型不随安装包分发。
- 模型默认只下载到软件共享 `model-cache`。
- `.uim` 项目只保存 `models.lock.json`。
- 另一台电脑打开 `.uim` 项目时，根据 lock 文件自动检查并补齐缺失模型。

## 默认模型

- rembg 快速预览：`rembg:u2netp`
- rembg 通用抠图：`rembg:isnet-general-use`
- rembg 卡通 / 动漫：`rembg:isnet-anime`
- SAM 默认：`sam2.1_hiera_small`
- SAM 低显存：`sam2.1_hiera_tiny`
- RMBG 2.0：可选，默认禁用，需要用户确认授权。

## 状态

- `not_installed`
- `downloading`
- `installed`
- `update_available`
- `broken`
