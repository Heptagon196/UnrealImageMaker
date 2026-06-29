from __future__ import annotations

import math
import base64
import shutil
import subprocess
import tempfile
from collections import Counter, deque
from io import BytesIO
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Sequence

from .asset_index import asset_id_from_name, load_asset_index, register_asset_version, sorted_versions, versioned_filename
from .constants import API_CONTRACT_VERSION
from .image_processing import _require_pillow
from .json_io import read_json
from .manifest import AnimationSequence, AssetFile, AssetManifest, NineSlice, SpriteFrame, UIState, write_manifest
from .pixel_postprocess import PixelMaskMode, PixelRestoreMode, apply_pixel_mask, frame_qa_summary, run_unfake_restore, write_qa_report
from .providers.codex_oauth_image import CodexOAuthImageProvider
from .providers.openai_image import ImageGenerationResult, OpenAIImageProvider
from .providers.rembg_adapter import RembgAdapter
from .providers.seedance_provider import SeedanceProvider

CHARACTER_GENERATED_DIRECTIONS = ["south", "north", "west", "east"]
CHARACTER_MIRRORED_DIRECTIONS = {"east": "west"}
CHARACTER_DIRECTIONS_8 = [*CHARACTER_GENERATED_DIRECTIONS]
CHARACTER_DIRECTION_DESCRIPTIONS = {
    "south": "facing SOUTH directly toward the camera in a 3/4 top-down game perspective",
    "west": "facing left in profile, both feet visible, body in 3/4 left turn",
    "north": "facing away from the camera, back view, both feet visible",
    "east": "facing right in profile, both feet visible, body in 3/4 right turn",
    "single": "single direction, centered toward the viewer or the intended gameplay camera",
}
TILEMAP_47_IDS = [
    "center", "north", "south", "west", "east", "north_west_edge", "north_east_edge", "south_west_edge", "south_east_edge",
    "outer_nw", "outer_ne", "outer_sw", "outer_se", "inner_nw", "inner_ne", "inner_sw", "inner_se",
    *[f"transition_{index:02d}" for index in range(30)],
]
TILEMAP_DUAL_GRID_16_IDS = [f"mask_{mask:02d}" for mask in range(16)]
TILEMAP_DUAL_GRID_16_MASK_BITS = {"NW": 1, "NE": 2, "SW": 4, "SE": 8}


def _video_ffmpeg_executable() -> tuple[str, str]:
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).exists():
            return str(bundled), "imageio-ffmpeg"
    except Exception:
        pass
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg, "ffmpeg"
    raise RuntimeError("Bundled ffmpeg is unavailable. Reinstall backend dependencies or install ffmpeg on PATH.")


