# Generate WangTiles At 256 Work Tile Resolution Before Logical Snap

Tilemap generation creates outer and primary terrain materials separately, builds and refines a 3x5 WangTiles work image at 256px per cell, then converts the result to the selected logical tile size before composing the current 16-tile corner set. This keeps AI refinement out of low-resolution pixel grids while preserving integer downsampling for power-of-two logical tiles such as 16, 32, 64, 128, and 256.
