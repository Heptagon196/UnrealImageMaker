# Docs

这个目录只保留当前仍有维护价值的工程说明和 README 图片资产。

## 当前文档

- `uim-project-format.md`：`.uim` 目录型项目结构。
- `manifest-schema.md`：资产 manifest 的通用字段和 Unreal target。
- `unreal-export.md`：Unreal MCP / Unreal Python 导入脚本策略。
- `adr/0001-tilemap-wangtiles-logical-snap.md`：地形集生成的工作分辨率决策。
- `readme-assets/`：README 引用的截图和案例图，不放临时截图、运行日志或本地绝对路径。

## 清理原则

- 旧计划、旧评审和进度快照不放在 `docs/` 长期保留，避免与当前产品形态冲突。
- 已隐藏或暂未启用的能力不写成正式功能文档。
- README 图片只保留被 `README.md` 实际引用的文件。