def _preview_frame_background(Image, width: int, height: int):
    background = Image.new("RGBA", (width, height), (238, 242, 246, 255))
    tile = 16
    for y in range(0, height, tile):
        for x in range(0, width, tile):
            if ((x // tile) + (y // tile)) % 2 == 0:
                block = Image.new("RGBA", (min(tile, width - x), min(tile, height - y)), (222, 229, 238, 255))
                background.paste(block, (x, y))
    return background


def _create_concept_reference(output_path: Path, asset_kind: str, size: int = 1024) -> None:
    Image, _, _ = _require_pillow()
    from PIL import ImageDraw

    image = Image.new("RGBA", (size, size), (248, 250, 252, 255))
    draw = ImageDraw.Draw(image)
    margin = size // 10
    draw.rectangle((margin, margin, size - margin, size - margin), outline=(196, 207, 222, 255), width=max(2, size // 180))
    draw.line((size // 2, margin, size // 2, size - margin), fill=(218, 226, 237, 255), width=max(1, size // 260))
    draw.line((margin, size // 2, size - margin, size // 2), fill=(218, 226, 237, 255), width=max(1, size // 260))
    draw.text((margin, margin // 2), f"{asset_kind} concept reference canvas", fill=(86, 99, 117, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _direction_description(direction: str) -> str:
    return CHARACTER_DIRECTION_DESCRIPTIONS.get(direction, direction.replace("_", " "))


def _provider(image_provider: str):
    if image_provider == "codex_oauth":
        return CodexOAuthImageProvider()
    if image_provider == "openai_api":
        return OpenAIImageProvider()
    raise ValueError(f"Unknown image provider: {image_provider}")


def _generate_image(
    prompt: str,
    output_path: Path,
    image_provider: str,
    *,
    size: str = "1024x1024",
    reference_path: Path | None = None,
    reference_paths: Sequence[Path] | None = None,
) -> ImageGenerationResult:
    provider = _provider(image_provider)
    references = list(reference_paths or ([] if reference_path is None else [reference_path]))
    if references:
        for path in references:
            if not path.exists() or not path.is_file():
                raise ValueError(f"Reference image does not exist: {path}")
        if len(references) > 1:
            edit_many = getattr(provider, "edit_many", None)
            if callable(edit_many):
                return edit_many(prompt, references, output_path, size=size)
        edit = getattr(provider, "edit", None)
        if callable(edit) and len(references) == 1:
            return edit(prompt, references[0], output_path, size=size)
        raise RuntimeError(f"Image provider {image_provider} does not support reference image input")
    return provider.generate(prompt, output_path, size=size)


def _asset_dirs(project_root: Path, asset_name: str) -> tuple[str, Path, Path]:
    asset_id = asset_id_from_name(asset_name)
    root = project_root / "assets" / asset_id
    generated = root / "generated"
    manifests = root / "manifests"
    generated.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    return asset_id, generated, manifests


def _asset_manifest_dir(project_root: Path, asset_id: str) -> Path:
    manifests = project_root / "assets" / asset_id / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    return manifests


def _ui_concept_dir(project_root: Path, asset_id: str) -> Path:
    output_dir = project_root / "ui" / "concepts" / asset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _rel(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _latest_version_path(project_root: Path, asset_id: str, role: str) -> Path | None:
    index = load_asset_index(project_root, asset_id)
    for version in sorted_versions(index.versions):
        if version.role == role:
            candidate = (project_root / version.path).resolve()
            candidate.relative_to(project_root.resolve())
            if candidate.exists():
                return candidate
    return None


def _mirror_image(source_path: Path, output_path: Path) -> None:
    Image, _, _ = _require_pillow()
    with Image.open(source_path) as image:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGBA").transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(output_path)


def _mirror_sheet_cells(source_path: Path, output_path: Path, columns: int, rows: int, cell_width: int, cell_height: int) -> None:
    Image, _, _ = _require_pillow()
    with Image.open(source_path) as image:
        source = image.convert("RGBA")
        output = Image.new("RGBA", source.size, (0, 0, 0, 0))
        for row in range(rows):
            for column in range(columns):
                box = (column * cell_width, row * cell_height, (column + 1) * cell_width, (row + 1) * cell_height)
                cell = source.crop(box).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                output.paste(cell, (column * cell_width, row * cell_height), cell)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_path)


def _create_anchor_grid_reference(output_path: Path, asset_kind: str, direction: str, size: int = 1024, logical_frame_size: str = "256x256") -> None:
    Image, _, _ = _require_pillow()
    from PIL import ImageDraw
    logical_width, logical_height = _parse_size(logical_frame_size)
    if logical_width <= 0 or logical_height <= 0:
        raise ValueError(f"Logical frame size must be positive: {logical_frame_size}")
    if size % logical_width != 0 or size % logical_height != 0:
        raise ValueError(f"Anchor output size {size}x{size} must be an integer upscale of logical frame size {logical_frame_size}")
    scale_x = size // logical_width
    scale_y = size // logical_height
    if scale_x != scale_y:
        raise ValueError(f"Anchor output scale must be uniform: output {size}x{size}, logical {logical_frame_size}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    pixels = image.load()
    block = max(1, scale_x)
    for y in range(size):
        for x in range(size):
            shade = 28 if ((x // block) + (y // block)) % 2 == 0 else 232
            pixels[x, y] = (shade, shade, shade, 255)
    draw = ImageDraw.Draw(image)
    step = size // 16
    line_color = (0, 204, 255, 130)
    guide_color = (255, 0, 255, 230)
    for value in range(0, size + 1, step):
        width = 3 if value % (step * 4) == 0 else 1
        draw.line((value, 0, value, size), fill=line_color, width=width)
        draw.line((0, value, size, value), fill=line_color, width=width)
    center_x = size // 2
    foot_y = int(size * 0.78)
    body_top = int(size * 0.18)
    body_bottom = int(size * 0.82)
    body_left = int(size * 0.32)
    body_right = int(size * 0.68)
    draw.rectangle((body_left, body_top, body_right, body_bottom), outline=guide_color, width=8)
    draw.line((center_x, body_top - 48, center_x, body_bottom + 48), fill=(0, 255, 255, 240), width=6)
    draw.line((body_left - 80, foot_y, body_right + 80, foot_y), fill=(255, 230, 0, 240), width=6)
    draw.ellipse((center_x - 14, foot_y - 14, center_x + 14, foot_y + 14), fill=(255, 230, 0, 255))
    draw.rectangle((20, 20, 470, 100), fill=(255, 255, 255, 220))
    draw.text((32, 28), f"{asset_kind} pixel-grid reference", fill=(24, 27, 33, 255))
    draw.text((32, 62), f"direction: {direction} | logical: {logical_frame_size} | scale: {scale_x}x", fill=(24, 27, 33, 255))
    draw.rectangle((20, size - 92, 640, size - 24), fill=(255, 255, 255, 220))
    draw.text((32, size - 72), "pixel scale + center line + foot baseline + silhouette bounds", fill=(24, 27, 33, 255))
    image.save(output_path)


def _logical_grid_discipline(logical_frame_size: str, output_size: str) -> str:
    logical_width, logical_height = _parse_size(logical_frame_size)
    scale = _anchor_output_scale(logical_frame_size, output_size)
    return (
        "Pixel-grid discipline:\n"
        f"- Treat the artwork as a {logical_width}x{logical_height} logical pixel grid, delivered on a {output_size} canvas.\n"
        f"- Each logical pixel should read as one {scale}x{scale} same-color block in the delivered image.\n"
        "- Use hand-pixeled 2D sprite clusters: hard edges, limited palette, dark outline, flat cel shading, and deliberate color ramps.\n"
        "- Do not create a 3D render, toy render, clay model, soft airbrush, volumetric lighting, output-resolution micro-detail, painterly texture, subpixel lines, or anti-aliased blur.\n"
        "- Details must remain readable after nearest-neighbor reduction back to the logical frame size.\n\n"
        "Background discipline:\n"
        "- Fill every non-sprite pixel on the entire canvas with exact #FF00FF.\n"
        "- The PNG must be fully opaque: no transparent pixels, no alpha background, no checkerboard, no black/white/gray empty background.\n"
        "- Do not add cast shadows, floor patches, scenery, gradients, borders, or glow halos in the background.\n\n"
    )


def _force_chroma_background(image: Any) -> Any:
    Image, _, _ = _require_pillow()
    source = image.convert("RGBA")
    rgba = Image.new("RGBA", source.size, (255, 0, 255, 255))
    rgba.alpha_composite(source)
    rgba = _replace_edge_connected_background_with_chroma(rgba)
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a < 255 or _is_chroma_like(r, g, b):
                pixels[x, y] = (255, 0, 255, 255)
            else:
                pixels[x, y] = (r, g, b, 255)
    return rgba


def _is_chroma_like(r: int, g: int, b: int) -> bool:
    return r >= 190 and b >= 190 and g <= 110


def _dominant_edge_colors(image: Any) -> list[tuple[int, int, int]]:
    pixels = image.load()
    width, height = image.size
    if width <= 0 or height <= 0:
        return []
    step = max(1, min(width, height) // 128)
    samples: list[tuple[int, int, int]] = []
    for x in range(0, width, step):
        for y in (0, height - 1):
            r, g, b, a = pixels[x, y]
            if a > 0 and not _is_chroma_like(r, g, b):
                samples.append((r, g, b))
    for y in range(0, height, step):
        for x in (0, width - 1):
            r, g, b, a = pixels[x, y]
            if a > 0 and not _is_chroma_like(r, g, b):
                samples.append((r, g, b))
    buckets = Counter((r // 16, g // 16, b // 16) for r, g, b in samples)
    return [(r * 16 + 8, g * 16 + 8, b * 16 + 8) for (r, g, b), _count in buckets.most_common(4)]


def _is_edge_background_pixel(r: int, g: int, b: int, a: int, reference_colors: Sequence[tuple[int, int, int]]) -> bool:
    if a < 255 or _is_chroma_like(r, g, b):
        return True
    return any(max(abs(r - rr), abs(g - gg), abs(b - bb)) <= 56 for rr, gg, bb in reference_colors)


def _replace_edge_connected_background_with_chroma(image: Any) -> Any:
    width, height = image.size
    if width <= 0 or height <= 0:
        return image
    reference_colors = _dominant_edge_colors(image)
    pixels = image.load()
    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def index(x: int, y: int) -> int:
        return y * width + x

    def enqueue_if_background(x: int, y: int) -> None:
        idx = index(x, y)
        if visited[idx]:
            return
        r, g, b, a = pixels[x, y]
        if _is_edge_background_pixel(r, g, b, a, reference_colors):
            visited[idx] = 1
            queue.append((x, y))

    for x in range(width):
        enqueue_if_background(x, 0)
        enqueue_if_background(x, height - 1)
    for y in range(height):
        enqueue_if_background(0, y)
        enqueue_if_background(width - 1, y)

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                enqueue_if_background(nx, ny)

    for y in range(height):
        for x in range(width):
            if visited[index(x, y)]:
                pixels[x, y] = (255, 0, 255, 255)
    return image


def _snap_anchor_to_logical_grid(image_path: Path, logical_frame_size: str, output_size: str) -> dict[str, int]:
    Image, _, _ = _require_pillow()
    logical_width, logical_height = _parse_size(logical_frame_size)
    output_width, output_height = _parse_size(output_size)
    if logical_width <= 0 or logical_height <= 0:
        raise ValueError(f"Logical frame size must be positive: {logical_frame_size}")
    if output_width % logical_width != 0 or output_height % logical_height != 0:
        raise ValueError(f"Anchor output size {output_size} must be an integer upscale of logical frame size {logical_frame_size}")
    scale_x = output_width // logical_width
    scale_y = output_height // logical_height
    if scale_x != scale_y:
        raise ValueError(f"Anchor output scale must be uniform: output {output_size}, logical {logical_frame_size}")
    with Image.open(image_path) as image:
        rgba = _force_chroma_background(image)
        logical = rgba.resize((logical_width, logical_height), Image.Resampling.BOX)
        logical = _force_chroma_background(logical)
        alpha = logical.getchannel("A")
        quantized = logical.convert("RGB").quantize(colors=32, method=Image.Quantize.MEDIANCUT).convert("RGBA")
        quantized.putalpha(alpha)
        logical = _force_chroma_background(quantized)
        snapped = logical.resize((output_width, output_height), Image.Resampling.NEAREST)
        snapped.save(image_path)
    return {
        "logicalWidth": logical_width,
        "logicalHeight": logical_height,
        "outputWidth": output_width,
        "outputHeight": output_height,
        "scale": scale_x,
        "paletteColors": 32,
        "backgroundMode": "opaque_edge_connected_chroma",
    }


def _compose_reference_pair(left_path: Path, right_path: Path, output_path: Path, left_label: str, right_label: str) -> Path:
    if not left_path.exists() or not left_path.is_file():
        raise ValueError(f"Reference image does not exist: {left_path}")
    if not right_path.exists() or not right_path.is_file():
        raise ValueError(f"Reference image does not exist: {right_path}")
    Image, _, _ = _require_pillow()
    from PIL import ImageDraw
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (2048, 1024), (246, 248, 251, 255))
    draw = ImageDraw.Draw(canvas)
    with Image.open(left_path) as left_image, Image.open(right_path) as right_image:
        left = left_image.convert("RGBA")
        left.thumbnail((944, 944))
        right = right_image.convert("RGBA")
        right.thumbnail((944, 944))
        canvas.paste(left, (40 + (944 - left.width) // 2, 64 + (944 - left.height) // 2), left)
        canvas.paste(right, (1064 + (944 - right.width) // 2, 64 + (944 - right.height) // 2), right)
    draw.text((40, 24), left_label, fill=(24, 27, 33, 255))
    draw.text((1064, 24), right_label, fill=(24, 27, 33, 255))
    canvas.save(output_path)
    return output_path


def _create_sheet_guide_reference(output_path: Path, columns: int, rows: int, cell_size: int) -> None:
    Image, _, _ = _require_pillow()
    from PIL import ImageDraw
    width = columns * cell_size
    height = rows * cell_size
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (width, height), (255, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    for row in range(rows):
        for column in range(columns):
            x0 = column * cell_size
            y0 = row * cell_size
            x1 = x0 + cell_size
            y1 = y0 + cell_size
            fill = (238, 243, 249, 255) if (row + column) % 2 == 0 else (220, 228, 238, 255)
            draw.rectangle((x0, y0, x1, y1), fill=fill, outline=(24, 27, 33, 220), width=max(2, cell_size // 64))
            draw.line((x0 + cell_size // 2, y0 + cell_size // 8, x0 + cell_size // 2, y1 - cell_size // 8), fill=(0, 170, 255, 180), width=max(1, cell_size // 96))
            draw.line((x0 + cell_size // 8, y1 - cell_size // 5, x1 - cell_size // 8, y1 - cell_size // 5), fill=(255, 180, 0, 210), width=max(1, cell_size // 96))
            draw.text((x0 + 8, y0 + 8), f"{row * columns + column + 1}", fill=(24, 27, 33, 255))
    image.save(output_path)


def _parse_size(size: str) -> tuple[int, int]:
    try:
        width_text, height_text = size.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise ValueError(f"Size must use WIDTHxHEIGHT format: {size}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"Size must be positive: {size}")
    return width, height


def _square_size_pixels(size: str) -> int:
    width, height = _parse_size(size)
    if width != height:
        raise ValueError(f"Anchor output size must be square: {size}")
    return width


def _anchor_output_scale(logical_frame_size: str, output_size: str) -> int:
    logical_width, logical_height = _parse_size(logical_frame_size)
    output_width, output_height = _parse_size(output_size)
    if output_width != output_height:
        raise ValueError(f"Anchor output size must be square: {output_size}")
    if logical_width <= 0 or logical_height <= 0:
        raise ValueError(f"Logical frame size must be positive: {logical_frame_size}")
    if output_width % logical_width != 0 or output_height % logical_height != 0:
        raise ValueError(f"Anchor output size {output_size} must be an integer upscale of logical frame size {logical_frame_size}")
    scale_x = output_width // logical_width
    scale_y = output_height // logical_height
    if scale_x != scale_y:
        raise ValueError(f"Anchor output scale must be uniform: output {output_size}, logical {logical_frame_size}")
    return scale_x


def _box_art_prompt(subject: str, asset_kind: str) -> str:
    if asset_kind == "weapon":
        return (
            "Create a high-resolution concept illustration for a single game weapon asset for a top-down 2D battle game.\n\n"
            "Format:\n"
            "- square PNG concept image\n"
            "- one isolated weapon design, not a portrait\n"
            "- readable silhouette that can later translate into a small pixel sprite\n"
            "- clear material language, edge shape, grip/handle orientation, and damage profile\n\n"
            "Weapon:\n"
            f"- {subject}\n"
            "- show the full weapon from tip to handle\n"
            "- make the primary shape recognizable at small size\n"
            "- include restrained magic, glow, engraving, gem, or elemental detail only if it belongs to the design\n\n"
            "Composition:\n"
            "- centered single weapon\n"
            "- no hand, arm, wielder, body, costume, or portrait pose\n"
            "- background can support the material read, but must not overpower the silhouette\n\n"
            "Avoid:\n"
            "- text, logos, UI, watermark\n"
            "- duplicate weapons unless explicitly requested\n"
            "- scene props that confuse the weapon outline\n\n"
            "This image is a weapon design reference only. It must not be used as a direct image-to-image sprite source."
        )
    if asset_kind == "decoration":
        return (
            "Create a high-resolution concept illustration for a single placeable decoration or environmental prop for a top-down 2D game.\n\n"
            "Format:\n"
            "- square PNG concept image\n"
            "- one isolated decoration/prop design\n"
            "- readable top-down-game silhouette that can later translate into a small pixel asset\n"
            "- clear material, volume, footprint, and gameplay placement readability\n\n"
            "Decoration:\n"
            f"- {subject}\n"
            "- show the whole object with its base/footprint visible\n"
            "- make its material and purpose readable at small size\n"
            "- optional subtle glow, flame, sparkle, or ambient effect only if it belongs to the prop\n\n"
            "Composition:\n"
            "- centered single prop or decoration\n"
            "- no humanoid figure, hand, costume, body, or portrait pose\n"
            "- background can support the object, but must not become scenery\n\n"
            "Avoid:\n"
            "- text, logos, UI, watermark\n"
            "- busy room scenes or large environment paintings\n"
            "- multiple unrelated props unless explicitly requested\n\n"
            "This image is a decoration design reference only. It must not be used as a direct image-to-image sprite source."
        )
    return (
        f"Create a high-resolution box-art portrait for a {asset_kind} game asset for a top-down 2D battle game.\n\n"
        "Format:\n"
        "- 1024x1536 PNG\n"
        "- 2:3 portrait\n"
        "- full-body or near full-body 3/4 hero composition\n"
        "- painterly illustration with strong silhouette logic that can later translate into pixel/game sprites\n\n"
        "Character:\n"
        f"- {subject}\n"
        "- readable costume and color palette\n"
        "- clear signature prop if the design includes one\n"
        "- personality visible through pose and silhouette\n\n"
        "World/background:\n"
        "- same world language as the rest of the roster\n"
        "- background supports the character, but does not overpower them\n\n"
        "Avoid:\n"
        "- text, logos, UI, watermark\n"
        "- symbols/runes/glyphs unless explicitly part of the design\n"
        "- background motifs that belong to another character\n\n"
        "This image is vibe and silhouette reference only. It must not be used as a direct image-to-image sprite source."
    )


def _ensure_image_generation_kind(asset_kind: str) -> None:
    if asset_kind == "tilemap":
        raise ValueError("Tilemap assets do not use pixel image generation. Import a tileset image and use tilemap-47 manifest generation instead.")


def _object_anchor_prompt(subject: str, asset_kind: str, logical_frame_size: str, output_size: str, uses_concept: bool = False) -> str:
    if asset_kind == "weapon":
        object_label = "weapon"
        purpose = "inventory icon, pickup sprite, or effect-ready weapon asset"
        details = (
            "- show exactly one complete weapon, fully visible from tip to handle\n"
            "- preserve grip direction and readable edge/point silhouette\n"
            "- no character, no wielder, no hand, no arm, no body, no face\n"
            "- keep magic glow or engravings small and attached to the weapon"
        )
    elif asset_kind == "decoration":
        object_label = "decoration prop"
        purpose = "placeable map decoration or interactive environmental prop"
        details = (
            "- show exactly one complete prop, fully visible with base/footprint\n"
            "- preserve top-down placement readability and material volume\n"
            "- no character, no hand, no face, no portrait composition\n"
            "- keep ambient glow, flame, or particles small and attached to the prop"
        )
    else:
        object_label = f"{asset_kind} object"
        purpose = "game-ready isolated object asset"
        details = (
            "- show exactly one complete object\n"
            "- preserve readable silhouette and material identity\n"
            "- no character, no hand, no face, no text\n"
            "- keep effects small and attached to the object"
        )
    if uses_concept:
        input_description = (
            "Input reference images:\n"
            "- Image 1 is concept art. Use it only for design language: object identity, silhouette vocabulary, material, palette, and signature details.\n"
            "- Do not copy Image 1 composition, camera angle, pose, lighting, shadows, scene background, or scale.\n"
            "- Image 2 is the pixel-grid anchor. It defines the final object bounds, center position, logical pixel scale, and clean #FF00FF background discipline.\n"
            "- The final output must be a new isolated object anchor, not an image-to-image conversion of Image 1.\n\n"
        )
    else:
        input_description = (
            "Input image:\n"
            "Image 1 is a pixel-grid anchor. Use it only to enforce chunky pixel-art block discipline, center position, and clean object bounds. Do not copy its content.\n\n"
        )
    return (
        f"Create a single pixel-art {object_label} anchor for a top-down 2D game.\n\n"
        f"{input_description}"
        "Intended use:\n"
        f"- {purpose}\n"
        f"- final artwork should behave like one logical {logical_frame_size} in-game frame, delivered at {output_size}\n\n"
        f"{_logical_grid_discipline(logical_frame_size, output_size)}"
        "Subject:\n"
        f"- {subject}\n\n"
        "Object rules:\n"
        f"{details}\n"
        "- centered single object\n"
        "- ample padding on every side\n"
        "- crisp readable silhouette at small size\n\n"
        "Style:\n"
        "- hand-pixeled 2D game asset enlarged with nearest-neighbor blocks\n"
        "- crisp hard edges, limited palette, 1-logical-pixel dark outline, no soft rendering\n"
        "- flat cel shading with a few deliberate color steps, consistent top-left light\n"
        "- solid #FF00FF chroma background outside the object\n\n"
        "Avoid:\n"
        "- no scene background, no floor shadow, no UI, no text, no logo, no watermark\n"
        "- guide lines, labels, frame numbers, or visible grid marks"
    )


def _south_anchor_prompt(subject: str, logical_frame_size: str, output_size: str, uses_concept: bool = False) -> str:
    if uses_concept:
        input_description = (
            "Input reference images:\n"
            "- Image 1 is concept art. Use it only for design language: character identity, costume motifs, palette, silhouette vocabulary, and signature details.\n"
            "- Do not copy Image 1 pose, camera angle, body direction, composition, lighting, shadows, scene background, or scale.\n"
            "- Image 2 is the pixel-grid anchor. It defines the final SOUTH-facing idle pose, centered single-frame composition, logical pixel scale, foot baseline, bounds, and #FF00FF background discipline.\n"
            "- The final output must be a newly constructed front-facing game sprite anchor, not an image-to-image conversion of Image 1.\n\n"
        )
    else:
        input_description = (
            "Image 1 role: pixel-grid anchor. Use it only to enforce chunky pixel-art block discipline and a centered single-frame composition. "
            "Do not copy its content.\n\n"
        )
    return (
        "Intended use: a single south-facing idle sprite frame for a top-down 2D action game. "
        f"Final artwork should behave like one logical {logical_frame_size} in-game frame, delivered at {output_size} "
        "so each sprite pixel reads as a clean block.\n\n"
        f"{_logical_grid_discipline(logical_frame_size, output_size)}"
        f"{input_description}"
        "Subject:\n"
        f"- {subject}, facing SOUTH directly toward the camera in 3/4 top-down game perspective.\n"
        "- This is the canonical idle frame.\n"
        "- calm readable idle expression/pose.\n\n"
        "Frame rules:\n"
        "- One character only, centered.\n"
        "- Full body visible.\n"
        "- Visible body fits within the intended logical sprite box.\n"
        "- Anchor/foot plant at bottom-center.\n"
        "- Preserve idle readability, not an attack pose.\n\n"
        "Style:\n"
        "- hand-pixeled SNES-era 2D game sprite enlarged with nearest-neighbor blocks\n"
        "- chunky readable silhouette\n"
        "- crisp hard edges and 1-logical-pixel dark outline\n"
        "- limited palette, flat cel shading, small deliberate highlight pixels\n"
        "- consistent top-left light source\n\n"
        "Background:\n"
        "- solid removable chroma color, preferably #FF00FF, outside the sprite silhouette\n"
        "- no scenery, props, borders, UI, text, logo, or watermark\n\n"
        "Avoid:\n"
        "- photorealism\n"
        "- painterly blending\n"
        "- anti-aliased halos\n"
        "- extra characters\n"
        "- complex background\n"
        "- symbols/runes/text if not wanted"
    )


def _neutral_anchor_prompt(subject: str, dynamic_effect: str, logical_frame_size: str, output_size: str, candidate_count: int = 1) -> str:
    return (
        "Intended use: corrected reusable SOUTH-facing neutral idle anchor sprite for a top-down 2D game character.\n\n"
        "Input images:\n"
        "Image 1 is the approved south-facing identity anchor. Preserve this exact character identity, detail level, face, outfit, palette, prop, proportions, silhouette, and sprite scale.\n"
        "Image 2 is the pixel/grid anchor. Use it to preserve output discipline and pixelated sprite feel. Do not copy its content.\n\n"
        "Primary request:\n"
        f"Create {candidate_count} candidate variant of the same SOUTH-facing neutral idle anchor. "
        f"The only intended design correction from Image 1 is removing {dynamic_effect}.\n"
        f"Final artwork should behave like one logical {logical_frame_size} in-game frame, delivered at {output_size}.\n\n"
        f"{_logical_grid_discipline(logical_frame_size, output_size)}"
        "Subject:\n"
        f"- {subject}.\n"
        "- Facing SOUTH, directly toward the camera.\n"
        "- Same silhouette, outfit, palette, prop, face readability, and body scale as Image 1.\n"
        "- hands and body should be neutral and resting naturally.\n\n"
        "Preserve from Image 1:\n"
        "- same face readability\n"
        "- same silhouette and proportions\n"
        "- same costume colors\n"
        "- same prop size/detail\n"
        "- same centered composition\n"
        "- same hand-pixeled low-color sprite treatment\n\n"
        "Change from Image 1:\n"
        f"- remove {dynamic_effect}\n"
        "- remove glow, particles, smoke, aura, projectile, and charged action pose\n"
        "- make the pose read as neutral idle\n\n"
        "Background:\n"
        "- solid uniform chroma background outside the character\n"
        "- no gradients, noise, shadows, scenery, text, border, or UI\n\n"
        "Avoid:\n"
        "- redesigning the character\n"
        "- simplifying key identity details\n"
        "- changing scale or silhouette\n"
        "- adding action effects"
    )


def _directional_silhouette_details(direction: str) -> str:
    if direction == "west":
        return "clear left-facing side profile, nose/chest/feet oriented left, readable side silhouette, no frontal face or front-facing torso"
    if direction == "east":
        return "clear right-facing side profile, nose/chest/feet oriented right, readable side silhouette, no frontal face or front-facing torso"
    if direction == "north":
        return "clear back view with back of head, back of outfit, rear silhouette, no visible front face or front-facing torso"
    return "clear direction-specific silhouette, no front-facing fallback"


def _directional_anchor_prompt(subject: str, direction: str, logical_frame_size: str, output_size: str, side_reference_direction: str | None = None) -> str:
    direction_description = _direction_description(direction)
    silhouette_details = _directional_silhouette_details(direction)
    if side_reference_direction:
        input_images = (
            "Input images:\n"
            "Image 1 is the approved neutral SOUTH-facing identity anchor. Preserve character identity, outfit, palette, proportions, accessories, and hand-pixeled game-sprite style.\n"
            f"Image 2 is the approved {side_reference_direction.upper()}-facing side anchor. Use it for side-view pose structure, foot baseline, side silhouette, accessory depth, and proportion consistency.\n"
            "Image 3 is an alternating black/white pixel-grid reference. Use it only as a pixel-texture and clean-background guide.\n\n"
        )
    else:
        input_images = (
            "Input images:\n"
            "Image 1 is the approved neutral SOUTH-facing identity anchor. Preserve the same character identity, outfit, palette, proportions, silhouette, accessories, and hand-pixeled game-sprite style.\n"
            "Image 2 is an alternating black/white pixel-grid reference. Use it only as a pixel-texture and clean-background guide.\n\n"
        )
    return (
        "Intended use: directional anchor sprite for a top-down 2D game character.\n\n"
        f"{input_images}"
        "Primary request:\n"
        f"Create a new {output_size} {direction.upper()}-facing full-body anchor frame of the same character, {direction_description}, in a neutral idle stance.\n"
        f"Final artwork should behave like one logical {logical_frame_size} in-game frame.\n\n"
        f"{_logical_grid_discipline(logical_frame_size, output_size)}"
        "Subject:\n"
        f"- {subject}.\n\n"
        "Pose and direction:\n"
        f"- The character should be {direction_description} in a game-ready top-down view.\n"
        f"- When a side anchor reference is provided, infer the opposite-side structure from it while still drawing a new {direction.upper()}-facing frame.\n"
        "- Keep both feet visible and stable on the same baseline.\n"
        "- Keep hands neutral.\n"
        "- No magic/effects/action pose.\n"
        f"- Preserve readable direction-specific silhouette: {silhouette_details}.\n"
        "- Do not keep the character facing SOUTH or toward the camera when the requested direction is WEST, EAST, or NORTH.\n\n"
        "Accessory placement:\n"
        "- Keep existing accessories attached naturally to the side/hip/hand where appropriate.\n"
        "- Use the side reference to keep accessory depth and side placement consistent instead of relying only on the front view.\n"
        "- Do not move props to awkward positions just to make them visible.\n"
        "- If a prop is awkward in this view, reduce its visibility rather than relocating it incorrectly.\n\n"
        "Composition:\n"
        "- Single centered character.\n"
        "- Full body visible.\n"
        "- Ample padding on all sides.\n"
        "- Flat chroma background matching source-anchor style.\n"
        "- No shadow, props, other characters, UI, or text.\n\n"
        "Critical constraints:\n"
        "- No dynamic attack effects.\n"
        "- No glow, particles, projectile, aura, or flame.\n"
        "- No weapon/staff/projectile unless it is part of the neutral identity.\n"
        "- This is a neutral anchor for later walk, idle, and attack generation.\n\n"
        "Style:\n"
        "- High-resolution pixelated 2D game sprite.\n"
        "- Crisp readable silhouette.\n"
        "- Consistent with the south-facing anchor."
    )


def _sheet_prompt(
    subject: str,
    asset_kind: str,
    action: str,
    direction: str,
    sheet_size: str,
    cell_size: int,
    attack_name: str,
    effect_color: str,
    projectile_or_effect: str,
    action_description: str = "",
) -> str:
    if asset_kind != "character":
        object_label = "weapon" if asset_kind == "weapon" else "decoration prop" if asset_kind == "decoration" else f"{asset_kind} object"
        if asset_kind == "weapon":
            default_motion = "a restrained weapon-state loop: tiny glint, brief charge, subtle angle or impact-readiness change, then return to the same resting silhouette"
            object_constraints = (
                "- same single weapon in every cell\n"
                "- no wielder, no hand, no arm, no character, no face\n"
                "- full weapon visible in every frame, including tip and handle\n"
                "- no large projectile that hides the weapon silhouette"
            )
        elif asset_kind == "decoration":
            default_motion = "a subtle prop idle loop: tiny glow pulse, gentle floating, small flame flicker, rune shimmer, or mechanism open-close, then return to the starting state"
            object_constraints = (
                "- same single decoration or prop in every cell\n"
                "- no character, no hand, no face, no portrait composition\n"
                "- full object visible in every frame, including base/footprint\n"
                "- no scenery that turns the asset into a room or landscape"
            )
        else:
            default_motion = "a subtle object state loop, then return to the starting state"
            object_constraints = (
                "- same single object in every cell\n"
                "- no character, no hand, no face\n"
                "- full object visible in every frame\n"
                "- no scenery or UI"
            )
        description = action_description or (f"{action} animation" if action not in {"idle", "attack"} else default_motion)
        return (
            "Intended use:\n"
            f"Create a 10-frame 5x2 spritesheet for a single top-down 2D game {object_label}.\n\n"
            "Input images:\n"
            "Image 1 is the approved object anchor. Preserve the exact object identity, material, proportions, palette, silhouette, and high-resolution pixelated game-asset style.\n"
            f"Image 2 is the 5x2 spritesheet layout/style guide. Use it only as a layout guide for ten equal cells across a {sheet_size} sheet.\n\n"
            "Subject:\n"
            f"- {subject}.\n\n"
            "Primary request:\n"
            f"Generate this object-state sequence: {description}. The asset remains centered and keeps the same scale in every frame.\n\n"
            "Canvas and layout:\n"
            f"- {sheet_size} PNG spritesheet\n"
            "- 5 columns by 2 rows\n"
            f"- ten equal {cell_size}x{cell_size} cells\n"
            "- frame order left to right across top row, then left to right across bottom row\n"
            "- one object per cell, centered consistently\n"
            "- simple solid chroma background if a flat background is needed\n\n"
            "Frame sequence:\n"
            "- frame 1: clean resting state\n"
            "- frames 2-4: subtle buildup or first state change\n"
            "- frames 5-6: clearest readable peak state\n"
            "- frames 7-9: return toward resting state\n"
            "- frame 10: matches frame 1 closely for a clean loop\n\n"
            "Object constraints:\n"
            f"{object_constraints}\n"
            "- do not crop the object\n"
            "- do not merge cells or create comic panels\n"
            "- do not recenter the object differently per frame\n\n"
            "Style:\n"
            "- polished high-resolution pixelated 2D game asset\n"
            "- crisp edges, readable silhouette, consistent lighting and palette\n"
            "- no UI, labels, text, watermark, or visible grid lines"
        )
    direction_description = _direction_description(direction)
    if action == "attack":
        return (
            "Intended use:\n"
            "Create a 10-frame 5x2 spritesheet for a top-down 2D game character attack animation.\n\n"
            "Input images:\n"
            f"Image 1 is the identity anchor. Preserve the exact character identity, outfit, proportions, prop placement, silhouette, palette, and {direction.upper()}-facing direction.\n"
            f"Image 2 is the 5x2 spritesheet layout/style guide. Use it only as a layout guide for ten equal cells across a {sheet_size} sheet.\n\n"
            "Subject:\n"
            f"- {subject}.\n\n"
            "Primary request:\n"
            f"Generate a {direction.upper()}-facing {attack_name}. The character faces {direction_description} for every frame. The attack effect is dynamic, but the character remains on a stable foot baseline.\n\n"
            "Canvas and layout:\n"
            f"- {sheet_size} PNG spritesheet\n"
            "- 5 columns by 2 rows\n"
            f"- ten equal {cell_size}x{cell_size} cells\n"
            "- frame order left to right across top row, then left to right across bottom row\n"
            "- character fully visible in each cell, including both feet\n"
            "- consistent character scale, camera, and ground baseline across all frames\n"
            "- simple solid chroma background if a flat background is needed\n\n"
            "Frame sequence:\n"
            "Frame 1: neutral ready stance, feet planted, no large active effect.\n"
            f"Frame 2: begins the attack, body still facing {direction.upper()}.\n"
            "Frame 3: anticipation pose, casting/attack hand rises or shifts.\n"
            f"Frame 4: small {effect_color} spark/charge appears.\n"
            f"Frame 5: compact {projectile_or_effect} forms, bright but not obscuring body or feet.\n"
            f"Frame 6: release frame, attack launches toward {direction_description}.\n"
            "Frame 7: follow-through, effect moves farther with a short trail; character recoils slightly.\n"
            "Frame 8: recoil peak, residual particles fade.\n"
            "Frame 9: settles back toward neutral, only faint embers remain.\n"
            "Frame 10: return to calm ready stance, no large active effect.\n\n"
            "Style:\n"
            "- high-resolution pixel-art-inspired game sprite\n"
            "- clean fantasy/action RPG animation frames\n"
            "- crisp edges\n"
            "- consistent lighting and palette\n"
            "- readable silhouette\n\n"
            "Constraints:\n"
            "- no direction change\n"
            "- no camera angle change\n"
            "- no extra characters\n"
            "- no props beyond existing gear\n"
            "- no scenery, UI, labels, text, watermark, or visible grid lines\n"
            "- do not crop feet, hair, props, arms, or effect\n"
            "- do not merge cells or create comic panels\n"
            "- do not recenter the character differently per frame"
        )
    if action not in {"idle", "attack"}:
        description = action_description or f"{action} animation"
        return (
            "Intended use:\n"
            f"Create a 10-frame 5x2 spritesheet for a top-down 2D game character action animation.\n\n"
            "Input images:\n"
            f"Image 1 is the identity anchor. Preserve the exact character identity, outfit, proportions, prop placement, silhouette, palette, and {direction.upper()}-facing direction.\n"
            f"Image 2 is the 5x2 spritesheet layout/style guide. Use it only as a layout guide for ten equal cells across a {sheet_size} sheet.\n\n"
            "Subject:\n"
            f"- {subject}.\n\n"
            "Primary request:\n"
            f"Generate this {direction.upper()}-facing action: {description}. "
            f"The character faces {direction_description} for every frame. Keep the character on a stable foot baseline.\n\n"
            "Canvas and layout:\n"
            f"- {sheet_size} PNG spritesheet\n"
            "- 5 columns by 2 rows\n"
            f"- ten equal {cell_size}x{cell_size} cells\n"
            "- frame order left to right across top row, then left to right across bottom row\n"
            "- character fully visible in each cell, including feet and key props\n"
            "- consistent character scale, camera, and ground baseline across all frames\n"
            "- simple solid chroma background if a flat background is needed\n\n"
            "Frame sequence:\n"
            "Frame 1: readable starting pose, feet planted, action not yet at peak.\n"
            "Frame 2: action begins; body orientation stays locked to the requested direction.\n"
            "Frame 3: anticipation or wind-up pose.\n"
            "Frame 4: action develops; silhouette remains readable.\n"
            "Frame 5: first peak of the action.\n"
            "Frame 6: strongest action/readability frame.\n"
            "Frame 7: follow-through.\n"
            "Frame 8: recovery from the action.\n"
            "Frame 9: settles back toward ready pose.\n"
            "Frame 10: clean end pose that can transition back to frame 1 or idle.\n\n"
            "Style:\n"
            "- high-resolution pixel-art-inspired game sprite\n"
            "- clean fantasy/action RPG animation frames\n"
            "- crisp edges\n"
            "- consistent lighting and palette\n"
            "- readable silhouette\n\n"
            "Constraints:\n"
            "- no direction change\n"
            "- no camera angle change\n"
            "- no extra characters\n"
            "- no scenery, UI, labels, text, watermark, or visible grid lines\n"
            "- do not crop feet, hair, props, arms, or action effects\n"
            "- do not merge cells or create comic panels\n"
            "- do not recenter the character differently per frame"
        )
    return (
        "Intended use:\n"
        f"{direction.upper()}-facing idle animation spritesheet for a top-down 2D game character.\n\n"
        "Input images:\n"
        f"Image 1 is the approved {direction.upper()}-facing identity anchor. Preserve the exact character identity, proportions, direction, palette, outfit, accessories, and high-resolution pixelated game-sprite style.\n"
        "Image 2 is the 5 columns x 2 rows sheet guide. Use it only as a spritesheet layout and pixel-texture guide.\n\n"
        "Subject:\n"
        f"- {subject}.\n\n"
        "Primary request:\n"
        f"Create a single {sheet_size} spritesheet with 10 frames arranged 5 columns x 2 rows. The character faces {direction_description} in every frame and performs a subtle idle loop.\n\n"
        "Frame sequence:\n"
        "Frame 1: neutral relaxed stance.\n"
        "Frame 2: slight inhale, shoulders/robe rise by a few pixels.\n"
        "Frame 3: hat/hair/cloth settles with tiny sway.\n"
        "Frame 4: tiny facial/cloth movement while body stays grounded.\n"
        "Frame 5: slight exhale, robe lowers.\n"
        "Frame 6: subtle hand/accessory sway.\n"
        "Frame 7: return toward neutral.\n"
        "Frame 8: tiny cloth sway in opposite direction.\n"
        "Frame 9: settle.\n"
        "Frame 10: match frame 1 closely for a clean loop.\n\n"
        "Composition constraints:\n"
        "- one full-body character per frame\n"
        "- feet, robe/hem, head/hat, sleeves, hands, and accessories fully visible\n"
        "- consistent character size\n"
        "- consistent foot baseline\n"
        "- consistent center position\n\n"
        "Critical constraints:\n"
        "- no attack effect\n"
        "- no glow, particles, fireball, projectile, or aura\n"
        "- no walking step\n"
        "- no turning\n"
        "- no added props, UI, labels, frame numbers, shadows, or scene detail\n\n"
        "Style:\n"
        "- high-resolution pixelated 2D game sprite\n"
        "- crisp readable silhouette\n"
        "- opaque flat background"
    )


def create_pixel_concept(
    project_root: Path,
    asset_name: str,
    subject: str,
    asset_kind: str,
    style_id: str,
    image_provider: str,
    content_path: str,
    output_size: str = "1024x1024",
) -> AssetManifest:
    _ensure_image_generation_kind(asset_kind)
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    output = generated / versioned_filename("concept_box_art")
    concept_reference = generated / versioned_filename("concept_reference")
    _create_concept_reference(concept_reference, asset_kind, size=_square_size_pixels(output_size))
    prompt = _box_art_prompt(subject, asset_kind)
    result = _generate_image(prompt, output, image_provider, size=output_size, reference_path=concept_reference)
    rel_output = _rel(project_root, output)
    register_asset_version(project_root, asset_name, rel_output, "concept:box_art", "Concept / box art", asset_id=asset_id, kind=asset_kind)
    manifest = AssetManifest(
        asset_type="texture",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role="concept:box_art", path=rel_output)],
        processing={
            "specialized": {
                "module": "pixel_spritesheet",
                "stage": "concept_box_art",
                "kind": asset_kind,
                "prompt": prompt,
                "model": result.model,
                "provider": image_provider,
                "providerBaseUrl": result.base_url,
                "outputSize": output_size,
                "referenceImage": _rel(project_root, concept_reference),
                "streamEvents": result.stream_events or [],
            }
        },
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def create_pixel_anchor(
    project_root: Path,
    asset_name: str,
    subject: str,
    asset_kind: str,
    direction: str,
    style_id: str,
    image_provider: str,
    content_path: str,
    concept_path: Path | None = None,
    reference_anchor_path: Path | None = None,
    anchor_stage: str = "south",
    dynamic_effect: str = "active effects, glow, particles, projectiles, and charged action pose",
    logical_frame_size: str = "256x256",
    output_size: str = "1024x1024",
    mirror_from: str | None = None,
) -> AssetManifest:
    _ensure_image_generation_kind(asset_kind)
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    output = generated / versioned_filename(f"anchor_{direction}")
    grid_size = _square_size_pixels(output_size)
    anchor_scale = _anchor_output_scale(logical_frame_size, output_size)
    logical_grid_snap: dict[str, int] | None = None
    concept_used_as_reference = False
    generation_reference_paths: list[Path] = []
    if asset_kind == "character" and mirror_from:
        source_direction = mirror_from
        if direction == source_direction:
            raise ValueError("Mirrored anchor direction must differ from source direction")
        source_path = _latest_version_path(project_root, asset_id, f"anchor:{source_direction}")
        if not source_path:
            raise ValueError(f"Generate anchor:{source_direction} before mirrored direction anchor:{direction}")
        _mirror_image(source_path, output)
        logical_grid_snap = _snap_anchor_to_logical_grid(output, logical_frame_size, output_size)
        prompt = f"Mirrored anchor:{source_direction} to create anchor:{direction}."
        result_model = "local:mirror"
        result_base_url = None
        stream_events: list[str] = [f"mirrored anchor:{source_direction} -> anchor:{direction}"]
    elif asset_kind == "character":
        grid_path = generated / versioned_filename(f"anchor_grid_{direction}")
        _create_anchor_grid_reference(grid_path, asset_kind, direction, size=grid_size, logical_frame_size=logical_frame_size)
        if anchor_stage == "neutral":
            identity_anchor = reference_anchor_path or _latest_version_path(project_root, asset_id, "anchor:south")
            if not identity_anchor:
                raise ValueError("Generate anchor:south before neutral anchor reset")
            generation_reference_paths = [identity_anchor, grid_path]
            prompt = _neutral_anchor_prompt(subject, dynamic_effect, logical_frame_size, output_size)
        elif direction == "south":
            if concept_path:
                generation_reference_paths = [concept_path, grid_path]
                concept_used_as_reference = True
            else:
                generation_reference_paths = [grid_path]
            prompt = _south_anchor_prompt(subject, logical_frame_size, output_size, uses_concept=concept_used_as_reference)
        else:
            identity_anchor = reference_anchor_path or _latest_version_path(project_root, asset_id, "anchor:south")
            if not identity_anchor:
                raise ValueError(f"Generate anchor:south before directional anchor:{direction}")
            side_reference_direction = "west" if direction == "east" else None
            if side_reference_direction:
                side_anchor = _latest_version_path(project_root, asset_id, f"anchor:{side_reference_direction}")
                if not side_anchor:
                    raise ValueError(f"Generate anchor:{side_reference_direction} before independent directional anchor:{direction}")
                generation_reference_paths = [identity_anchor, side_anchor, grid_path]
            else:
                generation_reference_paths = [identity_anchor, grid_path]
            prompt = _directional_anchor_prompt(subject, direction, logical_frame_size, output_size, side_reference_direction=side_reference_direction)
        result = _generate_image(prompt, output, image_provider, size=output_size, reference_paths=generation_reference_paths)
        logical_grid_snap = _snap_anchor_to_logical_grid(output, logical_frame_size, output_size)
        result_model = result.model
        result_base_url = result.base_url
        stream_events = result.stream_events or []
    else:
        grid_path = generated / versioned_filename(f"anchor_grid_{direction}")
        _create_anchor_grid_reference(grid_path, asset_kind, direction, size=grid_size, logical_frame_size=logical_frame_size)
        if concept_path:
            generation_reference_paths = [concept_path, grid_path]
            concept_used_as_reference = True
        else:
            generation_reference_paths = [grid_path]
        prompt = _object_anchor_prompt(subject, asset_kind, logical_frame_size, output_size, uses_concept=concept_used_as_reference)
        result = _generate_image(prompt, output, image_provider, size=output_size, reference_paths=generation_reference_paths)
        logical_grid_snap = _snap_anchor_to_logical_grid(output, logical_frame_size, output_size)
        result_model = result.model
        result_base_url = result.base_url
        stream_events = result.stream_events or []
    rel_output = _rel(project_root, output)
    register_asset_version(project_root, asset_name, rel_output, f"anchor:{direction}", f"anchor {direction}", asset_id=asset_id, kind=asset_kind)
    processing: dict[str, Any] = {
        "module": "pixel_spritesheet",
        "stage": anchor_stage,
        "kind": asset_kind,
        "direction": direction,
        "prompt": prompt,
        "model": result_model,
        "provider": image_provider,
        "providerBaseUrl": result_base_url,
        "streamEvents": stream_events,
        "logicalFrameSize": logical_frame_size,
        "outputSize": output_size,
        "anchorScale": anchor_scale,
    }
    if logical_grid_snap:
        processing["logicalGridSnap"] = logical_grid_snap
    if "grid_path" in locals():
        processing["anchorGridReference"] = _rel(project_root, grid_path)
    if generation_reference_paths:
        processing["referenceImages"] = [_rel(project_root, path) for path in generation_reference_paths]
    if concept_path:
        processing["conceptPath"] = _rel(project_root, concept_path)
        processing["conceptUsedAsImageReference"] = concept_used_as_reference
    if reference_anchor_path:
        processing["referenceAnchorPath"] = _rel(project_root, reference_anchor_path)
    if anchor_stage == "neutral":
        processing["removedDynamicEffect"] = dynamic_effect
    if asset_kind == "character" and mirror_from:
        processing["mirroredFrom"] = mirror_from
    manifest = AssetManifest(
        asset_type="texture",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role=f"anchor:{direction}", path=rel_output)],
        processing={"specialized": processing},
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def create_animation_sheet(
    project_root: Path,
    asset_name: str,
    subject: str,
    asset_kind: str,
    action: str,
    direction: str,
    style_id: str,
    image_provider: str,
    content_path: str,
    columns: int = 5,
    rows: int = 2,
    cell_size: int = 256,
    reference_path: Path | None = None,
    attack_name: str = "magic projectile attack",
    effect_color: str = "violet",
    projectile_or_effect: str = "projectile or impact effect",
    action_description: str = "",
    mirror_from: str | None = None,
) -> AssetManifest:
    _ensure_image_generation_kind(asset_kind)
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    output = generated / versioned_filename(f"{action}_{direction}_sheet")
    sheet_size = f"{columns * cell_size}x{rows * cell_size}"
    if asset_kind == "character" and mirror_from:
        source_direction = mirror_from
        if direction == source_direction:
            raise ValueError("Mirrored sheet direction must differ from source direction")
        source_path = _latest_version_path(project_root, asset_id, f"sheet:{action}:{source_direction}")
        if not source_path:
            raise ValueError(f"Generate sheet:{action}:{source_direction} before mirrored direction sheet:{action}:{direction}")
        _mirror_sheet_cells(source_path, output, columns, rows, cell_size, cell_size)
        prompt = f"Mirrored sheet:{action}:{source_direction} to create sheet:{action}:{direction}."
        result_model = "local:mirror"
        result_base_url = None
        stream_events: list[str] = [f"mirrored sheet:{action}:{source_direction} -> sheet:{action}:{direction}"]
    else:
        if not reference_path:
            anchor_role = f"anchor:{direction if asset_kind == 'character' else 'single'}"
            reference_path = _latest_version_path(project_root, asset_id, anchor_role)
        if not reference_path:
            raise ValueError(f"Generate anchor:{direction if asset_kind == 'character' else 'single'} before sheet:{action}:{direction}")
        guide_path = generated / versioned_filename(f"sheet_guide_{action}_{direction}")
        _create_sheet_guide_reference(guide_path, columns, rows, cell_size)
        prompt = _sheet_prompt(
            subject,
            asset_kind,
            action,
            direction,
            sheet_size,
            cell_size,
            attack_name,
            effect_color,
            projectile_or_effect,
            action_description,
        )
        result = _generate_image(prompt, output, image_provider, size=sheet_size, reference_paths=[reference_path, guide_path])
        result_model = result.model
        result_base_url = result.base_url
        stream_events = result.stream_events or []
    rel_output = _rel(project_root, output)
    register_asset_version(project_root, asset_name, rel_output, f"sheet:{action}:{direction}", f"{action} {direction}", asset_id=asset_id, kind=asset_kind)
    frames = [
        SpriteFrame(name=f"{action}_{direction}_{index:03d}", x=(index % columns) * cell_size, y=(index // columns) * cell_size, width=cell_size, height=cell_size)
        for index in range(columns * rows)
    ]
    processing: dict[str, Any] = {
        "module": "pixel_spritesheet",
        "kind": asset_kind,
        "action": action,
        "direction": direction,
        "prompt": prompt,
        "model": result_model,
        "provider": image_provider,
        "providerBaseUrl": result_base_url,
        "streamEvents": stream_events,
        "columns": columns,
        "rows": rows,
        "cellSize": cell_size,
        "sheetSize": sheet_size,
    }
    if "guide_path" in locals():
        processing["sheetGuideReference"] = _rel(project_root, guide_path)
    if "guide_path" in locals():
        processing["referenceImages"] = [_rel(project_root, reference_path), _rel(project_root, guide_path)]
    if reference_path:
        processing["anchorReference"] = _rel(project_root, reference_path)
    if asset_kind == "character" and mirror_from:
        processing["mirroredFrom"] = mirror_from
    manifest = AssetManifest(
        asset_type="spritesheet",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role=f"sheet:{action}:{direction}", path=rel_output)],
        frames=frames,
        animations=[AnimationSequence(name=f"{action}_{direction}", frame_names=[frame.name for frame in frames], fps=12.0, loop=action != "attack")],
        processing={"specialized": processing},
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D", "PaperSprite", "PaperFlipbook"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def import_animation_sheet(
    project_root: Path,
    asset_name: str,
    source_path: Path,
    asset_kind: str,
    action: str,
    direction: str,
    style_id: str,
    content_path: str,
    columns: int = 5,
    rows: int = 2,
    cell_size: int = 256,
) -> AssetManifest:
    _ensure_image_generation_kind(asset_kind)
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"Spritesheet image does not exist: {source_path}")
    Image, _, _ = _require_pillow()
    try:
        with Image.open(source_path) as image:
            image.verify()
    except Exception as exc:
        raise ValueError(f"Spritesheet image is not a readable image: {source_path}") from exc
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    suffix = source_path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    action_id = asset_id_from_name(action or "idle")
    output = generated / versioned_filename(f"{action_id}_{direction}_sheet_import", suffix=suffix)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, output)
    rel_output = _rel(project_root, output)
    register_asset_version(project_root, asset_name, rel_output, f"sheet:{action_id}:{direction}", f"{action_id} {direction} imported sheet", asset_id=asset_id, kind=asset_kind)
    frames = [
        SpriteFrame(name=f"{action_id}_{direction}_{index:03d}", x=(index % columns) * cell_size, y=(index // columns) * cell_size, width=cell_size, height=cell_size)
        for index in range(columns * rows)
    ]
    manifest = AssetManifest(
        asset_type="spritesheet",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role=f"sheet:{action_id}:{direction}", path=rel_output)],
        frames=frames,
        animations=[AnimationSequence(name=f"{action_id}_{direction}", frame_names=[frame.name for frame in frames], fps=12.0, loop=action_id != "attack")],
        processing={
            "specialized": {
                "module": "pixel_spritesheet",
                "source": "import",
                "sourcePath": str(source_path),
                "kind": asset_kind,
                "action": action_id,
                "direction": direction,
                "columns": columns,
                "rows": rows,
                "cellSize": cell_size,
            }
        },
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D", "PaperSprite", "PaperFlipbook"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def normalize_spritesheet(
    project_root: Path,
    sheet_path: Path,
    asset_name: str,
    action: str,
    columns: int,
    rows: int,
    cell_width: int,
    cell_height: int,
    style_id: str,
    content_path: str,
    chroma_key: tuple[int, int, int] | None = (255, 0, 255),
    direction: str | None = None,
    pixel_restore_mode: PixelRestoreMode = "safe",
    source_cell_width: int | None = None,
    source_cell_height: int | None = None,
    progress: Callable[[str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> AssetManifest:
    Image, _, _ = _require_pillow()
    source_cell_width = source_cell_width or cell_width
    source_cell_height = source_cell_height or cell_height
    if source_cell_width <= 0 or source_cell_height <= 0 or cell_width <= 0 or cell_height <= 0:
        raise ValueError("Cell size must be greater than zero")
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    output = generated / versioned_filename(f"runtime_{action}_sheet")
    gif_output = generated / f"{output.stem}.gif"
    contact_output = generated / f"{output.stem}_contact.png"
    restored_frames_dir: Path | None = None
    with Image.open(sheet_path) as image, tempfile.TemporaryDirectory(prefix="uim_normalize_frames_") as temp_dir:
        rgba = image.convert("RGBA")
        requested_columns = columns
        requested_rows = rows
        requested_source_cell_width = source_cell_width
        requested_source_cell_height = source_cell_height
        if columns <= 0 or rows <= 0:
            if rgba.width % source_cell_width == 0 and rgba.height % source_cell_height == 0:
                columns = max(1, rgba.width // source_cell_width)
                rows = max(1, rgba.height // source_cell_height)
            elif rgba.width % cell_width == 0 and rgba.height % cell_height == 0:
                source_cell_width = cell_width
                source_cell_height = cell_height
                columns = max(1, rgba.width // cell_width)
                rows = max(1, rgba.height // cell_height)
            else:
                raise ValueError(
                    "Could not infer spritesheet grid from source image size "
                    f"{rgba.width}x{rgba.height}; source cell {source_cell_width}x{source_cell_height}; "
                    f"target cell {cell_width}x{cell_height}"
                )
        if rgba.width % source_cell_width == 0 and rgba.width // source_cell_width > columns:
            columns = rgba.width // source_cell_width
        if rgba.height % source_cell_height == 0 and rgba.height // source_cell_height > rows:
            rows = rgba.height // source_cell_height
        expected_size = (columns * source_cell_width, rows * source_cell_height)
        if rgba.size[0] < expected_size[0] or rgba.size[1] < expected_size[1]:
            if rgba.width % source_cell_width == 0 and rgba.height % source_cell_height == 0:
                columns = max(1, rgba.width // source_cell_width)
                rows = max(1, rgba.height // source_cell_height)
            elif rgba.width % cell_width == 0 and rgba.height % cell_height == 0:
                source_cell_width = cell_width
                source_cell_height = cell_height
                columns = max(1, rgba.width // cell_width)
                rows = max(1, rgba.height // cell_height)
            elif columns > 0 and rows > 0 and rgba.width % columns == 0 and rgba.height % rows == 0:
                source_cell_width = max(1, rgba.width // columns)
                source_cell_height = max(1, rgba.height // rows)
            else:
                raise ValueError(f"Spritesheet is smaller than expected grid: expected at least {expected_size[0]}x{expected_size[1]}, got {rgba.width}x{rgba.height}")
            expected_size = (columns * source_cell_width, rows * source_cell_height)
        if rgba.size != expected_size:
            rgba = rgba.crop((0, 0, expected_size[0], expected_size[1]))
        frames = []
        bounds_data = []
        temp_root = Path(temp_dir)
        if pixel_restore_mode != "none":
            restored_frames_dir = generated / versioned_filename(f"{action}_{direction or 'single'}_{pixel_restore_mode}_unfake_frames", suffix="")
            restored_frames_dir.mkdir(parents=True, exist_ok=True)
        frame_count = columns * rows
        if progress:
            progress(
                f"pixel.normalize.start frames={frame_count} source_cell={source_cell_width}x{source_cell_height} "
                f"target_cell={cell_width}x{cell_height} restore={pixel_restore_mode}"
            )
        for row in range(rows):
            for column in range(columns):
                index = row * columns + column
                if is_cancelled and is_cancelled():
                    raise RuntimeError("Pixel normalize cancelled by user")
                if progress:
                    progress(f"pixel.normalize.frame start index={index + 1}/{frame_count}")
                cell = rgba.crop((column * source_cell_width, row * source_cell_height, (column + 1) * source_cell_width, (row + 1) * source_cell_height))
                if chroma_key:
                    datas = []
                    for pixel in cell.getdata():
                        r, g, b, a = pixel
                        datas.append((r, g, b, 0) if (r, g, b) == chroma_key else (r, g, b, a))
                    cell.putdata(datas)
                if pixel_restore_mode != "none":
                    cell_input = temp_root / f"frame_{index:04d}_input.png"
                    cell_output = restored_frames_dir / f"frame_{index:04d}_{pixel_restore_mode}.png"
                    cell.save(cell_input)
                    run_unfake_restore(cell_input, cell_output, pixel_restore_mode)
                    if is_cancelled and is_cancelled():
                        raise RuntimeError("Pixel normalize cancelled by user")
                    with Image.open(cell_output) as restored_cell:
                        cell = restored_cell.convert("RGBA")
                if cell.size != (cell_width, cell_height):
                    cell = cell.resize((cell_width, cell_height), Image.Resampling.NEAREST)
                box = cell.getchannel("A").getbbox()
                if box:
                    left, top, right, bottom = box
                    bounds_data.append({"left": left, "top": top, "right": right, "bottom": bottom, "height": bottom - top})
                frames.append(cell)
                if progress:
                    visible = sum(1 for value in cell.getchannel("A").getdata() if value > 0)
                    progress(f"pixel.normalize.frame done index={index + 1}/{frame_count} visible={visible}")
        target_height = max((item["height"] for item in bounds_data), default=cell_height)
        output_frames = []
        sprite_frames = []
        for index, cell in enumerate(frames):
            output_frames.append(cell)
            sprite_frames.append(
                SpriteFrame(
                    name=f"{action}_{index:03d}",
                    x=(index % columns) * cell_width,
                    y=(index // columns) * cell_height,
                    width=cell_width,
                    height=cell_height,
                    pivot=(0.5, 1.0),
                    trim_rect=None,
                )
            )
        sheet = Image.new("RGBA", (columns * cell_width, rows * cell_height), (0, 0, 0, 0))
        for index, frame in enumerate(output_frames):
            sheet.paste(frame, ((index % columns) * cell_width, (index // columns) * cell_height), frame)
        output.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(output)
        sheet.save(contact_output)
        qa_summary = frame_qa_summary(sheet, columns, rows, cell_width, cell_height)
        qa_output = generated / f"{output.stem}_qa.json"
        write_qa_report(qa_output, qa_summary)
        if output_frames:
            preview_frames = []
            for frame in output_frames:
                preview = _preview_frame_background(Image, cell_width, cell_height)
                preview.alpha_composite(frame)
                preview_frames.append(preview.convert("P", palette=Image.Palette.ADAPTIVE))
            preview_frames[0].save(gif_output, save_all=True, append_images=preview_frames[1:], duration=90, loop=0, disposal=2, optimize=False)
        if progress:
            progress(f"pixel.normalize.done frames={len(output_frames)} output={_rel(project_root, output)}")
    rel_output = _rel(project_root, output)
    role_scope = f"{action}:{direction}" if direction else action
    register_asset_version(project_root, asset_name, rel_output, f"runtime:{role_scope}", f"runtime {role_scope}", asset_id=asset_id)
    register_asset_version(project_root, asset_name, _rel(project_root, gif_output), f"preview:{role_scope}", f"preview {role_scope}", asset_id=asset_id)
    manifest = AssetManifest(
        asset_type="spritesheet",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role=f"runtime:{role_scope}", path=rel_output), AssetFile(role=f"preview:{role_scope}", path=_rel(project_root, gif_output))],
        frames=sprite_frames,
        animations=[AnimationSequence(name=role_scope.replace(":", "_"), frame_names=[frame.name for frame in sprite_frames], fps=12.0, loop=action != "attack")],
        processing={
            "normalization": {
                "pipelineVersion": "pixel-sheet-v2",
                "apiContractVersion": API_CONTRACT_VERSION,
                "sourceCellWidth": source_cell_width,
                "sourceCellHeight": source_cell_height,
                "requestedSourceCellWidth": requested_source_cell_width,
                "requestedSourceCellHeight": requested_source_cell_height,
                "cellWidth": cell_width,
                "cellHeight": cell_height,
                "columns": columns,
                "rows": rows,
                "requestedColumns": requested_columns,
                "requestedRows": requested_rows,
                "direction": direction,
                "targetVisibleHeight": target_height,
                "layoutMode": "preserve_cell_origin",
                "contactSheet": _rel(project_root, contact_output),
                "qaReport": _rel(project_root, qa_output),
                "qaSummary": {
                    "emptyFrameCount": qa_summary["emptyFrameCount"],
                    "visiblePixelMin": qa_summary["visiblePixelMin"],
                    "visiblePixelMax": qa_summary["visiblePixelMax"],
                    "bboxJitter": qa_summary["bboxJitter"],
                },
                "pixelRestoreMode": pixel_restore_mode,
            }
        },
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D", "PaperSprite", "PaperFlipbook"]}},
    )
    if restored_frames_dir:
        manifest.processing["normalization"]["restoredFramesDir"] = _rel(project_root, restored_frames_dir)
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def create_spritesheet_cutout(
    project_root: Path,
    sheet_path: Path,
    asset_name: str,
    action: str,
    direction: str,
    columns: int,
    rows: int,
    cell_width: int,
    cell_height: int,
    style_id: str,
    content_path: str,
    model_name: str = "isnet-general-use",
    progress: Any | None = None,
    *,
    mask_mode: PixelMaskMode = "hybrid",
    decontaminate_edges: bool = True,
    debug_artifacts: bool = False,
) -> AssetManifest:
    Image, _, _ = _require_pillow()
    if not sheet_path.exists() or not sheet_path.is_file():
        raise ValueError(f"Spritesheet file does not exist: {sheet_path}")
    if mask_mode not in {"hybrid", "rembg", "classic"}:
        raise ValueError(f"Unknown pixel mask mode: {mask_mode}")
    adapter = RembgAdapter(model_name) if mask_mode in {"hybrid", "rembg"} else None
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    action_id = asset_id_from_name(action or "action")
    output = generated / versioned_filename(f"{action_id}_{direction}_cutout_sheet")
    debug_dir = generated / f"{output.stem}_debug" if debug_artifacts else None
    frame_reports: list[dict[str, Any]] = []
    with Image.open(sheet_path) as image, tempfile.TemporaryDirectory(prefix="uim_cutout_frames_") as temp_dir:
        rgba = image.convert("RGBA")
        requested_columns = columns
        requested_rows = rows
        if cell_width <= 0 or cell_height <= 0:
            raise ValueError("Cell size must be greater than zero")
        if rgba.width % cell_width == 0 and rgba.width // cell_width > columns:
            columns = rgba.width // cell_width
        if rgba.height % cell_height == 0 and rgba.height // cell_height > rows:
            rows = rgba.height // cell_height
        expected_size = (columns * cell_width, rows * cell_height)
        if rgba.size[0] < expected_size[0] or rgba.size[1] < expected_size[1]:
            raise ValueError(f"Spritesheet is smaller than expected grid: expected at least {expected_size[0]}x{expected_size[1]}, got {rgba.width}x{rgba.height}")
        sheet = Image.new("RGBA", expected_size, (0, 0, 0, 0))
        frame_count = columns * rows
        temp_root = Path(temp_dir)
        if progress:
            progress(f"pixel.cutout.start frames={frame_count} mode={mask_mode} model={model_name}")
        for index in range(frame_count):
            row = index // columns
            column = index % columns
            x = column * cell_width
            y = row * cell_height
            cell = rgba.crop((x, y, x + cell_width, y + cell_height))
            rembg_alpha = None
            if progress:
                progress(f"pixel.cutout.frame start index={index + 1}/{frame_count}")
            if adapter is not None:
                input_frame = temp_root / f"frame_{index:04d}_input.png"
                output_frame = temp_root / f"frame_{index:04d}_rembg.png"
                cell.save(input_frame)
                adapter.remove_background(input_frame, output_frame)
                with Image.open(output_frame) as cutout_image:
                    rembg_cutout = cutout_image.convert("RGBA")
                    if rembg_cutout.size == (cell_width, cell_height):
                        rembg_alpha = rembg_cutout.getchannel("A")
                    else:
                        alpha_canvas = Image.new("L", (cell_width, cell_height), 0)
                        alpha_crop = rembg_cutout.getchannel("A").crop((0, 0, min(cell_width, rembg_cutout.width), min(cell_height, rembg_cutout.height)))
                        alpha_canvas.paste(alpha_crop, (0, 0))
                        rembg_alpha = alpha_canvas
                        if progress:
                            progress(f"rembg.cutout.frame size-normalized index={index + 1}/{frame_count} size={rembg_cutout.width}x{rembg_cutout.height}->{cell_width}x{cell_height}")
            cutout, report = apply_pixel_mask(
                cell,
                rembg_alpha=rembg_alpha,
                mode=mask_mode,
                decontaminate_edges=decontaminate_edges,
                debug_dir=debug_dir,
                debug_prefix=f"frame_{index:04d}",
            )
            frame_reports.append({"index": index, **report})
            sheet.paste(cutout, (x, y), cutout)
            if progress:
                progress(f"pixel.cutout.frame done index={index + 1}/{frame_count} visible={report.get('visiblePixels', 0)}")
        output.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(output)
        if progress:
            progress(f"pixel.cutout.done frames={frame_count}")
    rel_output = _rel(project_root, output)
    role = f"cutout:{action_id}:{direction}"
    register_asset_version(project_root, asset_name, rel_output, role, f"{action_id} {direction} cutout", asset_id=asset_id)
    frames = [
        SpriteFrame(
            name=f"{action_id}_{direction}_{index:03d}",
            x=(index % columns) * cell_width,
            y=(index // columns) * cell_height,
            width=cell_width,
            height=cell_height,
            pivot=(0.5, 1.0),
        )
        for index in range(frame_count)
    ]
    manifest = AssetManifest(
        asset_type="spritesheet",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role=role, path=rel_output)],
        frames=frames,
        animations=[AnimationSequence(name=f"{action_id}_{direction}", frame_names=[frame.name for frame in frames], fps=12.0, loop=action_id != "attack")],
        processing={
            "cutout": {
                "pipelineVersion": "pixel-sheet-v2",
                "apiContractVersion": API_CONTRACT_VERSION,
                "sourceSheet": _rel(project_root, sheet_path),
                "model": model_name,
                "columns": columns,
                "rows": rows,
                "requestedColumns": requested_columns,
                "requestedRows": requested_rows,
                "cellWidth": cell_width,
                "cellHeight": cell_height,
                "mode": f"per-frame-{mask_mode}-preserve-cell-origin",
                "maskMode": mask_mode,
                "decontaminateEdges": decontaminate_edges,
                "debugArtifacts": _rel(project_root, debug_dir) if debug_dir else None,
                "frames": frame_reports,
            }
        },
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D", "PaperSprite", "PaperFlipbook"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def create_spritesheet_from_video(
    project_root: Path,
    asset_name: str,
    video_path: Path,
    action: str,
    direction: str,
    columns: int,
    rows: int,
    cell_size: int,
    style_id: str,
    content_path: str,
    frame_times: list[float] | None = None,
) -> AssetManifest:
    Image, _, _ = _require_pillow()
    if not video_path.exists() or not video_path.is_file():
        raise ValueError(f"Video file does not exist: {video_path}")
    ffmpeg, ffmpeg_source = _video_ffmpeg_executable()

    action_id = asset_id_from_name(action or "action")
    selected_times = [max(0.0, float(time)) for time in (frame_times or [])]
    frame_count = len(selected_times) if selected_times else columns * rows
    sheet_rows = max(1, math.ceil(frame_count / max(1, columns)))
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    output = generated / versioned_filename(f"{action_id}_{direction}_video_sheet")
    with tempfile.TemporaryDirectory(prefix="uim_video_frames_") as temp_dir:
        if selected_times:
            selected_frames = _extract_video_frames_at_times(ffmpeg, video_path, selected_times, Path(temp_dir))
        else:
            frame_pattern = Path(temp_dir) / "frame_%04d.png"
            completed = subprocess.run(
                [ffmpeg, "-y", "-i", str(video_path), "-vf", "fps=8", str(frame_pattern)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"ffmpeg frame extraction failed: {detail[:800]}")
            extracted_frames = sorted(Path(temp_dir).glob("frame_*.png"))
            if not extracted_frames:
                raise RuntimeError("ffmpeg did not extract any frames from the video")
            if len(extracted_frames) >= frame_count:
                selected_frames = [
                    extracted_frames[round(index * (len(extracted_frames) - 1) / max(1, frame_count - 1))]
                    for index in range(frame_count)
                ]
            else:
                selected_frames = [extracted_frames[min(index, len(extracted_frames) - 1)] for index in range(frame_count)]

        sheet = Image.new("RGBA", (columns * cell_size, sheet_rows * cell_size), (0, 0, 0, 0))
        for index, frame_path in enumerate(selected_frames):
            with Image.open(frame_path) as frame_image:
                frame = frame_image.convert("RGBA")
                frame.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
                cell = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 0))
                paste_x = (cell_size - frame.width) // 2
                paste_y = cell_size - frame.height
                cell.paste(frame, (paste_x, paste_y), frame)
                sheet.paste(cell, ((index % columns) * cell_size, (index // columns) * cell_size), cell)
        output.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(output)

    rel_output = _rel(project_root, output)
    try:
        rel_video_path = _rel(project_root, video_path)
    except ValueError:
        rel_video_path = str(video_path)
    register_asset_version(project_root, asset_name, rel_output, f"sheet:{action_id}:{direction}", f"{action_id} {direction} video sheet", asset_id=asset_id)
    frames = [
        SpriteFrame(
            name=f"{action_id}_{direction}_{index:03d}",
            x=(index % columns) * cell_size,
            y=(index // columns) * cell_size,
            width=cell_size,
            height=cell_size,
            pivot=(0.5, 1.0),
        )
        for index in range(frame_count)
    ]
    manifest = AssetManifest(
        asset_type="spritesheet",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role=f"sheet:{action_id}:{direction}", path=rel_output)],
        frames=frames,
        animations=[AnimationSequence(name=f"{action_id}_{direction}", frame_names=[frame.name for frame in frames], fps=12.0, loop=action_id != "attack")],
        processing={
            "videoSpritesheet": {
                "videoPath": rel_video_path,
                "columns": columns,
                "rows": sheet_rows,
                "requestedRows": rows,
                "cellSize": cell_size,
                "frameCount": frame_count,
                "selectedFrameTimes": selected_times,
                "frameOrderMode": "user_queue" if selected_times else "auto_even",
                "extractor": ffmpeg_source,
            }
        },
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D", "PaperSprite", "PaperFlipbook"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def _extract_video_frames_at_times(ffmpeg: str, video_path: Path, selected_times: list[float], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_frames: list[Path] = []

    def extract_one(timestamp: float, frame_path: Path) -> tuple[bool, str]:
        attempts = [
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}", "-i", str(video_path), "-frames:v", "1", str(frame_path)],
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path), "-ss", f"{timestamp:.3f}", "-frames:v", "1", str(frame_path)],
        ]
        if timestamp > 0:
            for offset in (0.04, 0.1, 0.25, 0.5):
                fallback_time = max(0.0, timestamp - offset)
                attempts.append([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{fallback_time:.3f}", "-i", str(video_path), "-frames:v", "1", str(frame_path)])
        errors: list[str] = []
        for command in attempts:
            frame_path.unlink(missing_ok=True)
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0:
                return True, ""
            detail = (completed.stderr or completed.stdout or "").strip()
            if detail:
                errors.append(detail)
        return False, " | ".join(errors[-2:])

    for index, timestamp in enumerate(selected_times):
        frame_path = output_dir / f"selected_{index:04d}.png"
        ok, detail = extract_one(max(0.0, float(timestamp)), frame_path)
        if not ok:
            raise RuntimeError(f"ffmpeg selected-frame extraction failed at {timestamp:.3f}s: {detail[:800] or 'no frame was decoded'}")
        selected_frames.append(frame_path)
    return selected_frames


def _frame_to_cell(frame_path: Path, cell_size: int):
    Image, _, _ = _require_pillow()
    with Image.open(frame_path) as frame_image:
        frame = frame_image.convert("RGBA")
        frame.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
        cell = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 0))
        paste_x = (cell_size - frame.width) // 2
        paste_y = cell_size - frame.height
        cell.paste(frame, (paste_x, paste_y), frame)
        return cell


def _compose_video_frame_sheet(frame_paths: list[Path], columns: int, rows: int, cell_size: int):
    Image, _, _ = _require_pillow()
    sheet = Image.new("RGBA", (columns * cell_size, rows * cell_size), (0, 0, 0, 0))
    max_frames = columns * rows
    for index, frame_path in enumerate(frame_paths[:max_frames]):
        cell = _frame_to_cell(frame_path, cell_size)
        sheet.paste(cell, ((index % columns) * cell_size, (index // columns) * cell_size), cell)
    return sheet


def extract_video_frame_thumbnails(video_path: Path, frame_times: list[float], thumbnail_size: int = 144) -> dict[str, Any]:
    Image, _, _ = _require_pillow()
    if not video_path.exists() or not video_path.is_file():
        raise ValueError(f"Video file does not exist: {video_path}")
    selected_times = [max(0.0, float(time)) for time in frame_times]
    if not selected_times:
        return {"extractor": "", "frames": []}
    size = max(32, min(512, int(thumbnail_size or 144)))
    ffmpeg, ffmpeg_source = _video_ffmpeg_executable()
    frames: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="uim_video_thumbnails_") as temp_dir:
        extracted_frames = _extract_video_frames_at_times(ffmpeg, video_path, selected_times, Path(temp_dir))
        for index, frame_path in enumerate(extracted_frames):
            with Image.open(frame_path) as frame_image:
                frame = frame_image.convert("RGBA")
                frame.thumbnail((size, size), Image.Resampling.LANCZOS)
                thumbnail = Image.new("RGBA", (size, size), (255, 255, 255, 255))
                thumbnail.alpha_composite(frame, ((size - frame.width) // 2, (size - frame.height) // 2))
                buffer = BytesIO()
                thumbnail.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            frames.append({"time": selected_times[index], "thumbnail": f"data:image/png;base64,{encoded}"})
    return {"extractor": ffmpeg_source, "frames": frames}


def create_video_debug_export(
    project_root: Path,
    asset_name: str,
    video_path: Path,
    action: str,
    direction: str,
    export_type: str,
    columns: int,
    rows: int,
    cell_size: int,
    style_id: str,
    content_path: str,
    frame_times: list[float],
) -> AssetManifest:
    Image, _, _ = _require_pillow()
    if export_type not in {"png_sequence", "gif", "sheet"}:
        raise ValueError(f"Unknown video debug export type: {export_type}")
    if not video_path.exists() or not video_path.is_file():
        raise ValueError(f"Video file does not exist: {video_path}")
    selected_times = [max(0.0, float(time)) for time in frame_times]
    if not selected_times:
        raise ValueError("Video debug export requires at least one selected frame time")
    ffmpeg, ffmpeg_source = _video_ffmpeg_executable()
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    action_id = asset_id_from_name(action or "action")
    with tempfile.TemporaryDirectory(prefix="uim_video_debug_frames_") as temp_dir:
        extracted_frames = _extract_video_frames_at_times(ffmpeg, video_path, selected_times, Path(temp_dir))
        files: list[AssetFile] = []
        processing: dict[str, Any] = {
            "videoPath": _rel(project_root, video_path) if video_path.resolve().is_relative_to(project_root.resolve()) else str(video_path),
            "action": action_id,
            "direction": direction,
            "exportType": export_type,
            "selectedFrameTimes": selected_times,
            "frameOrderMode": "user_queue",
            "extractor": ffmpeg_source,
            "frameCount": len(selected_times),
            "cellSize": cell_size,
            "columns": columns,
            "rows": rows,
        }
        if export_type == "png_sequence":
            sequence_dir = generated / versioned_filename(f"{action_id}_{direction}_video_frames", suffix="")
            sequence_dir.mkdir(parents=True, exist_ok=True)
            frame_files: list[str] = []
            for index, frame_path in enumerate(extracted_frames):
                output_frame = sequence_dir / f"frame_{index:03d}_{selected_times[index]:.3f}s.png"
                with Image.open(frame_path) as image:
                    image.convert("RGBA").save(output_frame)
                rel_frame = _rel(project_root, output_frame)
                frame_files.append(rel_frame)
                files.append(AssetFile(role=f"debug:video_frame:{action_id}:{direction}:{index:03d}", path=rel_frame))
            preview_output = generated / versioned_filename(f"{action_id}_{direction}_video_frames_contact")
            preview_sheet = _compose_video_frame_sheet(extracted_frames, columns, max(1, (len(extracted_frames) + columns - 1) // columns), cell_size)
            preview_sheet.save(preview_output)
            rel_preview = _rel(project_root, preview_output)
            files.insert(0, AssetFile(role=f"debug:video_png_sequence:{action_id}:{direction}", path=rel_preview))
            processing["outputDirectory"] = _rel(project_root, sequence_dir)
            processing["frameFiles"] = frame_files
            output_for_index = rel_preview
            label = f"{action_id} {direction} video frame sequence"
        elif export_type == "gif":
            output = generated / versioned_filename(f"{action_id}_{direction}_video_debug", suffix=".gif")
            gif_frames = []
            for frame_path in extracted_frames:
                preview = _preview_frame_background(Image, cell_size, cell_size)
                preview.alpha_composite(_frame_to_cell(frame_path, cell_size))
                gif_frames.append(preview.convert("P", palette=Image.Palette.ADAPTIVE))
            gif_frames[0].save(output, save_all=True, append_images=gif_frames[1:], duration=90, loop=0, disposal=2, optimize=False)
            rel_output = _rel(project_root, output)
            files.append(AssetFile(role=f"debug:video_gif:{action_id}:{direction}", path=rel_output, mime_type="image/gif"))
            output_for_index = rel_output
            label = f"{action_id} {direction} video debug gif"
        else:
            output = generated / versioned_filename(f"{action_id}_{direction}_video_debug_sheet")
            sheet = _compose_video_frame_sheet(extracted_frames, columns, rows, cell_size)
            sheet.save(output)
            rel_output = _rel(project_root, output)
            files.append(AssetFile(role=f"debug:video_sheet:{action_id}:{direction}", path=rel_output))
            output_for_index = rel_output
            label = f"{action_id} {direction} video debug sheet"

    register_asset_version(project_root, asset_name, output_for_index, files[0].role, label, asset_id=asset_id)
    manifest = AssetManifest(
        asset_type="texture",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=files,
        processing={"videoDebugExport": processing},
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def _create_tilemap_manifest(
    project_root: Path,
    asset_name: str,
    tileset_path: Path,
    tile_size: int,
    style_id: str,
    content_path: str,
    *,
    standard: str,
    tile_ids: list[str],
    columns: int,
    file_role: str,
    label: str,
    extra_processing: dict[str, Any] | None = None,
) -> AssetManifest:
    asset_id, _, manifests = _asset_dirs(project_root, asset_name)
    if not tileset_path.exists() or not tileset_path.is_file():
        raise ValueError(f"Tileset image does not exist: {tileset_path}")
    rel_tileset = _rel(project_root, tileset_path)
    frames = [
        SpriteFrame(name=tile_id, x=(index % columns) * tile_size, y=(index // columns) * tile_size, width=tile_size, height=tile_size, pivot=(0.5, 0.5))
        for index, tile_id in enumerate(tile_ids)
    ]
    tilemap_processing: dict[str, Any] = {
        "standard": standard,
        "tileSize": tile_size,
        "tiles": tile_ids,
        "layout": {"columns": columns, "order": "row-major"},
    }
    if extra_processing:
        tilemap_processing.update(extra_processing)
    manifest = AssetManifest(
        asset_type="spritesheet",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role=file_role, path=rel_tileset)],
        frames=frames,
        processing={"tilemap": tilemap_processing},
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D", "PaperTileSet"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    register_asset_version(project_root, asset_name, rel_tileset, file_role, label, asset_id=asset_id, kind="tilemap")
    return manifest


def create_tilemap_47_manifest(project_root: Path, asset_name: str, tileset_path: Path, tile_size: int, style_id: str, content_path: str) -> AssetManifest:
    return _create_tilemap_manifest(
        project_root,
        asset_name,
        tileset_path,
        tile_size,
        style_id,
        content_path,
        standard="47-tile",
        tile_ids=TILEMAP_47_IDS,
        columns=8,
        file_role="tileset:47",
        label="47-tile terrain",
    )


def create_tilemap_dual_grid_manifest(project_root: Path, asset_name: str, tileset_path: Path, tile_size: int, style_id: str, content_path: str) -> AssetManifest:
    return _create_tilemap_manifest(
        project_root,
        asset_name,
        tileset_path,
        tile_size,
        style_id,
        content_path,
        standard="dual-grid-16",
        tile_ids=TILEMAP_DUAL_GRID_16_IDS,
        columns=4,
        file_role="tileset:dual-grid-16",
        label="dual-grid 16 terrain",
        extra_processing={
            "grid": "dual",
            "maskBits": TILEMAP_DUAL_GRID_16_MASK_BITS,
            "maskRange": [0, 15],
            "maskOrder": "NW=1, NE=2, SW=4, SE=8",
        },
    )


def create_ui_concept(project_root: Path, asset_name: str, game_description: str, layout: str, style_id: str, image_provider: str, content_path: str) -> AssetManifest:
    asset_id = asset_id_from_name(asset_name)
    manifests = _asset_manifest_dir(project_root, asset_id)
    output = _ui_concept_dir(project_root, asset_id) / versioned_filename("ui_concept")
    prompt = (
        f"Create a full game UI concept screen. Game: {game_description}. "
        f"Layout: {layout}. Cohesive game UI, buttons, panels, icons, readable hierarchy, no tiny text, production concept art."
    )
    result = _generate_image(prompt, output, image_provider, size="1536x1024")
    rel_output = _rel(project_root, output)
    register_asset_version(project_root, asset_name, rel_output, "ui:concept", "UI concept", asset_id=asset_id, kind="game_ui")
    manifest = AssetManifest(
        asset_type="ui_kit",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role="ui:concept", path=rel_output)],
        processing={
            "uiConcept": {
                "prompt": prompt,
                "gameDescription": game_description,
                "layout": layout,
                "model": result.model,
                "provider": image_provider,
                "providerBaseUrl": result.base_url,
                "streamEvents": result.stream_events or [],
            },
            "widgets": [],
        },
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def import_ui_concept(project_root: Path, asset_name: str, source_path: Path, style_id: str, content_path: str) -> AssetManifest:
    asset_id = asset_id_from_name(asset_name)
    manifests = _asset_manifest_dir(project_root, asset_id)
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"UI concept image does not exist: {source_path}")
    Image, _, _ = _require_pillow()
    try:
        with Image.open(source_path) as image:
            image.verify()
    except Exception as exc:
        raise ValueError(f"UI concept image is not a readable image: {source_path}") from exc
    suffix = source_path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    output = _ui_concept_dir(project_root, asset_id) / versioned_filename("ui_concept_import", suffix=suffix)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, output)
    rel_output = _rel(project_root, output)
    register_asset_version(project_root, asset_name, rel_output, "ui:concept", "UI concept import", asset_id=asset_id, kind="game_ui")
    manifest = AssetManifest(
        asset_type="ui_kit",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role="ui:concept", path=rel_output)],
        processing={
            "uiConcept": {
                "source": "import",
                "sourcePath": str(source_path),
            },
            "widgets": [],
        },
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D"]}},
    )
    write_manifest(manifests / "manifest.json", manifest)
    return manifest


def create_ui_widget(
    project_root: Path,
    asset_name: str,
    widget_type: str,
    widget_description: str,
    concept_path: Path | None,
    style_id: str,
    image_provider: str,
    content_path: str,
    nine_slice: tuple[int, int, int, int] | None = None,
) -> AssetManifest:
    asset_id, generated, manifests = _asset_dirs(project_root, asset_name)
    if widget_type not in {"button", "panel", "icon"}:
        raise ValueError(f"Unknown UI widget type: {widget_type}")
    roles = ["normal", "hover", "pressed", "disabled"] if widget_type == "button" else ["panel"] if widget_type == "panel" else ["icon"]
    manifest_path = manifests / "manifest.json"
    existing: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            existing = read_json(manifest_path)
        except Exception:
            existing = {}
    existing_files = [AssetFile(**item) for item in existing.get("files", []) if isinstance(item, dict) and item.get("path")]
    existing_states = [UIState(**item) for item in existing.get("uiStates", []) if isinstance(item, dict) and item.get("file")]
    existing_processing = existing.get("processing") if isinstance(existing.get("processing"), dict) else {}
    existing_widgets = existing_processing.get("widgets") if isinstance(existing_processing.get("widgets"), list) else []
    files: list[AssetFile] = []
    states: list[UIState] = []
    widgets: list[dict[str, Any]] = []
    for role in roles:
        output = generated / versioned_filename(f"ui_{widget_type}_{role}")
        prompt = (
            f"Create a game UI {widget_type} texture state '{role}'. "
            f"Description: {widget_description}. Match the provided concept style if present. Transparent background where appropriate. No text labels."
        )
        result = _generate_image(prompt, output, image_provider, size="1024x1024", reference_path=concept_path)
        rel_output = _rel(project_root, output)
        files.append(AssetFile(role=f"ui_widget:{widget_type}:{role}", path=rel_output))
        states.append(UIState(name=role, file=rel_output))
        widgets.append(
            {
                "type": widget_type,
                "state": role,
                "path": rel_output,
                "model": result.model,
                "provider": image_provider,
                "providerBaseUrl": result.base_url,
                "streamEvents": result.stream_events or [],
            }
        )
        register_asset_version(project_root, asset_name, rel_output, f"ui_widget:{widget_type}:{role}", f"{widget_type} {role}", asset_id=asset_id, kind="game_ui")
    merged_files_by_path = {item.path: item for item in [*existing_files, *files]}
    merged_processing = dict(existing_processing)
    if "uiConcept" not in merged_processing and concept_path:
        merged_processing["uiConcept"] = {"path": _rel(project_root, concept_path) if concept_path.exists() else str(concept_path)}
    merged_processing["conceptPath"] = str(concept_path or "")
    merged_processing["widgets"] = [*existing_widgets, *widgets]
    manifest = AssetManifest(
        asset_type="ui_kit",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=list(merged_files_by_path.values()),
        ui_states=[*existing_states, *states],
        nine_slice=NineSlice(*nine_slice) if nine_slice else None,
        processing=merged_processing,
        targets={"unreal": {"contentPath": content_path, "create": ["Texture2D", "SlateBrushMetadata"]}},
    )
    write_manifest(manifest_path, manifest)
    return manifest


def create_seedance_walk_video(
    project_root: Path,
    asset_name: str,
    anchor_path: Path,
    direction: str,
    prompt: str,
    seconds: int,
    action: str = "walk",
    model: str | None = None,
    resolution: str | None = None,
    progress: Callable[[str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    asset_id, generated, _ = _asset_dirs(project_root, asset_name)
    if not anchor_path.exists() or not anchor_path.is_file():
        raise ValueError(f"Seedance anchor image does not exist: {anchor_path}")
    action_id = asset_id_from_name(action or "walk")
    output = generated / versioned_filename(f"{action_id}_{direction}", suffix=".mp4")
    chroma_prompt = (
        f"{prompt.rstrip()}\n\n"
        "Background constraint:\n"
        "- The background must remain pure #FF00FF magenta in every frame.\n"
        "- Do not change, shade, gradient, texture, shadow, or animate the #FF00FF background.\n"
        "- Do not turn the background into a floor, room, horizon, outdoor scene, perspective grid, shadow plane, or environment."
    )
    result = SeedanceProvider(model=model, resolution=resolution).generate_walk_video(anchor_path, chroma_prompt, output, seconds=seconds, progress=progress, is_cancelled=is_cancelled)
    rel_output = _rel(project_root, output)
    register_asset_version(project_root, asset_name, rel_output, f"video:{action_id}:{direction}", f"{action_id} video {direction}", asset_id=asset_id)
    return {**asdict(result), "output_path": str(result.output_path), "path": rel_output, "anchorPath": _rel(project_root, anchor_path)}
