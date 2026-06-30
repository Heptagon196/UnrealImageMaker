# UnrealImageMaker Context

UnrealImageMaker turns project-local prompts, references, and generated images into structured Unreal-ready art assets.

## Language

**WangTiles图**:
A 3-row by 5-column terrain transition source image used as the input for programmatic tilemap assembly.
_Avoid_: Wang源图, 地形风格参考图

**工作 tile**:
The high-resolution per-cell tile used while AI generates and refines a WangTiles图 before logical pixel conversion.
_Avoid_: 逻辑 tile, tile_size

**逻辑 tile**:
The final per-cell pixel size of a WangTiles图 or Tile Set after post-processing, used by runtime tilemap slicing.
_Avoid_: 工作 tile, 基准图尺寸
