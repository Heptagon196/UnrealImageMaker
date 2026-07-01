from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .asset_index import asset_id_from_name, load_asset_index, register_asset_version, save_asset_index
from .image_processing import _require_pillow
from .json_io import read_json, write_json
from .pixel_postprocess import apply_pixel_mask
from .providers.rembg_adapter import RembgAdapter
from .specialized import _generate_image

UI_STRUCTURE_SCHEMA = "uim.game_ui.structure.v1"
UI_KIT_SCHEMA = "uim.game_ui.kit.v1"
DEFAULT_UI_WIDTH = 1920
DEFAULT_UI_HEIGHT = 1080
ALLOWED_UI_NODE_TYPES = {
    "screen",
    "panel",
    "image",
    "text",
    "button",
    "input",
    "scroll",
    "checkbox",
    "slider",
    "dropdown",
}
ALLOWED_UI_ANCHORS = {
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "center",
    "top-stretch",
    "bottom-stretch",
    "left-stretch",
    "right-stretch",
    "full",
}
UI_PIVOT_PRESETS: dict[str, tuple[float, float]] = {
    "top-left": (0.0, 0.0),
    "top": (0.5, 0.0),
    "top-right": (1.0, 0.0),
    "left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0),
    "bottom": (0.5, 1.0),
    "bottom-right": (1.0, 1.0),
}
BUTTON_STATES = ("normal", "hover", "pressed", "disabled")
UI_ATLAS_CATALOG_VERSION = "ui-texture-atlas-v3"
UI_ATLAS_SIZE = (1536, 1024)
UI_ATLAS_GRID = (4, 4)
UI_ATLAS_SLOT_INSET = (32, 32)
UI_TEXTURE_GENERATION_SIZE = "1024x1024"
UI_TEXTURE_STATE_SHEET_SIZE = (1024, 1024)
UI_TEXTURE_DEFAULT_SIZE = (320, 192)
DEFAULT_UI_CHROMA_KEY = (255, 0, 255)
UI_TEXTURE_TARGET_SIZES: dict[str, tuple[int, int]] = {
    "panelDefault": (384, 256),
    "imageFrame": (256, 256),
    "textPlate": (384, 96),
    "buttonDefault": (320, 128),
    "inputDefault": (384, 112),
    "scrollTrack": (96, 384),
    "scrollThumb": (96, 256),
    "checkboxBox": (160, 160),
    "sliderTrack": (384, 80),
    "sliderFill": (384, 80),
    "sliderThumb": (160, 160),
    "dropdownBox": (384, 112),
    "dropdownArrow": (160, 160),
    "dropdownOption": (384, 96),
}
UI_TEXTURE_REQUIRED_STATES: dict[str, tuple[str, ...]] = {
    "panel": ("normal",),
    "image": ("normal",),
    "text": ("normal",),
    "button": BUTTON_STATES,
    "input": ("normal", "focused", "disabled", "error"),
    "scroll": ("normal", "disabled"),
    "checkbox": ("unchecked", "uncheckedHover", "checked", "checkedHover", "disabled"),
    "slider": ("normal", "disabled"),
    "dropdown": ("normal", "open", "disabled"),
}
DEFAULT_STYLE_TOKENS: dict[str, str] = {
    "panel": "panelDefault",
    "image": "imageFrame",
    "text": "textPlate",
    "button": "buttonDefault",
    "input": "inputDefault",
    "checkbox": "checkboxBox",
    "scroll": "scrollTrack",
    "slider": "sliderTrack",
    "dropdown": "dropdownBox",
}
BOX_STYLE_TOKENS = {
    "panelDefault",
    "textPlate",
    "buttonDefault",
    "inputDefault",
    "scrollTrack",
    "scrollThumb",
    "sliderTrack",
    "sliderFill",
    "dropdownBox",
    "dropdownOption",
}
DEFAULT_UI_TEXTURE_CATALOG: tuple[dict[str, str], ...] = (
    {"token": "panelDefault", "type": "panel", "states": "normal", "description": "general rectangular panel background with decorative border"},
    {"token": "imageFrame", "type": "image", "states": "normal", "description": "image portrait or item frame border with transparent center"},
    {"token": "textPlate", "type": "text", "states": "normal", "description": "subtle text label plate or title strip background, no letters"},
    {"token": "buttonDefault", "type": "button", "states": "normal,hover,pressed,disabled", "description": "primary game button background, no text"},
    {"token": "inputDefault", "type": "input", "states": "normal,focused,disabled,error", "description": "editable text box background and border, no text"},
    {"token": "scrollTrack", "type": "scroll", "states": "normal,disabled", "description": "vertical scroll bar track texture"},
    {"token": "scrollThumb", "type": "scroll", "states": "normal,hover,dragged,disabled", "description": "vertical scroll bar draggable thumb"},
    {"token": "checkboxBox", "type": "checkbox", "states": "unchecked,uncheckedHover,checked,checkedHover,disabled", "description": "checkbox square box, checked states include a clear check mark icon"},
    {"token": "sliderTrack", "type": "slider", "states": "normal,disabled", "description": "horizontal slider track"},
    {"token": "sliderFill", "type": "slider", "states": "normal,disabled", "description": "horizontal slider filled progress strip"},
    {"token": "sliderThumb", "type": "slider", "states": "normal,hover,disabled", "description": "slider draggable knob"},
    {"token": "dropdownBox", "type": "dropdown", "states": "normal,open,disabled", "description": "dropdown field background"},
    {"token": "dropdownArrow", "type": "dropdown", "states": "normal,open,disabled", "description": "dropdown arrow icon button"},
    {"token": "dropdownOption", "type": "dropdown", "states": "normal,hover,selected", "description": "dropdown option row background"},
)

UI_TEXTURE_TOKEN_SPECS: dict[str, dict[str, Any]] = {
    "paneldefault": {
        "shape": "large rectangular decorative background panel with readable border and a calm center surface",
        "transparent": "opaque plate; only outside the silhouette is transparent after cutout",
        "nineSlice": "nine-slice friendly: consistent border thickness, simple center, no corner-dependent details in stretch zones",
        "forbidden": "full UI screens, text, icons, portraits, inventory content, window chrome labels, noisy illustration",
    },
    "buttondefault": {
        "shape": "wide horizontal reusable button skin, centered in every slot",
        "transparent": "outside the button silhouette only; the button body remains solid enough for UMG button brushes",
        "nineSlice": "nine-slice friendly horizontal stretch skin with clean corners and consistent side borders",
        "forbidden": "letters, icons, glyphs, complete menu mockups, square badges, vertical button shapes",
    },
    "imageframe": {
        "shape": "portrait/item frame border with an empty transparent center window",
        "transparent": "the center hole must be transparent chroma background, not filled; only the frame border is artwork",
        "nineSlice": "not a filled panel; keep a clean frame ring with stable corners",
        "forbidden": "solid panels, filled centers, portraits, items, placeholder images, text labels, background art inside the opening",
    },
    "textplate": {
        "shape": "wide low-height label plate or title strip background",
        "transparent": "outside the strip silhouette only",
        "nineSlice": "nine-slice friendly horizontal strip with subtle center",
        "forbidden": "letters, numbers, captions, complete text boxes, icons",
    },
    "inputdefault": {
        "shape": "wide horizontal editable text input field skin",
        "transparent": "outside the field silhouette only; inner field remains simple and readable",
        "nineSlice": "nine-slice friendly border and quiet center, suitable for arbitrary typed text",
        "forbidden": "typed text, placeholder text, cursor, icons, labels, full forms",
    },
    "scrolltrack": {
        "shape": "vertical scrollbar empty track/rail only",
        "transparent": "outside the rail silhouette only",
        "nineSlice": "vertical stretch friendly rail with simple middle",
        "forbidden": "scroll thumb, arrows, page content, complete scrollbar widget",
    },
    "scrollthumb": {
        "shape": "vertical draggable scrollbar handle only",
        "transparent": "transparent margins around the handle",
        "nineSlice": "vertical stretch friendly handle, no surrounding rail",
        "forbidden": "full scroll track, arrows, page content, complete scrollbar widget",
    },
    "checkboxbox": {
        "shape": "square checkbox control; checked states may include one clear check mark",
        "transparent": "outside the square control silhouette only",
        "nineSlice": "not required; keep the box centered and readable",
        "forbidden": "field labels, surrounding settings rows, full menus, unrelated icons",
    },
    "slidertrack": {
        "shape": "horizontal empty slider track/rail only",
        "transparent": "outside the track silhouette only",
        "nineSlice": "horizontal stretch friendly rail, no knob",
        "forbidden": "draggable thumb, progress fill, complete slider bar, tick labels",
    },
    "sliderfill": {
        "shape": "horizontal filled progress strip only",
        "transparent": "outside the fill strip silhouette only",
        "nineSlice": "horizontal stretch friendly strip, no knob",
        "forbidden": "thumb/knob, empty track, complete slider widget, tick labels",
    },
    "sliderthumb": {
        "shape": "draw only the draggable thumb/knob handle: compact circular, hex, or rounded-square, centered in every slot",
        "transparent": "transparent margins around the knob; no horizontal strip behind it",
        "nineSlice": "not nine-slice; compact icon-like knob",
        "forbidden": "do not draw a slider track, progress fill, complete slider bar, tick marks, labels, second handle",
    },
    "dropdownbox": {
        "shape": "wide horizontal dropdown field skin",
        "transparent": "outside the field silhouette only; inner field remains simple and readable",
        "nineSlice": "nine-slice friendly horizontal stretch skin",
        "forbidden": "text, option list, arrow glyph, menu items, complete dropdown widget",
    },
    "dropdownarrow": {
        "shape": "single compact arrow/chevron glyph only",
        "transparent": "transparent around the glyph; no surrounding box unless the glyph itself needs a tiny bevel",
        "nineSlice": "not nine-slice; centered icon glyph",
        "forbidden": "dropdown field, option list, text, outer frame, complete dropdown widget",
    },
    "dropdownoption": {
        "shape": "wide horizontal dropdown option row background",
        "transparent": "outside the row silhouette only",
        "nineSlice": "horizontal stretch friendly row skin",
        "forbidden": "option text, check icons, arrow glyph, complete dropdown list",
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(value: str, fallback: str = "screen") -> str:
    return asset_id_from_name(value or fallback)


def _rel(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _normalize_chroma_key(value: Any = None) -> tuple[int, int, int]:
    if value is None:
        return DEFAULT_UI_CHROMA_KEY
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) == 6:
            try:
                return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
            except ValueError as exc:
                raise ValueError(f"Invalid chroma key hex: {value}") from exc
    if isinstance(value, (list, tuple)) and len(value) == 3:
        rgb = tuple(int(component) for component in value)
        if all(0 <= component <= 255 for component in rgb):
            return rgb  # type: ignore[return-value]
    raise ValueError("chroma_key must be an RGB triplet such as [255, 0, 255] or a #RRGGBB string.")


def _hex_color(rgb: tuple[int, int, int] | list[int]) -> str:
    red, green, blue = (max(0, min(255, int(component))) for component in rgb)
    return f"#{red:02X}{green:02X}{blue:02X}"


def _token_spec(token: str, widget_type: str) -> dict[str, Any]:
    normalized = _safe_name(token)
    if normalized in UI_TEXTURE_TOKEN_SPECS:
        return UI_TEXTURE_TOKEN_SPECS[normalized]
    if widget_type in {"panel", "button", "input", "dropdown", "text"}:
        return {
            "shape": "one clean reusable stretchable game UI plate",
            "transparent": "outside the component silhouette only",
            "nineSlice": "nine-slice friendly with consistent borders and simple center",
            "forbidden": "text, icons, full UI screens, scene props, complete widgets",
        }
    return {
        "shape": "only the named reusable game UI sub-component",
        "transparent": "transparent outside the component silhouette",
        "nineSlice": "use stable margins appropriate to the token",
        "forbidden": "full UI screens, mixed atlases, labels, unrelated controls",
    }


def _transparent_center_token(token: str) -> bool:
    return _safe_name(token) in {"imageframe"}


def _chroma_distance_mask(image: Any, chroma_key: tuple[int, int, int], *, tolerance: float = 96.0) -> Any:
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return None
    rgba = np.array(image.convert("RGBA"), dtype=np.int16)
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    key = np.array(chroma_key, dtype=np.int16)
    diff = rgb - key
    distance = np.sqrt(np.sum(diff.astype("float32") * diff.astype("float32"), axis=2))
    return (alpha <= 0) | (distance <= tolerance)


def _project_path(project_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _ui_root(project_root: Path) -> Path:
    return project_root / "ui"


def html_dir(project_root: Path) -> Path:
    return _ui_root(project_root) / "html"


def structure_dir(project_root: Path) -> Path:
    return _ui_root(project_root) / "structure"


def kit_dir(project_root: Path) -> Path:
    return _ui_root(project_root) / "kits"


def ui_texture_dir(project_root: Path, kit_name: str) -> Path:
    return _ui_root(project_root) / "textures" / _safe_name(kit_name, "ui_kit")


def ui_kit_work_dir(project_root: Path, kit_name: str) -> Path:
    return kit_dir(project_root) / _safe_name(kit_name, "ui_kit")


def default_texture_catalog() -> list[dict[str, Any]]:
    return [
        {
            "token": item["token"],
            "type": item["type"],
            "states": [state.strip() for state in item["states"].split(",") if state.strip()],
            "description": item["description"],
        }
        for item in DEFAULT_UI_TEXTURE_CATALOG
    ]


def _file_updated_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _remove_asset_versions_for_path(project_root: Path, rel_path: str, role: str | None = None) -> int:
    root = project_root.resolve()
    removed_count = 0
    for index_file in (root / "assets").glob("*/asset.index.json"):
        asset_id = index_file.parent.name
        index = load_asset_index(root, asset_id)
        remaining = []
        for version in index.versions:
            if version.path == rel_path and (role is None or version.role == role):
                removed_count += 1
                continue
            remaining.append(version)
        if len(remaining) != len(index.versions):
            index.versions = remaining
            save_asset_index(root, index)
    return removed_count


def _normalize_texture_catalog(widget_tokens: list[dict[str, Any]] | None, coverage: str) -> list[dict[str, Any]]:
    catalog = default_texture_catalog() if coverage == "default_full" else []
    for token in widget_tokens or []:
        token_name = str(token.get("token") or "").strip()
        widget_type = str(token.get("type") or "button").strip()
        if not token_name:
            raise ValueError("widget_tokens entries require token.")
        if widget_type not in ALLOWED_UI_NODE_TYPES - {"screen"}:
            raise ValueError(f"Unsupported UI texture type: {widget_type}")
        raw_states = token.get("states")
        if isinstance(raw_states, str):
            states = [state.strip() for state in raw_states.split(",") if state.strip()]
        elif isinstance(raw_states, list):
            states = [str(state).strip() for state in raw_states if str(state).strip()]
        else:
            states = list(UI_TEXTURE_REQUIRED_STATES.get(widget_type, ("normal",)))
        catalog.append(
            {
                "token": token_name,
                "type": widget_type,
                "states": states,
                "description": str(token.get("description") or token_name),
            }
        )
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in catalog:
        key = (str(item["token"]), str(item["type"]))
        if key in deduped:
            existing_states = list(deduped[key]["states"])
            for state in item["states"]:
                if state not in existing_states:
                    existing_states.append(state)
            deduped[key]["states"] = existing_states
            if item.get("description"):
                deduped[key]["description"] = item["description"]
        else:
            deduped[key] = dict(item)
    return list(deduped.values())


def _atlas_slots(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slots = []
    for item in catalog:
        for state in item["states"]:
            slots.append(
                {
                    "token": item["token"],
                    "state": state,
                    "type": item["type"],
                    "description": item["description"],
                    "nineSliceHint": item["type"] in {"panel", "button", "input", "dropdown", "text"},
                }
            )
    return slots


def _atlas_pages(slots: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    page_capacity = UI_ATLAS_GRID[0] * UI_ATLAS_GRID[1]
    return [slots[index : index + page_capacity] for index in range(0, len(slots), page_capacity)]


def _slot_rect(slot_index: int) -> dict[str, int]:
    atlas_width, atlas_height = UI_ATLAS_SIZE
    columns, rows = UI_ATLAS_GRID
    inset_x, inset_y = UI_ATLAS_SLOT_INSET
    cell_width = atlas_width // columns
    cell_height = atlas_height // rows
    column = slot_index % columns
    row = slot_index // columns
    return {
        "x": column * cell_width + inset_x,
        "y": row * cell_height + inset_y,
        "width": cell_width - inset_x * 2,
        "height": cell_height - inset_y * 2,
    }


def _create_atlas_guide(project_root: Path, kit_name: str, page_index: int, page_slots: list[dict[str, Any]]) -> dict[str, Any]:
    Image, _, _ = _require_pillow()
    from PIL import ImageDraw

    work = ui_kit_work_dir(project_root, kit_name)
    guide_dir = work / "atlas_guides"
    guide_dir.mkdir(parents=True, exist_ok=True)
    output = guide_dir / f"atlas_guide_{page_index + 1:02d}.png"
    metadata_path = guide_dir / f"atlas_guide_{page_index + 1:02d}.json"
    image = Image.new("RGBA", UI_ATLAS_SIZE, (255, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    slots = []
    for slot_index, slot in enumerate(page_slots):
        rect = _slot_rect(slot_index)
        x0, y0 = rect["x"], rect["y"]
        x1, y1 = x0 + rect["width"], y0 + rect["height"]
        draw.rectangle((x0, y0, x1, y1), outline=(0, 255, 255, 255), width=3)
        draw.rectangle((x0 + 8, y0 + 8, x0 + 44, y0 + 32), fill=(255, 255, 255, 220))
        draw.text((x0 + 14, y0 + 10), str(slot_index + 1), fill=(20, 25, 30, 255))
        slots.append({**slot, "slotIndex": slot_index, "rect": rect})
    image.save(output)
    metadata = {
        "schema": "uim.game_ui.atlas_guide.v1",
        "catalogVersion": UI_ATLAS_CATALOG_VERSION,
        "pageIndex": page_index,
        "atlasSize": {"width": UI_ATLAS_SIZE[0], "height": UI_ATLAS_SIZE[1]},
        "grid": {"columns": UI_ATLAS_GRID[0], "rows": UI_ATLAS_GRID[1]},
        "guidePath": _rel(project_root, output),
        "slots": slots,
    }
    write_json(metadata_path, metadata)
    metadata["metadataPath"] = _rel(project_root, metadata_path)
    return metadata


def _texture_target_size(slot: dict[str, Any]) -> tuple[int, int]:
    token = str(slot.get("token") or "")
    if token in UI_TEXTURE_TARGET_SIZES:
        return UI_TEXTURE_TARGET_SIZES[token]
    widget_type = str(slot.get("type") or "")
    if widget_type in {"panel", "button", "input", "dropdown", "text"}:
        return UI_TEXTURE_DEFAULT_SIZE
    if widget_type in {"checkbox", "slider"}:
        return (160, 160)
    return UI_TEXTURE_DEFAULT_SIZE


def _lanczos_resample() -> Any:
    Image, _, _ = _require_pillow()
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None:
        return resampling.LANCZOS
    return getattr(Image, "LANCZOS", 1)


def _state_guidance(state: str) -> str:
    return {
        "normal": "default usable state",
        "hover": "slightly brighter hover state",
        "pressed": "pressed/down state with darker inner surface",
        "disabled": "muted disabled state with lower contrast",
        "focused": "focused state with a clear but tasteful highlight",
        "error": "error state with restrained red warning accent",
        "checked": "checked state with a clear check mark",
        "checkedHover": "checked hover state with a clear check mark and mild highlight",
        "unchecked": "unchecked empty state",
        "uncheckedHover": "unchecked hover state with mild highlight",
        "open": "open/expanded state",
        "dragged": "actively dragged state",
        "selected": "selected state with visible selection accent",
    }.get(state, f"{state} state")


def _token_shape_guidance(token: str, widget_type: str) -> str:
    spec = _token_spec(token, widget_type)
    return (
        f"Target shape: {spec['shape']} "
        f"Transparent area requirement: {spec['transparent']} "
        f"Nine-slice/stretch requirement: {spec['nineSlice']} "
        f"Forbidden content: {spec['forbidden']}."
    )


def _is_wide_texture(size: tuple[int, int]) -> bool:
    return size[0] > size[1] * 1.35


def _is_tall_texture(size: tuple[int, int]) -> bool:
    return size[1] > size[0] * 1.35


def _token_state_slots(item: dict[str, Any]) -> list[dict[str, Any]]:
    states = list(item.get("states") or [])
    token = str(item.get("token") or "uiTexture")
    widget_type = str(item.get("type") or "panel")
    description = str(item.get("description") or token)
    target_size = _texture_target_size({"token": token, "type": widget_type})
    sheet_width, sheet_height = UI_TEXTURE_STATE_SHEET_SIZE
    margin = 64
    gap = 32
    count = max(1, len(states))
    slots: list[dict[str, Any]] = []
    if _is_wide_texture(target_size):
        slot_height = min(max(target_size[1] + 48, 128), max(96, (sheet_height - margin * 2 - gap * (count - 1)) // count))
        slot_width = sheet_width - margin * 2
        total_height = slot_height * count + gap * (count - 1)
        start_y = (sheet_height - total_height) // 2
        start_x = (sheet_width - slot_width) // 2
        rects = [
            {"x": start_x, "y": start_y + index * (slot_height + gap), "width": slot_width, "height": slot_height}
            for index in range(count)
        ]
    elif _is_tall_texture(target_size):
        slot_width = min(max(target_size[0] + 48, 128), max(96, (sheet_width - margin * 2 - gap * (count - 1)) // count))
        slot_height = min(sheet_height - margin * 2, max(target_size[1] + 160, 640))
        total_width = slot_width * count + gap * (count - 1)
        start_x = (sheet_width - total_width) // 2
        start_y = (sheet_height - slot_height) // 2
        rects = [
            {"x": start_x + index * (slot_width + gap), "y": start_y, "width": slot_width, "height": slot_height}
            for index in range(count)
        ]
    else:
        columns = 3 if count > 4 else min(count, 4)
        rows = (count + columns - 1) // columns
        cell_width = (sheet_width - margin * 2 - gap * (columns - 1)) // columns
        cell_height = (sheet_height - margin * 2 - gap * (rows - 1)) // rows
        slot_size = min(cell_width, cell_height)
        grid_width = columns * slot_size + gap * (columns - 1)
        grid_height = rows * slot_size + gap * (rows - 1)
        start_x = (sheet_width - grid_width) // 2
        start_y = (sheet_height - grid_height) // 2
        rects = []
        for index in range(count):
            column = index % columns
            row = index // columns
            rects.append({"x": start_x + column * (slot_size + gap), "y": start_y + row * (slot_size + gap), "width": slot_size, "height": slot_size})
    for index, state in enumerate(states):
        slots.append(
            {
                "token": token,
                "state": str(state),
                "type": widget_type,
                "description": description,
                "nineSliceHint": widget_type in {"panel", "button", "input", "dropdown", "text"},
                "stateIndex": index,
                "rect": rects[index],
                "targetSize": {"width": target_size[0], "height": target_size[1]},
            }
        )
    return slots


def _create_state_sheet_guide(project_root: Path, kit_name: str, item: dict[str, Any], chroma_key: Any = None) -> dict[str, Any]:
    Image, _, _ = _require_pillow()
    from PIL import ImageDraw

    chroma_rgb = _normalize_chroma_key(chroma_key)
    token = str(item.get("token") or "uiTexture")
    work = ui_kit_work_dir(project_root, kit_name)
    guide_dir = work / "state_guides"
    guide_dir.mkdir(parents=True, exist_ok=True)
    output = guide_dir / f"{_safe_name(token)}_state_guide.png"
    metadata_path = guide_dir / f"{_safe_name(token)}_state_guide.json"
    image = Image.new("RGBA", UI_TEXTURE_STATE_SHEET_SIZE, (*chroma_rgb, 255))
    draw = ImageDraw.Draw(image)
    slots = _token_state_slots(item)
    for slot in slots:
        rect = slot["rect"]
        x0, y0 = rect["x"], rect["y"]
        x1, y1 = x0 + rect["width"], y0 + rect["height"]
        draw.rectangle((x0, y0, x1, y1), outline=(0, 255, 255, 255), width=4)
        draw.rectangle((x0 + 8, y0 + 8, min(x0 + 140, x1 - 8), y0 + 36), fill=(255, 255, 255, 230))
        draw.text((x0 + 14, y0 + 12), str(slot["state"]), fill=(20, 25, 30, 255))
    image.save(output)
    metadata = {
        "schema": "uim.game_ui.state_sheet_guide.v1",
        "catalogVersion": UI_ATLAS_CATALOG_VERSION,
        "token": token,
        "type": item.get("type") or "panel",
        "sheetSize": {"width": UI_TEXTURE_STATE_SHEET_SIZE[0], "height": UI_TEXTURE_STATE_SHEET_SIZE[1]},
        "chromaKey": list(chroma_rgb),
        "chromaKeyHex": _hex_color(chroma_rgb),
        "guidePath": _rel(project_root, output),
        "slots": slots,
    }
    write_json(metadata_path, metadata)
    metadata["metadataPath"] = _rel(project_root, metadata_path)
    return metadata


def _state_sheet_prompt(kit_name: str, item: dict[str, Any], guide: dict[str, Any], chroma_key: Any = None) -> str:
    chroma_rgb = _normalize_chroma_key(chroma_key if chroma_key is not None else guide.get("chromaKey"))
    key_hex = _hex_color(chroma_rgb)
    token = str(item.get("token") or "uiTexture")
    widget_type = str(item.get("type") or "panel")
    description = str(item.get("description") or token)
    spec = _token_spec(token, widget_type)
    shape_guidance = _token_shape_guidance(token, widget_type)
    slot_lines = []
    for slot in guide["slots"]:
        size = slot["targetSize"]
        slot_lines.append(
            f"- {slot['state']}: {_state_guidance(str(slot['state']))}; final state PNG will be {size['width']}x{size['height']}"
        )
    forbidden_lines = "\n".join(f"- {part.strip()}" for part in str(spec["forbidden"]).split(",") if part.strip())
    return (
        "GLOBAL GAME UI STYLE CONSTRAINTS\n"
        f"- Create one state sheet for kit '{kit_name}' containing a single reusable Unreal Engine UMG / video game UI / HUD skin texture token.\n"
        "- This is not a physical object, full UI screen, website/app mockup, icon set, scene prop, logo, inventory item, or illustration.\n"
        "- The output must look like production video game interface skin art: reusable, isolated, orthographic, centered, clean at small UMG sizes.\n"
        "- The first reference image, when provided, is the concept image and primary visual target for style only: palette, material, line weight, corner language, bevel depth, glow/accent color, and ornament rhythm.\n"
        "- Do not copy concept layout, widgets, text, icons, screenshots, or full-screen composition.\n\n"
        "TOKEN-SPECIFIC ASSET CONTRACT\n"
        f"- Token: {token}\n"
        f"- Widget type: {widget_type}\n"
        f"- Purpose: {description}\n"
        f"- {shape_guidance}\n"
        f"- Shape: {spec['shape']}\n"
        f"- Transparency: {spec['transparent']}\n"
        f"- Nine-slice/stretch behavior: {spec['nineSlice']}\n"
        "- Forbidden content:\n"
        f"{forbidden_lines}\n\n"
        "STATE SHEET LAYOUT CONSTRAINTS\n"
        "- Use the state guide reference only for slot placement and state order; never copy guide labels, cyan rectangles, numbers, captions, or guide marks into the artwork.\n"
        "- Draw exactly one state variant inside each slot rectangle and keep the same geometry, silhouette, border thickness, perspective, and ornament placement across all states.\n"
        "- Only state-specific lighting, color intensity, pressed depth, disabled contrast, checked/open accents, or focus/error highlights may change.\n"
        f"- Every background pixel outside the texture must be exact {key_hex} key color.\n"
        f"- The key color {key_hex} is background only and is a forbidden pigment for the asset itself.\n"
        f"- Do not use {key_hex}, near-{key_hex} hues, key-colored glow, key-colored rim light, key-colored ambient reflection, or key-colored color bleeding anywhere on the control.\n"
        "- The control body, highlights, shadows, outlines, ornaments, bevels, transparent-center border, and antialiased edge pixels must all use non-key colors that remain clearly separable from the key background.\n"
        "- Do not merge slots. Do not reorder states. Do not draw labels, text, slot names, cursors, sample content, or complete widgets.\n"
        "- For transparent-center tokens such as imageFrame, the center must remain the key-color hole so it becomes transparent after cutout.\n\n"
        "REQUIRED STATES\n"
        + "\n".join(slot_lines)
    )


def _fit_ui_texture_to_canvas(image: Any, target_size: tuple[int, int], padding: int = 8) -> Any:
    Image, _, _ = _require_pillow()
    target_width, target_height = target_size
    canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return canvas
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    crop = image.crop((left, top, right, bottom))
    available_width = max(1, target_width - padding * 2)
    available_height = max(1, target_height - padding * 2)
    scale = min(available_width / crop.width, available_height / crop.height)
    resized_width = max(1, round(crop.width * scale))
    resized_height = max(1, round(crop.height * scale))
    crop = _resize_rgba_premultiplied(crop, (resized_width, resized_height), _lanczos_resample())
    paste_x = (target_width - resized_width) // 2
    paste_y = (target_height - resized_height) // 2
    canvas.alpha_composite(crop, (paste_x, paste_y))
    return canvas


def _resize_rgba_premultiplied(image: Any, size: tuple[int, int], resample: Any) -> Any:
    Image, _, _ = _require_pillow()
    rgba = image.convert("RGBA")
    try:
        import numpy as np  # type: ignore
    except ImportError:
        cleaned = rgba.copy()
        pixels = cleaned.load()
        for y in range(cleaned.height):
            for x in range(cleaned.width):
                r, g, b, a = pixels[x, y]
                if a <= 0:
                    pixels[x, y] = (0, 0, 0, 0)
        resized = cleaned.resize(size, resample)
        pixels = resized.load()
        for y in range(resized.height):
            for x in range(resized.width):
                r, g, b, a = pixels[x, y]
                if a < 4:
                    pixels[x, y] = (0, 0, 0, 0)
        return resized

    data = np.array(rgba, dtype=np.float32)
    alpha = data[:, :, 3:4] / 255.0
    premultiplied = data.copy()
    premultiplied[:, :, :3] *= alpha
    premultiplied_image = Image.fromarray(np.clip(premultiplied, 0, 255).astype("uint8"), "RGBA")
    resized = np.array(premultiplied_image.resize(size, resample), dtype=np.float32)
    resized_alpha = resized[:, :, 3]
    output = np.zeros_like(resized)
    visible = resized_alpha >= 4
    output[:, :, 3] = np.where(visible, resized_alpha, 0)
    if np.any(visible):
        output_rgb = output[:, :, :3]
        output_rgb[visible] = np.clip(resized[:, :, :3][visible] * 255.0 / resized_alpha[visible, None], 0, 255)
        output[:, :, :3] = output_rgb
    return Image.fromarray(output.astype("uint8"), "RGBA")


def _ui_chroma_cutout(image: Any, chroma_key: Any = None) -> tuple[Any, dict[str, Any]]:
    Image, _, _ = _require_pillow()
    chroma_rgb = _normalize_chroma_key(chroma_key)
    rgba = image.convert("RGBA")
    output = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    transparent_pixels = 0
    visible_pixels = 0
    chroma_mask = _chroma_distance_mask(rgba, chroma_rgb, tolerance=112.0)
    if chroma_mask is not None:
        try:
            import numpy as np  # type: ignore
        except ImportError:
            chroma_mask = None
        if chroma_mask is not None:
            data = np.array(rgba, dtype=np.uint8)
            transparent_pixels = int(chroma_mask.sum())
            visible_pixels = int(data.shape[0] * data.shape[1] - transparent_pixels)
            data[chroma_mask, 3] = 0
            output = Image.fromarray(data, "RGBA")
    if chroma_mask is None:
        source = rgba.load()
        target = output.load()
        kr, kg, kb = chroma_rgb
        for y in range(rgba.height):
            for x in range(rgba.width):
                r, g, b, a = source[x, y]
                distance = ((int(r) - kr) ** 2 + (int(g) - kg) ** 2 + (int(b) - kb) ** 2) ** 0.5
                is_chroma = a == 0 or distance <= 112
                if is_chroma:
                    target[x, y] = (r, g, b, 0)
                    transparent_pixels += 1
                else:
                    target[x, y] = (r, g, b, a)
                    visible_pixels += 1
    return output, {
        "mode": "ui_chroma",
        "chromaRgb": list(chroma_rgb),
        "chromaKey": list(chroma_rgb),
        "chromaKeyHex": _hex_color(chroma_rgb),
        "transparentPixels": transparent_pixels,
        "visiblePixels": visible_pixels,
    }


def _rembg_rgba(image: Any, temp_dir: Path, stem: str, model_name: str = "isnet-general-use") -> Any:
    Image, _, _ = _require_pillow()
    input_path = temp_dir / f"{stem}_rembg_input.png"
    output_path = temp_dir / f"{stem}_rembg.png"
    temp_dir.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").save(input_path)
    RembgAdapter(model_name=model_name).remove_background(input_path, output_path)
    with Image.open(output_path) as rembg_image:
        return rembg_image.convert("RGBA").copy()


def _rembg_component_regions(image: Any, temp_dir: Path, token: str, slots: list[dict[str, Any]], model_name: str = "isnet-general-use", chroma_key: Any = None) -> dict[str, dict[str, int]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return {}
    def collect_regions(mask: Any) -> list[dict[str, int | float]]:
        kernel = np.ones((5, 5), dtype="uint8")
        clean_mask = cv2.morphologyEx(mask.astype("uint8"), cv2.MORPH_CLOSE, kernel, iterations=1)
        labels_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(clean_mask, connectivity=8)
        min_area = max(256, int(image.width * image.height * 0.002))
        found: list[dict[str, int | float]] = []
        for label in range(1, labels_count):
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            width = int(stats[label, cv2.CC_STAT_WIDTH])
            height = int(stats[label, cv2.CC_STAT_HEIGHT])
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < min_area or width < 12 or height < 12:
                continue
            if width > image.width * 0.96 and height > image.height * 0.96:
                continue
            padding = 18
            left = max(0, x - padding)
            top = max(0, y - padding)
            right = min(image.width, x + width + padding)
            bottom = min(image.height, y + height + padding)
            found.append({"x": left, "y": top, "width": right - left, "height": bottom - top, "cx": (left + right) / 2, "cy": (top + bottom) / 2, "area": area})
        return found

    rembg_image = _rembg_rgba(image, temp_dir, f"{_safe_name(token)}_state_sheet", model_name=model_name)
    alpha = np.array(rembg_image.getchannel("A"))
    regions = collect_regions(alpha > 16)
    if len(regions) < len(slots):
        chroma_rgb = _normalize_chroma_key(chroma_key)
        rgba = np.array(image.convert("RGBA"))
        a = rgba[:, :, 3]
        rgb = rgba[:, :, :3].astype("int16")
        key = np.array(chroma_rgb, dtype=np.int16)
        diff = rgb - key
        chroma = np.sqrt(np.sum(diff.astype("float32") * diff.astype("float32"), axis=2)) <= 128
        regions = collect_regions((a > 0) & (~chroma))
    if len(regions) < len(slots):
        return {}
    assigned: dict[str, dict[str, int]] = {}
    used: set[int] = set()
    for slot in slots:
        rect = slot["rect"]
        state = str(slot["state"])
        slot_cx = rect["x"] + rect["width"] / 2
        slot_cy = rect["y"] + rect["height"] / 2
        best_index = -1
        best_distance = float("inf")
        for index, region in enumerate(regions):
            if index in used:
                continue
            dx = float(region["cx"]) - slot_cx
            dy = float(region["cy"]) - slot_cy
            distance = dx * dx + dy * dy
            if distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index < 0:
            return {}
        used.add(best_index)
        region = regions[best_index]
        assigned[state] = {"x": int(region["x"]), "y": int(region["y"]), "width": int(region["width"]), "height": int(region["height"])}
    return assigned


def _state_slot_crop_rect(slot: dict[str, Any], detected_rect: dict[str, int] | None) -> tuple[dict[str, int], str]:
    if detected_rect:
        return detected_rect, "detected_rect"
    return slot["rect"], "guide_rect"


def _cleanup_ui_crop(
    crop: Any,
    output_path: Path,
    temp_dir: Path,
    *,
    mask_mode: str,
    decontaminate_edges: bool,
    debug_artifacts: bool,
    target_size: tuple[int, int] | None = None,
    chroma_key: Any = None,
    model_name: str = "isnet-general-use",
    prefer_chroma_cutout: bool = False,
) -> dict[str, Any]:
    input_path = temp_dir / f"{output_path.stem}_raw.png"
    temp_dir.mkdir(parents=True, exist_ok=True)
    Image, _, _ = _require_pillow()
    chroma_rgb = _normalize_chroma_key(chroma_key)
    source = crop.convert("RGBA")
    source.save(input_path)
    if prefer_chroma_cutout:
        cleaned, report = _ui_chroma_cutout(source, chroma_rgb)
        report["mode"] = "ui_chroma_preferred"
    else:
        normalized_mask_mode = "rembg" if mask_mode == "rembg_only" else mask_mode
        rembg_alpha = None
        if normalized_mask_mode in {"hybrid", "rembg"}:
            rembg_image = _rembg_rgba(source, temp_dir, output_path.stem, model_name=model_name)
            rembg_alpha = rembg_image.getchannel("A")
        elif normalized_mask_mode != "classic":
            normalized_mask_mode = "hybrid"
            rembg_image = _rembg_rgba(source, temp_dir, output_path.stem, model_name=model_name)
            rembg_alpha = rembg_image.getchannel("A")
        debug_dir = temp_dir / "debug" if debug_artifacts else None
        cleaned, report = apply_pixel_mask(
            source,
            rembg_alpha=rembg_alpha,
            mode=normalized_mask_mode,
            decontaminate_edges=decontaminate_edges,
            debug_dir=debug_dir,
            debug_prefix=output_path.stem,
        )
    cleaned, chroma_report = _remove_ui_chroma_fringe(cleaned, chroma_rgb)
    report.update(chroma_report)
    cleaned, spill_report = _decontaminate_ui_chroma_spill(cleaned, chroma_rgb)
    report.update(spill_report)
    report["requestedMaskMode"] = mask_mode
    report["decontaminateEdges"] = decontaminate_edges
    report["preferChromaCutout"] = prefer_chroma_cutout
    report["chromaKey"] = list(chroma_rgb)
    report["chromaKeyHex"] = _hex_color(chroma_rgb)
    if target_size:
        cleaned = _fit_ui_texture_to_canvas(cleaned, target_size)
        cleaned, post_fit_chroma_report = _remove_ui_chroma_fringe(cleaned, chroma_rgb)
        cleaned, post_fit_spill_report = _decontaminate_ui_chroma_spill(cleaned, chroma_rgb)
        report["removedUiChromaFringePixelsPostFit"] = post_fit_chroma_report["removedUiChromaFringePixels"]
        report["decontaminatedUiChromaSpillPixelsPostFit"] = post_fit_spill_report["decontaminatedUiChromaSpillPixels"]
        report["targetSize"] = {"width": target_size[0], "height": target_size[1]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(output_path)
    if debug_artifacts:
        debug_dir = temp_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        cleaned.save(debug_dir / f"{output_path.stem}_mask_cleaned.png")
        write_json(temp_dir / f"{output_path.stem}_mask_report.json", report)
    return report


def _remove_ui_chroma_fringe(image: Any, background_rgb: Any = None) -> tuple[Any, dict[str, Any]]:
    Image, _, _ = _require_pillow()
    rgba = image.convert("RGBA")
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return rgba, {"removedUiChromaFringePixels": 0}

    data = np.array(rgba, dtype=np.uint8)
    alpha = data[:, :, 3]
    visible = alpha > 0
    rgb = data[:, :, :3].astype("int32")
    bg_tuple = _normalize_chroma_key(background_rgb)
    bg = np.array(bg_tuple, dtype=np.int32)
    diff = rgb - bg
    distance = np.sqrt(np.sum(diff.astype("float32") * diff.astype("float32"), axis=2))
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    near_key = visible & (distance <= 150)
    antialias_key = visible & (alpha < 245) & (distance <= 210)
    magenta_key = bg_tuple[0] >= 180 and bg_tuple[2] >= 180 and bg_tuple[1] <= 96
    dark_magenta_fringe = (
        visible
        & (alpha < 245)
        & (r >= 24)
        & (b >= 24)
        & (g <= 40)
        & (g * 3 <= np.minimum(r, b))
        & (np.abs(r - b) <= 120)
    ) if magenta_key else np.zeros_like(visible, dtype=bool)
    chroma_like = near_key | antialias_key | dark_magenta_fringe
    if not np.any(chroma_like):
        return rgba, {"removedUiChromaFringePixels": 0}

    transparent = alpha <= 0
    kernel = np.ones((3, 3), dtype="uint8")
    near_transparent = cv2.dilate(transparent.astype("uint8"), kernel, iterations=5).astype(bool)
    remove = chroma_like & near_transparent
    removed = int(remove.sum())
    if removed <= 0:
        return rgba, {"removedUiChromaFringePixels": 0}
    data[remove, :3] = 0
    data[remove, 3] = 0
    return Image.fromarray(data, "RGBA"), {"removedUiChromaFringePixels": removed}


def _decontaminate_ui_chroma_spill(image: Any, chroma_key: Any = None, edge_pixels: int = 8) -> tuple[Any, dict[str, Any]]:
    Image, _, _ = _require_pillow()
    rgba = image.convert("RGBA")
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from scipy import ndimage  # type: ignore
    except ImportError:
        return rgba, {"decontaminatedUiChromaSpillPixels": 0}

    chroma_rgb = _normalize_chroma_key(chroma_key)
    data = np.array(rgba, dtype=np.uint8)
    alpha = data[:, :, 3]
    visible = alpha > 0
    if not np.any(visible):
        return rgba, {"decontaminatedUiChromaSpillPixels": 0}

    rgb = data[:, :, :3].astype(np.int16)
    key = np.array(chroma_rgb, dtype=np.int16)
    distance = np.sqrt(np.sum((rgb - key).astype("float32") * (rgb - key).astype("float32"), axis=2))
    transparent = alpha <= 0
    kernel = np.ones((3, 3), dtype=np.uint8)
    edge_band = cv2.dilate(transparent.astype(np.uint8), kernel, iterations=max(1, edge_pixels)).astype(bool) & visible
    alpha_edge = visible & (alpha < 250)
    global_key_like = visible & (distance <= 132)
    soft_key_like = visible & (alpha < 245) & (distance <= 220)
    key_like = global_key_like | soft_key_like

    magenta_key = chroma_rgb[0] >= 180 and chroma_rgb[2] >= 180 and chroma_rgb[1] <= 96
    if magenta_key:
        r = rgb[:, :, 0]
        g = rgb[:, :, 1]
        b = rgb[:, :, 2]
        dark_magenta_bleed = visible & (alpha < 250) & (r >= 24) & (b >= 24) & (g <= 48) & (g * 3 <= np.minimum(r, b)) & (np.abs(r - b) <= 128)
        key_like = key_like | dark_magenta_bleed

    spill = global_key_like | (key_like & (edge_band | alpha_edge))
    if not np.any(spill):
        return rgba, {"decontaminatedUiChromaSpillPixels": 0}

    safe_source = visible & ~key_like
    if not np.any(safe_source):
        data[spill, :3] = 0
        data[spill, 3] = 0
        return Image.fromarray(data, "RGBA"), {"decontaminatedUiChromaSpillPixels": int(spill.sum()), "decontaminatedUiChromaSpillFallback": "removed"}

    nearest_indices = ndimage.distance_transform_edt(~safe_source, return_distances=False, return_indices=True)
    data[spill, :3] = data[nearest_indices[0][spill], nearest_indices[1][spill], :3]
    return Image.fromarray(data, "RGBA"), {"decontaminatedUiChromaSpillPixels": int(spill.sum())}


def _ui_texture_quality_report(image: Any, token: str, target_size: tuple[int, int], chroma_key: Any = None) -> dict[str, Any]:
    Image, _, _ = _require_pillow()
    chroma_rgb = _normalize_chroma_key(chroma_key)
    rgba = image.convert("RGBA")
    total_pixels = max(1, rgba.width * rgba.height)
    issues: list[str] = []
    try:
        import numpy as np  # type: ignore
    except ImportError:
        pixels = list(getattr(rgba, "get_flattened_data", rgba.getdata)())
        visible_pixels = 0
        residual_key_pixels = 0
        kr, kg, kb = chroma_rgb
        for r, g, b, a in pixels:
            if a <= 8:
                continue
            visible_pixels += 1
            distance = ((int(r) - kr) ** 2 + (int(g) - kg) ** 2 + (int(b) - kb) ** 2) ** 0.5
            if distance <= 80:
                residual_key_pixels += 1
        bbox = rgba.getchannel("A").getbbox()
        visible_ratio = visible_pixels / total_pixels
        report: dict[str, Any] = {
            "ok": True,
            "issues": issues,
            "chromaKey": list(chroma_rgb),
            "chromaKeyHex": _hex_color(chroma_rgb),
            "visiblePixels": visible_pixels,
            "transparentPixels": total_pixels - visible_pixels,
            "visibleRatio": visible_ratio,
            "residualKeyPixels": residual_key_pixels,
            "bbox": list(bbox) if bbox else None,
        }
    else:
        data = np.array(rgba, dtype=np.int16)
        alpha = data[:, :, 3]
        visible = alpha > 8
        visible_pixels = int(visible.sum())
        transparent_pixels = int(total_pixels - visible_pixels)
        key = np.array(chroma_rgb, dtype=np.int16)
        diff = data[:, :, :3] - key
        distance = np.sqrt(np.sum(diff.astype("float32") * diff.astype("float32"), axis=2))
        residual_key_pixels = int((visible & (distance <= 80)).sum())
        bbox = rgba.getchannel("A").getbbox()
        visible_ratio = visible_pixels / total_pixels
        report = {
            "ok": True,
            "issues": issues,
            "chromaKey": list(chroma_rgb),
            "chromaKeyHex": _hex_color(chroma_rgb),
            "visiblePixels": visible_pixels,
            "transparentPixels": transparent_pixels,
            "visibleRatio": visible_ratio,
            "residualKeyPixels": residual_key_pixels,
            "bbox": list(bbox) if bbox else None,
        }
        normalized = _safe_name(token)
        if normalized == "imageframe":
            left = int(rgba.width * 0.32)
            top = int(rgba.height * 0.32)
            right = max(left + 1, int(rgba.width * 0.68))
            bottom = max(top + 1, int(rgba.height * 0.68))
            center_alpha = alpha[top:bottom, left:right]
            center_alpha_mean = float(center_alpha.mean()) if center_alpha.size else 255.0
            report["centerAlphaMean"] = center_alpha_mean
            if center_alpha_mean > 32:
                issues.append("imageFrame center is not transparent")
        if normalized == "sliderthumb" and bbox:
            bbox_width = int(bbox[2] - bbox[0])
            bbox_height = int(bbox[3] - bbox[1])
            bbox_aspect = bbox_width / max(1, bbox_height)
            report["bboxAspect"] = bbox_aspect
            if bbox_width > rgba.width * 0.78 and bbox_aspect > 2.2:
                issues.append("sliderThumb looks like it contains a horizontal track")
    if not report["bbox"]:
        issues.append("no visible content")
    if visible_ratio < 0.02:
        issues.append(f"too little visible content: {visible_ratio:.3f}")
    residual_ratio = residual_key_pixels / max(1, visible_pixels)
    report["residualKeyRatio"] = residual_ratio
    if residual_key_pixels > max(8, int(visible_pixels * 0.01)):
        issues.append(f"visible key color contamination: {residual_key_pixels} pixels")
    if rgba.size != target_size:
        issues.append(f"size {rgba.width}x{rgba.height} != {target_size[0]}x{target_size[1]}")
    report["ok"] = len(issues) == 0
    return report


def _compose_local_texture_page(project_root: Path, kit_name: str, page: dict[str, Any], slot_outputs: dict[tuple[str, str], Path]) -> str:
    Image, _, _ = _require_pillow()
    output_dir = ui_kit_work_dir(project_root, kit_name) / "atlases"
    output_dir.mkdir(parents=True, exist_ok=True)
    atlas = Image.new("RGBA", UI_ATLAS_SIZE, (255, 0, 255, 255))
    for slot in page["slots"]:
        output = slot_outputs.get((str(slot["token"]), str(slot["state"])))
        if not output or not output.exists():
            continue
        rect = slot["rect"]
        with Image.open(output) as image:
            item = image.convert("RGBA")
        max_width = rect["width"]
        max_height = rect["height"]
        scale = min(max_width / item.width, max_height / item.height)
        resized = item.resize((max(1, round(item.width * scale)), max(1, round(item.height * scale))), _lanczos_resample())
        paste_x = rect["x"] + (max_width - resized.width) // 2
        paste_y = rect["y"] + (max_height - resized.height) // 2
        atlas.alpha_composite(resized, (paste_x, paste_y))
    output = output_dir / f"atlas_{page['pageIndex'] + 1:02d}.png"
    atlas.save(output)
    return _rel(project_root, output)


def game_ui_dsl_prompt(width: int = DEFAULT_UI_WIDTH, height: int = DEFAULT_UI_HEIGHT, project_root: str | None = None) -> str:
    project_root_line = f'当前打开的 UnrealImageMaker 项目 project_root 是："{project_root}"。' if project_root else "当前项目由 UnrealImageMaker 应用和 MCP 服务端维护；只做 HTML 原型时不要创建、查找、切换或询问工作区。"
    return f"""你是游戏 UI 原型工程师。请生成一个可被 UnrealImageMaker 转换为 Unreal UMG 的单文件 HTML。

写入当前 HTML 原型的强制 MCP 流程：
{project_root_line}
A. 不要只把 HTML 回复给用户；不要用普通文件写入、PowerShell、Python、Node、cat、重定向或本地编辑器写入 HTML。
B. 只做 HTML 原型时，不要创建、查找、打开、切换或确认工作区；当前项目由 MCP 服务端提供。
C. 必须通过 MCP tool 写入当前 UnrealImageMaker 工作区。调用顺序固定如下：
   1) 调用 game_ui_get_current_dsl_prompt(width={width}, height={height}) 获取最新 DSL 和 dslPromptToken。
   2) 如果用户没有提供 HTML 原型名称 / screen_name，先向用户询问名称；不要替用户擅自命名。名称必须是 camelCase，例如 shopScreen、battleHud、inventoryScreen。
   3) 生成完整单文件 HTML。
   4) 调用 game_ui_write_current_html(screen_name, html, dsl_prompt_token)，其中 dsl_prompt_token 必须使用第 1 步返回的 dslPromptToken。
   5) 只有 game_ui_write_current_html 返回 ok=true 才算完成；返回的 path 应位于当前项目的 ui/html/*.html。
如果 MCP 客户端只暴露显式 project_root 工具，则使用 game_ui_get_dsl_prompt(project_root, width={width}, height={height}) -> game_ui_write_html(project_root, screen_name, html, dsl_prompt_token)，但仍然不要创建或寻找工作区。
D. dslPromptToken 是一次性写入许可。每次重写 HTML 都必须重新调用 game_ui_get_current_dsl_prompt 或 game_ui_get_dsl_prompt 获取新 token。
E. 如果用户要求继续烘焙结构 JSON，再调用 game_ui_bake_html；不要在写入 HTML 前跳过 game_ui_write_current_html / game_ui_write_html。

必须遵守：
0. 你必须先通过 MCP tool game_ui_get_dsl_prompt 获取本提示词；该 tool 返回的 dslPromptToken 是一次性写入许可。调用 game_ui_write_html 时必须传入 dsl_prompt_token；每次写入 HTML 前都要重新获取新的 token。
1. 根节点必须声明 data-u-type="screen" 和 data-u-name，例如 data-u-name="shopScreen"。
2. 根节点不能锁定固定像素分辨率；必须使用 viewport 自适应，例如 width:100vw; height:100vh; min-width:100vw; min-height:100vh; position:relative; overflow:hidden;。
3. 所有要导入 UE 的节点必须包含 data-u-type 和唯一 data-u-name。
4. data-u-type 只能使用：screen, panel, image, text, button, input, scroll, checkbox, slider, dropdown。
5. 所有节点使用 position:absolute 和 px 坐标/尺寸；不要使用 CSS grid/flex 作为导出布局依据。
6. 除 screen 根节点外，所有导出节点都必须显式写 data-u-anchor，禁止省略。可用值：top-left, top-right, bottom-left, bottom-right, center, top-stretch, bottom-stretch, left-stretch, right-stretch, full。
7. 除 screen 根节点外，所有导出节点都必须显式写 data-u-pivot，禁止省略。可用值：0,0、0.5,0.5、1,1，或 top-left、center、bottom-right 等语义别名。
8. 锚点和 pivot 语义必须符合控件用途：角落 HUD 用对应 corner anchor 和同向 pivot；顶部/底部横条用 top-stretch/bottom-stretch 且 pivot 通常为 0,0；左右侧栏用 left-stretch/right-stretch；中心弹窗用 center + center；全屏背景用 full + 0,0。
9. data-u-name 使用 camelCase，必须唯一。
10. 可用 data-u-style-token 标记贴图语义，例如 primaryButton、panelDark、iconCurrency。
11. 按钮文字、标题、数值等文本必须使用独立 data-u-type="text" 节点；不要只写在父容器里。
12. 禁止外部图片、SVG、canvas、伪元素、复杂 CSS 动画和远程字体。
13. 输出完整 HTML，不要解释，不要 Markdown 代码块。
"""


def _parse_ui_pivot(value: Any, node_name: str = "") -> tuple[float, float]:
    text = str(value or "").strip().lower()
    if text in UI_PIVOT_PRESETS:
        return UI_PIVOT_PRESETS[text]
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2:
        raise ValueError(f'UI node "{node_name}" has invalid data-u-pivot. Use "0,0", "0.5,0.5", or a preset such as "center".')
    try:
        pivot_x = float(parts[0])
        pivot_y = float(parts[1])
    except ValueError as exc:
        raise ValueError(f'UI node "{node_name}" has invalid data-u-pivot. Pivot values must be numbers between 0 and 1.') from exc
    if not (0.0 <= pivot_x <= 1.0 and 0.0 <= pivot_y <= 1.0):
        raise ValueError(f'UI node "{node_name}" has invalid data-u-pivot. Pivot values must be between 0 and 1.')
    return pivot_x, pivot_y


def _layout_for_anchor_preset(
    preset: str,
    x: int,
    y: int,
    width: int,
    height: int,
    root_width: int,
    root_height: int,
    pivot: tuple[float, float] = (0.0, 0.0),
) -> dict[str, Any]:
    normalized = (preset or "top-left").strip().lower()
    anchors_by_preset = {
        "top-left": (0.0, 0.0, 0.0, 0.0),
        "top-right": (1.0, 0.0, 1.0, 0.0),
        "bottom-left": (0.0, 1.0, 0.0, 1.0),
        "bottom-right": (1.0, 1.0, 1.0, 1.0),
        "center": (0.5, 0.5, 0.5, 0.5),
        "top-stretch": (0.0, 0.0, 1.0, 0.0),
        "bottom-stretch": (0.0, 1.0, 1.0, 1.0),
        "left-stretch": (0.0, 0.0, 0.0, 1.0),
        "right-stretch": (1.0, 0.0, 1.0, 1.0),
        "full": (0.0, 0.0, 1.0, 1.0),
    }
    min_x, min_y, max_x, max_y = anchors_by_preset.get(normalized, anchors_by_preset["top-left"])
    if normalized not in anchors_by_preset:
        normalized = "top-left"
    pivot_x, pivot_y = pivot
    left = x - (min_x * root_width) + (width * pivot_x if min_x == max_x else 0)
    top = y - (min_y * root_height) + (height * pivot_y if min_y == max_y else 0)
    right = width if min_x == max_x else (max_x * root_width) - (x + width)
    bottom = height if min_y == max_y else (max_y * root_height) - (y + height)
    return {
        "anchorPreset": normalized,
        "anchors": {"minimum": {"x": min_x, "y": min_y}, "maximum": {"x": max_x, "y": max_y}},
        "offsets": {"left": round(left), "top": round(top), "right": round(right), "bottom": round(bottom)},
        "alignment": {"x": pivot_x, "y": pivot_y},
    }


def _ensure_ui_layout_metadata(
    node: dict[str, Any],
    parent_width: int,
    parent_height: int,
    parent_x: int = 0,
    parent_y: int = 0,
) -> None:
    if not isinstance(node, dict):
        return
    has_layout = isinstance(node.get("anchors"), dict) and isinstance(node.get("offsets"), dict)
    node_x = int(node.get("x") or 0)
    node_y = int(node.get("y") or 0)
    if not has_layout:
        node.update(
            _layout_for_anchor_preset(
                str(node.get("anchorPreset") or "top-left"),
                node_x - parent_x,
                node_y - parent_y,
                int(node.get("width") or 0),
                int(node.get("height") or 0),
                parent_width,
                parent_height,
                (
                    float((node.get("alignment") or {}).get("x", 0.0)) if isinstance(node.get("alignment"), dict) else 0.0,
                    float((node.get("alignment") or {}).get("y", 0.0)) if isinstance(node.get("alignment"), dict) else 0.0,
                ),
            )
        )
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _ensure_ui_layout_metadata(child, int(node.get("width") or parent_width), int(node.get("height") or parent_height), node_x, node_y)


class _UiHtmlContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        if "data-u-type" in attributes or "data-u-name" in attributes:
            self.nodes.append(attributes)


def validate_html_source(html: str) -> None:
    lowered = html.lower()
    forbidden = [
        ("<svg", "SVG is not supported in UI structure export."),
        ("<canvas", "Canvas is not supported in UI structure export."),
        ("::before", "CSS pseudo-elements are not supported in UI structure export."),
        ("::after", "CSS pseudo-elements are not supported in UI structure export."),
        ("http://", "External URLs are not allowed in UI HTML."),
        ("https://", "External URLs are not allowed in UI HTML."),
    ]
    for marker, message in forbidden:
        if marker in lowered:
            raise ValueError(message)
    parser = _UiHtmlContractParser()
    parser.feed(html)
    screen_nodes = [node for node in parser.nodes if node.get("data-u-type", "").strip().lower() == "screen"]
    if not screen_nodes:
        raise ValueError('UI HTML must include one root node with data-u-type="screen".')
    if len(screen_nodes) != 1:
        raise ValueError("UI HTML must include exactly one screen root node.")
    screen = screen_nodes[0]
    if not screen.get("data-u-name", "").strip():
        raise ValueError('The screen root node must include data-u-name.')
    root_style = screen.get("style", "")
    if not root_style.strip():
        raise ValueError("The screen root must declare responsive width/height style.")
    if re.search(r"(?:^|;)\s*(?:width|height)\s*:\s*\d+(?:\.\d+)?px\s*(?:;|$)", root_style, flags=re.IGNORECASE):
        raise ValueError("The screen root must not lock a fixed pixel width/height. Use viewport sizing such as width:100vw;height:100vh.")
    if not re.search(r"(?:^|;)\s*width\s*:", root_style, flags=re.IGNORECASE) or not re.search(r"(?:^|;)\s*height\s*:", root_style, flags=re.IGNORECASE):
        raise ValueError("The screen root must declare both responsive width and height.")
    for node in parser.nodes:
        node_type = node.get("data-u-type", "").strip().lower()
        node_name = node.get("data-u-name", "").strip()
        if not node_type or not node_name:
            raise ValueError("Every exported UI node must include both data-u-type and data-u-name.")
        if node_type not in ALLOWED_UI_NODE_TYPES:
            raise ValueError(f"Unsupported data-u-type: {node_type}")
        if node_type == "screen":
            continue
        anchor = node.get("data-u-anchor", "").strip().lower()
        if not anchor:
            raise ValueError(f'UI node "{node_name}" must include explicit data-u-anchor.')
        if anchor not in ALLOWED_UI_ANCHORS:
            raise ValueError(f'UI node "{node_name}" has unsupported data-u-anchor: {anchor}')
        pivot = node.get("data-u-pivot", "").strip()
        if not pivot:
            raise ValueError(f'UI node "{node_name}" must include explicit data-u-pivot.')
        _parse_ui_pivot(pivot, node_name)


def write_game_ui_html(project_root: Path, screen_name: str, html: str) -> dict[str, Any]:
    root = project_root.resolve()
    validate_html_source(html)
    name = _safe_name(screen_name)
    output = html_dir(root) / f"{name}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8", newline="\n")
    rel = _rel(root, output)
    register_asset_version(root, screen_name, rel, "ui_html:prototype", "UI HTML prototype", asset_id=_safe_name(screen_name), kind="game_ui")
    return {"screenName": screen_name, "path": rel, "absolutePath": str(output)}


def list_game_ui_html_prototypes(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    items = []
    for path in sorted(html_dir(root).glob("*.html")):
        items.append(
            {
                "screenName": path.stem,
                "path": _rel(root, path),
                "updatedAt": _file_updated_at(path),
            }
        )
    return {"htmlPrototypes": items}


def read_game_ui_html(project_root: Path, html_path: str) -> dict[str, Any]:
    root = project_root.resolve()
    source = _project_path(root, html_path)
    if source is None or not source.exists() or not source.is_file():
        raise ValueError(f"UI HTML file does not exist: {html_path}")
    source.relative_to(root)
    source.relative_to(html_dir(root).resolve())
    if source.suffix.lower() != ".html":
        raise ValueError("UI HTML path must point to a .html file.")
    return {"path": _rel(root, source), "html": source.read_text(encoding="utf-8"), "updatedAt": _file_updated_at(source)}


def delete_game_ui_html(project_root: Path, html_path: str) -> dict[str, Any]:
    root = project_root.resolve()
    source = _project_path(root, html_path)
    if source is None or not source.exists() or not source.is_file():
        raise ValueError(f"UI HTML file does not exist: {html_path}")
    source.relative_to(root)
    source.relative_to(html_dir(root).resolve())
    if source.suffix.lower() != ".html":
        raise ValueError("UI HTML path must point to a .html file.")
    rel = _rel(root, source)
    source.unlink()
    removed_versions = _remove_asset_versions_for_path(root, rel, "ui_html:prototype")
    return {"deleted": rel, "removedVersions": removed_versions}


def _bake_html_with_playwright(html: str, width: int, height: int) -> dict[str, Any]:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return _bake_html_with_node_playwright(html, width, height, import_error=RuntimeError("Playwright Sync API cannot run inside an asyncio loop."))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return _bake_html_with_node_playwright(html, width, height, import_error=exc)

    js = """
    ([allowedTypes, expectedWidth, expectedHeight]) => {
      const allowed = new Set(allowedTypes);
      const root = document.querySelector('[data-u-type="screen"][data-u-name]');
      if (!root) throw new Error('Missing root node: data-u-type="screen" and data-u-name are required.');
      const seen = new Set();
      const rootRect = root.getBoundingClientRect();
      function rgb2hex(value) {
        if (!value || value === 'transparent' || value === 'rgba(0, 0, 0, 0)') return '#FFFFFF00';
        const match = value.match(/^rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)$/);
        if (!match) return value;
        const hex = (n) => (`0${Number(n).toString(16)}`).slice(-2);
        const alpha = match[4] === undefined ? '' : hex(Math.round(Number(match[4]) * 255));
        return `#${hex(match[1])}${hex(match[2])}${hex(match[3])}${alpha}`;
      }
      function parseNumber(value, fallback) {
        const parsed = Number.parseFloat(value);
        return Number.isFinite(parsed) ? parsed : fallback;
      }
      function parsePivot(value, nodeName) {
        const presets = {
          'top-left': [0, 0],
          top: [0.5, 0],
          'top-right': [1, 0],
          left: [0, 0.5],
          center: [0.5, 0.5],
          right: [1, 0.5],
          'bottom-left': [0, 1],
          bottom: [0.5, 1],
          'bottom-right': [1, 1],
        };
        const text = String(value || '').trim().toLowerCase();
        if (presets[text]) return presets[text];
        const parts = text.split(',').map((part) => part.trim());
        if (parts.length !== 2) throw new Error(`UI node "${nodeName}" has invalid data-u-pivot.`);
        const pivotX = Number(parts[0]);
        const pivotY = Number(parts[1]);
        if (!Number.isFinite(pivotX) || !Number.isFinite(pivotY) || pivotX < 0 || pivotX > 1 || pivotY < 0 || pivotY > 1) {
          throw new Error(`UI node "${nodeName}" has invalid data-u-pivot. Pivot values must be between 0 and 1.`);
        }
        return [pivotX, pivotY];
      }
      function layoutForPreset(preset, x, y, width, height, rootWidth, rootHeight, pivot) {
        const anchorsByPreset = {
          'top-left': [0, 0, 0, 0],
          'top-right': [1, 0, 1, 0],
          'bottom-left': [0, 1, 0, 1],
          'bottom-right': [1, 1, 1, 1],
          center: [0.5, 0.5, 0.5, 0.5],
          'top-stretch': [0, 0, 1, 0],
          'bottom-stretch': [0, 1, 1, 1],
          'left-stretch': [0, 0, 0, 1],
          'right-stretch': [1, 0, 1, 1],
          full: [0, 0, 1, 1],
        };
        const normalized = String(preset || 'top-left').trim().toLowerCase();
        const values = anchorsByPreset[normalized] || anchorsByPreset['top-left'];
        const [minX, minY, maxX, maxY] = values;
        const [pivotX, pivotY] = pivot || [0, 0];
        return {
          anchorPreset: anchorsByPreset[normalized] ? normalized : 'top-left',
          anchors: { minimum: { x: minX, y: minY }, maximum: { x: maxX, y: maxY } },
          offsets: {
            left: Math.round(x - minX * rootWidth + (minX === maxX ? width * pivotX : 0)),
            top: Math.round(y - minY * rootHeight + (minY === maxY ? height * pivotY : 0)),
            right: Math.round(minX === maxX ? width : maxX * rootWidth - (x + width)),
            bottom: Math.round(minY === maxY ? height : maxY * rootHeight - (y + height)),
          },
          alignment: { x: pivotX, y: pivotY },
        };
      }
      function inferAnchorPreset(element, style, x, y, width, height, rootWidth, rootHeight) {
        const allowedAnchors = new Set([
          'top-left',
          'top-right',
          'bottom-left',
          'bottom-right',
          'center',
          'top-stretch',
          'bottom-stretch',
          'left-stretch',
          'right-stretch',
          'full',
        ]);
        const explicit = element.getAttribute('data-u-anchor');
        if (!explicit) throw new Error(`UI node "${element.getAttribute('data-u-name') || ''}" must include explicit data-u-anchor.`);
        const normalized = explicit.trim().toLowerCase();
        if (!allowedAnchors.has(normalized)) throw new Error(`Unsupported data-u-anchor on "${element.getAttribute('data-u-name') || ''}": ${explicit}`);
        return normalized;
      }
      function bake(element, parentRect) {
        const type = element.getAttribute('data-u-type');
        const name = element.getAttribute('data-u-name');
        if (!type && !name) return null;
        if (!type || !name) throw new Error('Every exported node must include both data-u-type and data-u-name.');
        if (!allowed.has(type)) throw new Error(`Unsupported data-u-type: ${type}`);
        if (seen.has(name)) throw new Error(`Duplicate data-u-name: ${name}`);
        seen.add(name);
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        const children = [];
        for (const child of Array.from(element.children)) {
          if (element.tagName.toLowerCase() === 'select' && child.tagName.toLowerCase() === 'option') continue;
          const baked = bake(child, rect);
          if (baked) children.push(baked);
        }
        const options = [];
        if (type === 'dropdown' && element.tagName.toLowerCase() === 'select') {
          for (const option of Array.from(element.querySelectorAll('option'))) options.push(option.innerText.trim());
        }
        const x = Math.round(rect.left - rootRect.left);
        const y = Math.round(rect.top - rootRect.top);
        const localX = Math.round(rect.left - (parentRect ? parentRect.left : rootRect.left));
        const localY = Math.round(rect.top - (parentRect ? parentRect.top : rootRect.top));
        const parentWidth = Math.round(parentRect ? parentRect.width : (rootRect.width || expectedWidth));
        const parentHeight = Math.round(parentRect ? parentRect.height : (rootRect.height || expectedHeight));
        const nodeWidth = Math.round(rect.width);
        const nodeHeight = Math.round(rect.height);
        const anchorPreset = type === 'screen' ? 'full' : inferAnchorPreset(element, style, localX, localY, nodeWidth, nodeHeight, parentWidth, parentHeight);
        const pivot = type === 'screen' ? [0, 0] : parsePivot(element.getAttribute('data-u-pivot'), name);
        const layout = layoutForPreset(anchorPreset, localX, localY, nodeWidth, nodeHeight, parentWidth, parentHeight, pivot);
        return {
          name,
          type,
          styleToken: element.getAttribute('data-u-style-token') || '',
          x,
          y,
          width: nodeWidth,
          height: nodeHeight,
          anchorPreset: layout.anchorPreset,
          anchors: layout.anchors,
          offsets: layout.offsets,
          alignment: layout.alignment,
          color: rgb2hex(style.backgroundColor),
          fontColor: rgb2hex(style.color),
          fontSize: Math.round(parseNumber(style.fontSize, 16)),
          fontWeight: style.fontWeight || '',
          textAlign: style.textAlign || 'center',
          text: (type === 'input' ? (element.value || element.placeholder || '') : (['text', 'button', 'dropdown'].includes(type) ? element.innerText || '' : '')).trim(),
          value: parseNumber(element.getAttribute('data-u-value'), 0.5),
          checked: element.getAttribute('data-u-checked') === 'true',
          direction: element.getAttribute('data-u-dir') || 'v',
          options,
          children
        };
      }
      const tree = bake(root, null);
      return {
        width: Math.round(rootRect.width) || expectedWidth,
        height: Math.round(rootRect.height) || expectedHeight,
        root: tree
      };
    }
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(100)
            return page.evaluate(js, [sorted(ALLOWED_UI_NODE_TYPES), width, height])
        finally:
            browser.close()


def _bake_html_with_node_playwright(html: str, width: int, height: int, import_error: Exception) -> dict[str, Any]:
    node = shutil.which("node")
    script = Path(__file__).with_name("game_ui_bake.mjs")
    if not node or not script.exists():
        raise RuntimeError("Playwright is required to bake UI HTML. Install backend requirements and run: python -m playwright install chromium") from import_error
    payload = json.dumps({"html": html, "width": width, "height": height, "allowedTypes": sorted(ALLOWED_UI_NODE_TYPES)}, ensure_ascii=False).encode("utf-8")
    env = os.environ.copy()
    env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    result = subprocess.run(
        [node, str(script)],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Playwright HTML bake failed: {detail or 'node playwright exited with an error'}")
    return json.loads(result.stdout.decode("utf-8"))


def bake_game_ui_html(project_root: Path, screen_name: str, html_path: str | None = None, width: int = DEFAULT_UI_WIDTH, height: int = DEFAULT_UI_HEIGHT) -> dict[str, Any]:
    root = project_root.resolve()
    source = _project_path(root, html_path) if html_path else html_dir(root) / f"{_safe_name(screen_name)}.html"
    if source is None or not source.exists() or not source.is_file():
        raise ValueError(f"UI HTML file does not exist: {source}")
    source.resolve().relative_to(root)
    html = source.read_text(encoding="utf-8")
    validate_html_source(html)
    baked = _bake_html_with_playwright(html, width, height)
    root_width = int(baked.get("width") or width)
    root_height = int(baked.get("height") or height)
    _ensure_ui_layout_metadata(baked["root"], root_width, root_height)
    structure = {
        "schema": UI_STRUCTURE_SCHEMA,
        "screenName": screen_name,
        "sourceHtml": _rel(root, source),
        "referenceResolution": {"width": root_width, "height": root_height},
        "root": baked["root"],
        "createdAt": _now(),
    }
    output = structure_dir(root) / f"{_safe_name(screen_name)}.uim-ui.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, structure)
    rel = _rel(root, output)
    register_asset_version(root, screen_name, rel, "ui_structure:json", "UI structure JSON", asset_id=_safe_name(screen_name), kind="game_ui")
    return {"screenName": screen_name, "path": rel, "absolutePath": str(output), "structure": structure}


def list_game_ui_structures(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    items = []
    for path in sorted(structure_dir(root).glob("*.uim-ui.json")):
        try:
            data = read_json(path)
        except Exception:
            data = {}
        items.append(
            {
                "screenName": data.get("screenName") or path.stem,
                "path": _rel(root, path),
                "referenceResolution": data.get("referenceResolution") or {},
                "createdAt": data.get("createdAt") or "",
            }
        )
    return {"structures": items}


def delete_game_ui_structure(project_root: Path, structure_path: str) -> dict[str, Any]:
    root = project_root.resolve()
    target = _project_path(root, structure_path)
    if target is None or not target.exists() or not target.is_file():
        raise ValueError(f"UI structure JSON does not exist: {structure_path}")
    target.relative_to(root)
    target.relative_to(structure_dir(root).resolve())
    if not target.name.endswith(".uim-ui.json"):
        raise ValueError("UI structure path must point to a .uim-ui.json file.")
    rel = _rel(root, target)
    target.unlink()
    removed_versions = _remove_asset_versions_for_path(root, rel, "ui_structure:json")
    return {"deleted": rel, "removedVersions": removed_versions}


def _normalize_kit_files(project_root: Path, files: Any) -> dict[str, Any]:
    textures: dict[str, Any] = {}
    def normalize_state_value(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        text = str(value or "")
        return {"unrealPath": text} if text.startswith("/Game/") else {"path": text}

    if isinstance(files, dict):
        iterable = []
        for token, value in files.items():
            if isinstance(value, dict) and "states" in value:
                for state, state_value in value["states"].items():
                    iterable.append({"token": token, "state": state, **normalize_state_value(state_value)})
            else:
                iterable.append({"token": token, "state": "normal", **normalize_state_value(value)})
    elif isinstance(files, list):
        iterable = files
    else:
        raise ValueError("Texture kit files must be a list or mapping.")

    for item in iterable:
        if not isinstance(item, dict):
            raise ValueError("Texture kit file entries must be objects.")
        token = str(item.get("token") or "").strip()
        state = str(item.get("state") or "normal").strip() or "normal"
        path_value = str(item.get("path") or "").strip()
        unreal_path = str(item.get("unrealPath") or item.get("unreal_path") or "").strip()
        if not token or (not path_value and not unreal_path):
            raise ValueError("Texture kit file entries require token and either path or unrealPath.")
        rel_path = ""
        if path_value:
            resolved = _project_path(project_root, path_value)
            if resolved is None:
                raise ValueError("Texture kit path is empty.")
            resolved.relative_to(project_root.resolve())
            if not resolved.exists() or not resolved.is_file():
                raise ValueError(f"Texture kit file does not exist: {resolved}")
            rel_path = _rel(project_root, resolved)
        entry = textures.setdefault(token, {"states": {}})
        entry["states"][state] = {
            "path": rel_path,
            "unrealPath": unreal_path,
        }
    return textures


def register_texture_kit(project_root: Path, kit_name: str, files: Any, content_path: str = "/Game/UIM/UI", generation: dict[str, Any] | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    name = _safe_name(kit_name, "ui_kit")
    textures = _normalize_kit_files(root, files)
    kit = {
        "schema": UI_KIT_SCHEMA,
        "kitName": kit_name,
        "contentPath": content_path,
        "textures": textures,
        "generation": generation or {},
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    output = kit_dir(root) / f"{name}.uim-uikit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, kit)
    return {"kitName": kit_name, "path": _rel(root, output), "absolutePath": str(output), "kit": kit, "validation": validate_texture_kit(kit)}


def list_texture_kits(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    items = []
    registered_names: set[str] = set()
    for path in sorted(kit_dir(root).glob("*.uim-uikit.json")):
        try:
            data = read_json(path)
        except Exception:
            data = {}
        kit_name = str(data.get("kitName") or path.stem.replace(".uim-uikit", ""))
        registered_names.add(_safe_name(kit_name, "ui_kit"))
        items.append(
            {
                "kitName": kit_name,
                "path": _rel(root, path),
                "contentPath": data.get("contentPath") or "",
                "tokens": sorted((data.get("textures") or {}).keys()) if isinstance(data.get("textures"), dict) else [],
                "validation": validate_texture_kit(data),
                "inProgress": False,
            }
        )
    discovered_names: set[str] = set()
    for directory in (kit_dir(root), _ui_root(root) / "textures"):
        if not directory.exists() or not directory.is_dir():
            continue
        for child in directory.iterdir():
            if child.is_dir():
                discovered_names.add(child.name)
    for safe_name in sorted(discovered_names - registered_names):
        partial_files = _existing_texture_kit_partial_files(root, safe_name, None, "default_full")
        state_sheet_dir = kit_dir(root) / safe_name / "state_sheets"
        state_sheet_count = len(list(state_sheet_dir.glob("*_states.png"))) if state_sheet_dir.exists() else 0
        if not partial_files and state_sheet_count <= 0:
            continue
        tokens = sorted({str(item["token"]) for item in partial_files} | _tokens_from_state_sheet_dir(state_sheet_dir))
        items.append(
            {
                "kitName": safe_name,
                "path": "",
                "contentPath": "",
                "tokens": tokens,
                "validation": {
                    "ok": False,
                    "issues": ["in-progress texture kit has generated files but no registered kit JSON"],
                },
                "inProgress": True,
                "generatedStateCount": len(partial_files),
                "stateSheetCount": state_sheet_count,
                "workPath": _rel(root, kit_dir(root) / safe_name) if (kit_dir(root) / safe_name).exists() else "",
                "textureDir": _rel(root, ui_texture_dir(root, safe_name)) if ui_texture_dir(root, safe_name).exists() else "",
            }
        )
    return {"kits": items}


def _collect_texture_kit_local_files(root: Path, kit: dict[str, Any]) -> set[Path]:
    files: set[Path] = set()
    textures = kit.get("textures") if isinstance(kit.get("textures"), dict) else {}
    for entry in textures.values():
        states = entry.get("states") if isinstance(entry, dict) and isinstance(entry.get("states"), dict) else {}
        for state_data in states.values():
            if not isinstance(state_data, dict) or not state_data.get("path"):
                continue
            target = _project_path(root, str(state_data.get("path") or ""))
            if target is None:
                continue
            target.relative_to(root)
            try:
                target.relative_to(_ui_root(root).resolve())
            except ValueError:
                continue
            files.add(target)
    generation = kit.get("generation") if isinstance(kit.get("generation"), dict) else {}
    for sheet in generation.get("stateSheets") or []:
        if isinstance(sheet, dict):
            sheet_path = _project_path(root, str(sheet.get("sheetPath") or ""))
            if sheet_path is not None:
                try:
                    sheet_path.relative_to(root)
                    sheet_path.relative_to(_ui_root(root).resolve())
                except ValueError:
                    continue
                files.add(sheet_path)
    for page in generation.get("atlasPages") or []:
        if isinstance(page, dict):
            for key in ("atlasPath", "guidePath", "metadataPath"):
                value = str(page.get(key) or "")
                if not value:
                    continue
                page_path = _project_path(root, value)
                if page_path is not None:
                    try:
                        page_path.relative_to(root)
                        page_path.relative_to(_ui_root(root).resolve())
                    except ValueError:
                        continue
                    files.add(page_path)
    return files


def clear_texture_kit(project_root: Path, texture_kit_path: str = "", kit_name: str = "") -> dict[str, Any]:
    root = project_root.resolve()
    kit_file: Path | None = None
    kit: dict[str, Any] = {}
    if texture_kit_path:
        kit_file = _project_path(root, texture_kit_path)
        if kit_file is None or not kit_file.exists() or not kit_file.is_file():
            raise ValueError(f"UI texture kit does not exist: {texture_kit_path}")
        kit_file.relative_to(root)
        try:
            kit_file.relative_to(kit_dir(root).resolve())
        except ValueError as exc:
            raise ValueError("UI texture kit must be inside the project ui/kits directory.") from exc
        if not kit_file.name.endswith(".uim-uikit.json"):
            raise ValueError("UI texture kit path must point to a .uim-uikit.json file.")
        kit = read_json(kit_file)
        kit_name = str(kit.get("kitName") or kit_file.stem.replace(".uim-uikit", ""))
    else:
        kit_name = str(kit_name or "").strip()
        if not kit_name:
            raise ValueError("UI texture kit clear requires texture_kit_path or kit_name.")
        candidate = kit_dir(root) / f"{_safe_name(kit_name, 'ui_kit')}.uim-uikit.json"
        if candidate.exists() and candidate.is_file():
            kit_file = candidate.resolve()
            kit_file.relative_to(root)
            kit = read_json(kit_file)
            kit_name = str(kit.get("kitName") or kit_name)
    safe_name = _safe_name(kit_name, "ui_kit")
    deleted_files: list[str] = []
    if kit:
        for target in sorted(_collect_texture_kit_local_files(root, kit)):
            if target.exists() and target.is_file():
                target.unlink()
                deleted_files.append(_rel(root, target))

    deleted_dirs: list[str] = []
    for directory in (ui_texture_dir(root, kit_name), ui_kit_work_dir(root, kit_name), _ui_root(root) / "textures" / safe_name, kit_dir(root) / safe_name):
        try:
            directory.relative_to(root)
        except ValueError:
            continue
        if directory.exists() and directory.is_dir():
            shutil.rmtree(directory)
            deleted_dirs.append(_rel(root, directory))

    deleted_config = ""
    if kit_file is not None and kit_file.exists():
        deleted_config = _rel(root, kit_file)
        kit_file.unlink()
    return {
        "deleted": deleted_config,
        "kitName": kit_name,
        "deletedFiles": sorted(set(deleted_files)),
        "deletedDirs": sorted(set(deleted_dirs)),
    }


def validate_texture_kit(kit: dict[str, Any]) -> dict[str, Any]:
    textures = kit.get("textures") if isinstance(kit.get("textures"), dict) else {}
    issues = []
    warnings = []
    for token, entry in textures.items():
        states = entry.get("states") if isinstance(entry, dict) and isinstance(entry.get("states"), dict) else {}
        if not states:
            issues.append(f"{token}: missing states")
        for state, state_data in states.items():
            if not isinstance(state_data, dict) or not (state_data.get("path") or state_data.get("unrealPath")):
                issues.append(f"{token}.{state}: missing path or unrealPath")
    generation = kit.get("generation") if isinstance(kit.get("generation"), dict) else {}
    for issue in generation.get("qualityIssues") or []:
        warnings.append(str(issue))
    return {"ok": len(issues) == 0, "issues": issues, "warnings": warnings}


def _effective_style_token(node: dict[str, Any], textures: dict[str, Any]) -> str:
    node_type = str(node.get("type") or "")
    explicit_token = str(node.get("styleToken") or "").strip()
    if explicit_token and explicit_token in textures:
        return explicit_token
    if node_type == "text":
        return ""
    if explicit_token and node_type in {"panel", "image"}:
        try:
            width = float(node.get("width") or 0)
            height = float(node.get("height") or 0)
        except Exception:
            width = 0
            height = 0
        if width <= 0 or height <= 0 or width > 520 or height > 220:
            return ""
    fallback = DEFAULT_STYLE_TOKENS.get(node_type, "")
    return fallback if fallback in textures else explicit_token


def _collect_required_tokens(node: dict[str, Any], result: dict[str, set[str]], textures: dict[str, Any]) -> None:
    explicit_token = str(node.get("styleToken") or "").strip()
    node_type = str(node.get("type") or "")
    token = _effective_style_token(node, textures) if (explicit_token or node_type != "text") else ""
    if token:
        required = set(UI_TEXTURE_REQUIRED_STATES.get(node_type, ("normal",)))
        result.setdefault(token, set()).update(required)
    if not explicit_token:
        if node_type == "scroll":
            result.setdefault("scrollThumb", set()).update(("normal", "hover", "dragged", "disabled"))
        elif node_type == "slider":
            result.setdefault("sliderFill", set()).update(("normal", "disabled"))
            result.setdefault("sliderThumb", set()).update(("normal", "hover", "disabled"))
        elif node_type == "dropdown":
            result.setdefault("dropdownArrow", set()).update(("normal", "open", "disabled"))
            result.setdefault("dropdownOption", set()).update(("normal", "hover", "selected"))
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _collect_required_tokens(child, result, textures)


def validate_structure_with_kit(structure: dict[str, Any], kit: dict[str, Any]) -> dict[str, Any]:
    required: dict[str, set[str]] = {}
    textures = kit.get("textures") if isinstance(kit.get("textures"), dict) else {}
    root = structure.get("root")
    if isinstance(root, dict):
        _collect_required_tokens(root, required, textures)
    missing = []
    for token, states in sorted(required.items()):
        actual = textures.get(token, {}).get("states", {}) if isinstance(textures.get(token), dict) else {}
        for state in sorted(states):
            if state not in actual:
                missing.append({"token": token, "state": state})
    return {"ok": len(missing) == 0, "missing": missing, "required": {token: sorted(states) for token, states in required.items()}}


def _state_output_path(root: Path, kit_name: str, token: str, state: str) -> Path:
    return ui_texture_dir(root, kit_name) / f"{_safe_name(token)}_{_safe_name(state)}.png"


def _ui_texture_file_quality(path: Path, target_size: tuple[int, int], chroma_key: Any = None, token: str = "") -> dict[str, Any]:
    Image, _, _ = _require_pillow()
    if not path.exists() or not path.is_file():
        return {"ok": False, "reason": "missing"}
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
    except Exception as exc:
        return {"ok": False, "reason": f"unreadable: {exc}"}
    report = _ui_texture_quality_report(rgba, token, target_size, chroma_key)
    if not report["ok"]:
        return {"ok": False, "reason": "; ".join(report["issues"])}
    return report


def _item_generated_files_from_existing_outputs(root: Path, kit_name: str, item: dict[str, Any], chroma_key: Any = None) -> list[dict[str, Any]]:
    files = _item_existing_state_files(root, kit_name, item, chroma_key)
    expected_count = len(item.get("states") or [])
    return files if expected_count > 0 and len(files) == expected_count else []


def _item_existing_state_files(root: Path, kit_name: str, item: dict[str, Any], chroma_key: Any = None) -> list[dict[str, Any]]:
    token = str(item.get("token") or "uiTexture")
    files = []
    target_size = _texture_target_size(item)
    for state in item.get("states") or []:
        state_name = str(state)
        output = _state_output_path(root, kit_name, token, state_name)
        if not _ui_texture_file_quality(output, target_size, chroma_key, token)["ok"]:
            continue
        files.append({"token": token, "state": state_name, "path": _rel(root, output)})
    return files


def _existing_texture_kit_partial_files(project_root: Path, kit_name: str, widget_tokens: list[dict[str, Any]] | None = None, coverage: str = "default_full", chroma_key: Any = None) -> list[dict[str, Any]]:
    root = project_root.resolve()
    files: list[dict[str, Any]] = []
    for item in _normalize_texture_catalog(widget_tokens, coverage):
        files.extend(_item_existing_state_files(root, kit_name, item, chroma_key))
    return files


def _existing_texture_kit_files(project_root: Path, kit_name: str, widget_tokens: list[dict[str, Any]] | None = None, coverage: str = "default_full", chroma_key: Any = None) -> list[dict[str, Any]]:
    root = project_root.resolve()
    files: list[dict[str, Any]] = []
    for item in _normalize_texture_catalog(widget_tokens, coverage):
        files.extend(_item_generated_files_from_existing_outputs(root, kit_name, item, chroma_key))
    return files


def _tokens_from_state_sheet_dir(state_sheet_dir: Path) -> set[str]:
    if not state_sheet_dir.exists() or not state_sheet_dir.is_dir():
        return set()
    by_safe_token = {_safe_name(item["token"]): str(item["token"]) for item in default_texture_catalog()}
    tokens: set[str] = set()
    for path in state_sheet_dir.glob("*_states.png"):
        safe_token = path.stem.removesuffix("_states")
        tokens.add(by_safe_token.get(safe_token, safe_token))
    return tokens


def migrate_texture_kit_from_existing_outputs(
    project_root: Path,
    kit_name: str,
    widget_tokens: list[dict[str, Any]] | None = None,
    content_path: str = "/Game/UIM/UI",
    coverage: str = "default_full",
    chroma_key: Any = None,
) -> dict[str, Any]:
    files = _existing_texture_kit_files(project_root, kit_name, widget_tokens, coverage, chroma_key)
    if not files:
        raise ValueError(f"No completed UI texture files were found for kit: {kit_name}")
    generation = {
        "mode": "migrated_existing_outputs",
        "coverage": coverage,
        "slotCatalogVersion": UI_ATLAS_CATALOG_VERSION,
        "sourceGenerationSize": UI_TEXTURE_GENERATION_SIZE,
        "resumedFromExistingOutputs": True,
        "migratedAt": _now(),
    }
    return register_texture_kit(project_root, kit_name, files, content_path=content_path, generation=generation)


def _python_literal(value: Any) -> str:
    return repr(value)


def _unreal_import_script(structure: dict[str, Any], kit: dict[str, Any], content_path: str, widget_path: str, result_path: str) -> str:
    return f'''import asyncio
import json
import sys
import traceback
import unreal
from toolset_registry._registry_interface import execute_tool as _execute_toolset

STRUCTURE = {_python_literal(structure)}
TEXTURE_KIT = {_python_literal(kit)}
CONTENT_PATH = {content_path!r}
WIDGET_PATH = {widget_path!r}
RESULT_PATH = {result_path!r}
DEFAULT_STYLE_TOKENS = {_python_literal(DEFAULT_STYLE_TOKENS)}
BOX_STYLE_TOKENS = {_python_literal(sorted(BOX_STYLE_TOKENS))}

def _write_uim_result(payload):
    try:
        with open(RESULT_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        unreal.log_error(f"UnrealImageMaker failed to write result file: {{exc}}")
    unreal.log("UIM_RESULT " + json.dumps(payload, ensure_ascii=False))

def _uim_excepthook(exc_type, exc_value, exc_tb):
    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _write_uim_result({{
        "ok": False,
        "widgetPath": WIDGET_PATH,
        "error": str(exc_value),
        "traceback": error_text,
    }})
    unreal.log_error("UnrealImageMaker UMG export failed: " + str(exc_value))

sys.excepthook = _uim_excepthook

def _color(hex_value, fallback=(1, 1, 1, 1)):
    if not hex_value or not isinstance(hex_value, str) or not hex_value.startswith("#"):
        return unreal.LinearColor(*fallback)
    raw = hex_value[1:]
    if len(raw) == 6:
        raw += "ff"
    try:
        r = int(raw[0:2], 16) / 255.0
        g = int(raw[2:4], 16) / 255.0
        b = int(raw[4:6], 16) / 255.0
        a = int(raw[6:8], 16) / 255.0
        return unreal.LinearColor(r, g, b, a)
    except Exception:
        return unreal.LinearColor(*fallback)

def _import_textures():
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    tasks = []
    imported = {{}}
    for token, entry in TEXTURE_KIT.get("textures", {{}}).items():
        for state, state_data in entry.get("states", {{}}).items():
            unreal_path = state_data.get("unrealPath", "")
            if unreal_path:
                asset = unreal.load_asset(unreal_path)
                if asset:
                    imported[(token, state)] = asset
                    continue
            source = state_data.get("path", "")
            if not source:
                continue
            task = unreal.AssetImportTask()
            task.filename = source if ":" in source or source.startswith("/") else source
            task.destination_path = TEXTURE_KIT.get("contentPath") or CONTENT_PATH
            task.automated = True
            task.save = True
            task.replace_existing = True
            tasks.append((token, state, task))
    asset_tools.import_asset_tasks([task for _, _, task in tasks])
    for token, state, task in tasks:
        if task.imported_object_paths:
            imported[(token, state)] = unreal.load_asset(task.imported_object_paths[0])
    return imported

TEXTURES = _import_textures()

def _style_token(node, fallback_type=None):
    node_type = fallback_type or node.get("type", "")
    explicit = node.get("styleToken") or ""
    textures = TEXTURE_KIT.get("textures", {{}})
    if explicit and explicit in textures:
        return explicit
    if node_type == "text":
        return ""
    if explicit and node_type in ("panel", "image"):
        try:
            width = float(node.get("width") or 0)
            height = float(node.get("height") or 0)
        except Exception:
            width = 0
            height = 0
        if width <= 0 or height <= 0 or width > 520 or height > 220:
            return ""
    fallback = DEFAULT_STYLE_TOKENS.get(node_type, "")
    return fallback if fallback in textures else explicit

def _style_token_for_texture(node, fallback_type=None, explicit_token=None):
    token = explicit_token or _style_token(node, fallback_type)
    if not token:
        return ""
    return token

def _texture_for(node, state="normal", fallback_type=None, explicit_token=None):
    token = _style_token_for_texture(node, fallback_type, explicit_token)
    return (TEXTURES.get((token, state)) or TEXTURES.get((token, "normal"))) if token else None

def _brush_from_texture(texture, width=64, height=64, draw_as="image", margin=0.25):
    brush = unreal.SlateBrush()
    try:
        brush.set_editor_property("resource_object", texture)
        try:
            image_size = unreal.DeprecateSlateVector2D()
            image_size.set_editor_property("x", float(width))
            image_size.set_editor_property("y", float(height))
        except Exception:
            try:
                image_size = unreal.Vector2f(float(width), float(height))
            except Exception:
                image_size = unreal.Vector2D(float(width), float(height))
        brush.set_editor_property("image_size", image_size)
        if draw_as == "box":
            brush.set_editor_property("draw_as", unreal.SlateBrushDrawType.BOX)
            brush.set_editor_property("margin", unreal.Margin(float(margin), float(margin), float(margin), float(margin)))
        else:
            brush.set_editor_property("draw_as", unreal.SlateBrushDrawType.IMAGE)
    except Exception as exc:
        unreal.log_warning(f"Failed to create SlateBrush: {{exc}}")
    return brush

def _draw_as_for_token(token):
    return "box" if token in BOX_STYLE_TOKENS else "image"

def _apply_brush(widget, brush, texture=None):
    if hasattr(widget, "set_brush"):
        try:
            widget.set_brush(brush)
            return True
        except Exception:
            pass
    try:
        widget.set_editor_property("brush", brush)
        return True
    except Exception:
        pass
    if texture and hasattr(widget, "set_brush_from_texture"):
        try:
            widget.set_brush_from_texture(texture, False)
            return True
        except Exception:
            pass
    return False

def _apply_button_style(button, node):
    token = _style_token(node, "button")
    if not token:
        return
    try:
        style = unreal.ButtonStyle()
        state_map = {{
            "normal": "normal",
            "hover": "hovered",
            "pressed": "pressed",
            "disabled": "disabled",
        }}
        for source_state, property_name in state_map.items():
            texture = TEXTURES.get((token, source_state)) or TEXTURES.get((token, "normal"))
            if texture:
                style.set_editor_property(property_name, _brush_from_texture(texture, node.get("width", 64), node.get("height", 64), draw_as=_draw_as_for_token(token)))
        button.set_editor_property("widget_style", style)
    except Exception as exc:
        unreal.log_warning(f"Button style setup failed for {{node.get('name')}}: {{exc}}")

package_path, asset_name = WIDGET_PATH.rsplit("/", 1)
asset_exists_before_create = unreal.EditorAssetLibrary.does_asset_exist(WIDGET_PATH)
widget_bp = unreal.load_asset(WIDGET_PATH) if asset_exists_before_create else None
if asset_exists_before_create:
    if widget_bp:
        existing_class = widget_bp.get_class().get_name()
        if existing_class != "WidgetBlueprint":
            raise RuntimeError(f"Existing asset at {{WIDGET_PATH}} is {{existing_class}}, expected WidgetBlueprint")
    if not unreal.EditorAssetLibrary.delete_asset(WIDGET_PATH):
        raise RuntimeError("Failed to replace existing Widget Blueprint: " + WIDGET_PATH)
    try:
        unreal.SystemLibrary.collect_garbage()
    except Exception:
        pass
    widget_bp = None
def _toolset_call(tool_name, payload):
    return asyncio.run(_execute_toolset("UMGToolSet.UMGToolSet", tool_name, payload))

def _class_ref(widget_class):
    try:
        return {{"refPath": widget_class.static_class().get_path_name()}}
    except Exception:
        pass
    name = getattr(widget_class, "__name__", str(widget_class))
    if name.startswith("unreal."):
        name = name.split(".", 1)[1]
    return {{"refPath": "/Script/UMG." + name}}

def _object_ref(obj):
    if not obj or obj == "None":
        return None
    if isinstance(obj, dict):
        return obj
    return {{"refPath": obj.get_path_name()}}

def _load_ref(ref):
    if not ref or ref == "None":
        return None
    ref_path = ref.get("refPath") if isinstance(ref, dict) else str(ref)
    if not ref_path or ref_path == "None":
        return None
    return unreal.load_object(None, ref_path)

if not getattr(unreal, "ToolsetRegistry", None) or not unreal.ToolsetRegistry.is_toolset_registered("UMGToolSet.UMGToolSet"):
    raise RuntimeError("UMGToolSet.UMGToolSet is unavailable. UE 5.8 ToolsetRegistry/UMGToolSet plugins are required for headless Widget Blueprint export.")
created = _toolset_call("CreateWidgetBlueprint", {{
    "folderPath": package_path,
    "assetName": asset_name,
    "parentClass": {{"refPath": "/Script/UMG.UserWidget"}},
}})
widget_bp = _load_ref((created.get("returnValue") or {{}}))
if not widget_bp:
    widget_bp = unreal.load_asset(WIDGET_PATH)
if not widget_bp:
    raise RuntimeError("Failed to create Widget Blueprint through UMGToolSet.UMGToolSet: " + WIDGET_PATH)
if widget_bp.get_class().get_name() != "WidgetBlueprint":
    raise RuntimeError(f"Created asset at {{WIDGET_PATH}} is {{widget_bp.get_class().get_name()}}, expected WidgetBlueprint")

def _struct_value(data, *names):
    if isinstance(data, dict):
        for name in names:
            if name in data:
                return data[name]
            lower_name = name[:1].lower() + name[1:]
            if lower_name in data:
                return data[lower_name]
        return None
    for name in names:
        try:
            return data.get_editor_property(name)
        except Exception:
            pass
        try:
            return getattr(data, name)
        except Exception:
            pass
    return None

def _add_widget(widget_class, name, parent=None):
    payload = {{
        "widgetBlueprint": _object_ref(widget_bp),
        "widgetClass": _class_ref(widget_class),
        "widgetDisplayName": str(name),
        "childIndex": -1,
    }}
    parent_ref = _object_ref(parent)
    if parent_ref:
        payload["parentWidget"] = parent_ref
    result = _toolset_call("AddWidget", payload)
    info = result.get("returnValue") or {{}}
    widget = _load_ref(_struct_value(info, "Widget", "widget"))
    slot = _load_ref(_struct_value(info, "Slot", "slot"))
    if not widget:
        raise RuntimeError(f"UMGToolSet failed to add widget {{name}}")
    return widget, slot

root_canvas, root_slot = _add_widget(unreal.CanvasPanel, "RootCanvas", None)

def _widget_tree(widget_blueprint):
    try:
        tree = unreal.find_object(widget_blueprint, "WidgetTree")
        if tree:
            return tree
    except Exception:
        pass
    return None

tree = _widget_tree(widget_bp)

def _dict_value(data, key, fallback):
    return data.get(key, fallback) if isinstance(data, dict) else fallback

def _make_anchors(min_x, min_y, max_x, max_y):
    try:
        return unreal.Anchors(float(min_x), float(min_y), float(max_x), float(max_y))
    except Exception:
        anchors = unreal.Anchors()
        try:
            anchors.minimum = unreal.Vector2D(float(min_x), float(min_y))
            anchors.maximum = unreal.Vector2D(float(max_x), float(max_y))
        except Exception:
            pass
        return anchors

def _slot(widget, node, slot=None):
    if slot is None:
        try:
            slot = widget.slot
        except Exception:
            slot = None
    if not slot:
        return
    anchors = node.get("anchors") if isinstance(node.get("anchors"), dict) else {{}}
    anchor_min = _dict_value(anchors, "minimum", {{}})
    anchor_max = _dict_value(anchors, "maximum", {{}})
    offsets = node.get("offsets") if isinstance(node.get("offsets"), dict) else {{}}
    alignment = node.get("alignment") if isinstance(node.get("alignment"), dict) else {{}}
    min_x = _dict_value(anchor_min, "x", 0.0)
    min_y = _dict_value(anchor_min, "y", 0.0)
    max_x = _dict_value(anchor_max, "x", min_x)
    max_y = _dict_value(anchor_max, "y", min_y)
    left = _dict_value(offsets, "left", node.get("x", 0))
    top = _dict_value(offsets, "top", node.get("y", 0))
    right = _dict_value(offsets, "right", node.get("width", 0))
    bottom = _dict_value(offsets, "bottom", node.get("height", 0))
    align_x = _dict_value(alignment, "x", 0.0)
    align_y = _dict_value(alignment, "y", 0.0)
    if hasattr(slot, "set_anchors"):
        try:
            slot.set_anchors(_make_anchors(min_x, min_y, max_x, max_y))
        except Exception as exc:
            unreal.log_warning(f"Anchor setup failed for {{node.get('name')}}: {{exc}}")
    if hasattr(slot, "set_alignment"):
        try:
            slot.set_alignment(unreal.Vector2D(float(align_x), float(align_y)))
        except Exception:
            pass
    if hasattr(slot, "set_offsets"):
        try:
            slot.set_offsets(unreal.Margin(float(left), float(top), float(right), float(bottom)))
            return
        except Exception as exc:
            unreal.log_warning(f"Offset setup failed for {{node.get('name')}}: {{exc}}")
    if hasattr(slot, "set_position"):
        slot.set_position(unreal.Vector2D(float(node.get("x", 0)), float(node.get("y", 0))))
    if hasattr(slot, "set_size"):
        slot.set_size(unreal.Vector2D(float(node.get("width", 0)), float(node.get("height", 0))))

def _set_text(widget, node):
    try:
        widget.set_text(str(node.get("text", "")))
        widget.set_color_and_opacity(unreal.SlateColor(_color(node.get("fontColor"), (1, 1, 1, 1))))
        widget.set_font(unreal.SlateFontInfo(size=int(node.get("fontSize", 16))))
    except Exception as exc:
        unreal.log_warning(f"Text setup failed for {{node.get('name')}}: {{exc}}")

def _apply_texture(widget, node, state="normal"):
    token = _style_token_for_texture(node)
    texture = _texture_for(node, state)
    if texture:
        brush = _brush_from_texture(texture, node.get("width", 64), node.get("height", 64), draw_as=_draw_as_for_token(token))
        if _apply_brush(widget, brush, texture):
            return
    elif hasattr(widget, "set_color_and_opacity"):
        widget.set_color_and_opacity(_color(node.get("color")))
    elif hasattr(widget, "set_brush_color"):
        widget.set_brush_color(_color(node.get("color")))

def _skin_background(parent, node, token=None, state="normal", suffix="Skin"):
    texture = _texture_for(node, state, explicit_token=token)
    if not texture:
        return None
    skin, skin_slot = _add_widget(unreal.Image, str(node.get("name", "Widget")) + suffix, parent)
    try:
        brush = _brush_from_texture(texture, node.get("width", 64), node.get("height", 64), draw_as=_draw_as_for_token(token or _style_token(node)))
        _apply_brush(skin, brush, texture)
    except Exception:
        pass
    _slot(skin, node, skin_slot)
    return skin

def _create(parent, node):
    node_type = node.get("type", "panel")
    name = node.get("name", "Widget")
    slot = None
    if node_type == "screen":
        widget = parent
    elif node_type in ("panel", "image"):
        widget, slot = _add_widget(unreal.Image, name, parent)
        _apply_texture(widget, node)
    elif node_type == "text":
        if node.get("styleToken"):
            _skin_background(parent, node, token=_style_token(node, "text"), suffix="Plate")
        widget, slot = _add_widget(unreal.TextBlock, name, parent)
        _set_text(widget, node)
    elif node_type == "button":
        widget, slot = _add_widget(unreal.Button, name, parent)
        _apply_button_style(widget, node)
    elif node_type == "input":
        _skin_background(parent, node, token=_style_token(node, "input"))
        widget, slot = _add_widget(unreal.EditableTextBox, name, parent)
        try:
            widget.set_text(str(node.get("text", "")))
        except Exception:
            pass
    elif node_type == "scroll":
        _skin_background(parent, node, token="scrollTrack")
        widget, slot = _add_widget(unreal.ScrollBox, name, parent)
    elif node_type == "checkbox":
        _skin_background(parent, node, token="checkboxBox", state="checked" if node.get("checked") else "unchecked")
        widget, slot = _add_widget(unreal.CheckBox, name, parent)
        try:
            widget.set_is_checked(bool(node.get("checked")))
        except Exception:
            pass
    elif node_type == "slider":
        _skin_background(parent, node, token="sliderTrack")
        _skin_background(parent, node, token="sliderFill", suffix="Fill")
        _skin_background(parent, node, token="sliderThumb", suffix="Thumb")
        widget, slot = _add_widget(unreal.Slider, name, parent)
        try:
            widget.set_value(float(node.get("value", 0.5)))
        except Exception:
            pass
    elif node_type == "dropdown":
        _skin_background(parent, node, token="dropdownBox")
        _skin_background(parent, node, token="dropdownArrow", suffix="Arrow")
        widget, slot = _add_widget(unreal.ComboBoxString, name, parent)
        for option in node.get("options", []):
            try:
                widget.add_option(str(option))
            except Exception:
                pass
    else:
        widget, slot = _add_widget(unreal.Image, name, parent)
    if widget is not parent:
        _slot(widget, node, slot)
    for child in node.get("children", []):
        child_parent = widget if node_type in ("screen", "scroll") and hasattr(widget, "add_child") else parent
        _create(child_parent, child)
    return widget

_create(root_canvas, STRUCTURE["root"])
try:
    widget_bp.modify()
except Exception:
    pass
try:
    widget_bp.mark_package_dirty()
except Exception:
    pass
try:
    unreal.BlueprintEditorLibrary.compile_blueprint(widget_bp)
except Exception as exc:
    unreal.log_warning(f"Widget Blueprint compile failed for {{WIDGET_PATH}}: {{exc}}")
try:
    unreal.EditorAssetLibrary.save_loaded_asset(widget_bp, only_if_is_dirty=False)
except Exception:
    unreal.EditorAssetLibrary.save_asset(WIDGET_PATH, only_if_is_dirty=False)
saved_widget = unreal.load_asset(WIDGET_PATH)
saved_class = saved_widget.get_class().get_name() if saved_widget else ""
exists = unreal.EditorAssetLibrary.does_asset_exist(WIDGET_PATH)
if not exists or not saved_widget:
    raise RuntimeError("Widget Blueprint was not saved: " + WIDGET_PATH)
if saved_class != "WidgetBlueprint":
    raise RuntimeError(f"Saved asset at {{WIDGET_PATH}} is {{saved_class}}, expected WidgetBlueprint")
_write_uim_result({{
    "ok": True,
    "widgetPath": WIDGET_PATH,
    "assetName": asset_name,
    "packagePath": package_path,
    "assetClass": saved_class,
    "exists": bool(exists),
}})
unreal.log("UnrealImageMaker UMG export complete: " + WIDGET_PATH)
'''


def export_game_ui_umg(project_root: Path, screen_name: str, structure_path: str, texture_kit_path: str, content_path: str = "/Game/UIM/UI") -> dict[str, Any]:
    root = project_root.resolve()
    structure_file = _project_path(root, structure_path)
    kit_file = _project_path(root, texture_kit_path)
    if structure_file is None or not structure_file.exists():
        raise ValueError(f"UI structure JSON does not exist: {structure_path}")
    if kit_file is None or not kit_file.exists():
        raise ValueError(f"UI texture kit does not exist: {texture_kit_path}")
    structure_file.relative_to(root)
    kit_file.relative_to(root)
    structure = read_json(structure_file)
    kit = read_json(kit_file)
    validation = validate_structure_with_kit(structure, kit)
    if not validation["ok"]:
        raise ValueError(f"Texture kit is missing required states: {validation['missing']}")
    exported_kit = json.loads(json.dumps(kit))
    textures = exported_kit.get("textures") if isinstance(exported_kit.get("textures"), dict) else {}
    for entry in textures.values():
        states = entry.get("states") if isinstance(entry, dict) and isinstance(entry.get("states"), dict) else {}
        for state_data in states.values():
            if isinstance(state_data, dict) and state_data.get("path"):
                state_data["path"] = str((root / state_data["path"]).resolve())
    asset_name = _safe_name(screen_name)
    widget_path = f"{content_path.rstrip('/')}/WBP_{asset_name}"
    output = root / "exports" / "unreal" / f"{asset_name}_umg_import.py"
    result_output = root / "exports" / "unreal" / f"{asset_name}_umg_import_result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_unreal_import_script(structure, exported_kit, content_path, widget_path, str(result_output)), encoding="utf-8", newline="\n")
    return {
        "mode": "python_script",
        "script": str(output),
        "resultFile": str(result_output),
        "widgetPath": widget_path,
        "validation": validation,
        "runInUnreal": "Enable the Python Editor Script Plugin, then run this script from Unreal Editor's Python console or command line.",
    }


def _resolve_unreal_cmd_editor(editor_path: str) -> Path:
    editor = Path(editor_path).expanduser().resolve()
    if not editor.exists() or not editor.is_file():
        raise ValueError(f"Unreal Editor executable does not exist: {editor_path}")
    name = editor.name.lower()
    if name == "unrealeditor.exe":
        cmd_editor = editor.with_name("UnrealEditor-Cmd.exe")
        if cmd_editor.exists() and cmd_editor.is_file():
            return cmd_editor.resolve()
        raise ValueError("Headless UMG export requires UnrealEditor-Cmd.exe. The selected path points to UnrealEditor.exe, and UnrealEditor-Cmd.exe was not found next to it.")
    if name != "unrealeditor-cmd.exe":
        raise ValueError("Headless UMG export requires selecting UnrealEditor-Cmd.exe, not the GUI UnrealEditor executable.")
    return editor


def _extract_unreal_error_lines(stdout: str, stderr: str, limit: int = 40) -> list[str]:
    markers = (
        "error",
        "exception",
        "traceback",
        "runtimeerror",
        "fatal",
        "failed",
        "失败",
        "错误",
    )
    ignored = (
        "LogEOSSDK",
        "LogEOSShared",
        "LogExit",
        "LogHttpServerModule",
        "Failed to load 'aqProf.dll'",
        "Failed to load 'VtuneApi.dll'",
        "Failed to load 'VtuneApi32e.dll'",
        "Failed to load 'WinPixGpuCapturer.dll'",
        "Failed to load 'Wintab32.dll'",
        "PIX capture plugin failed to initialize",
        "Failed to SetupSDK for platform",
        "UE::UnifiedErrorTest",
        "FError that has been invalidated",
        "FError that has been moved from",
        "LogAutomationTest: Error: Condition failed",
        "HttpListener unable to bind",
        "MapCheck:",
        "LogInterchangeEngine:",
        "LogFileHelpers: Saving Package:",
        "OBJ SavePackage:",
        "Cmd: OBJ SAVEPACKAGE",
        "LogSavePackage: Moving",
        "AssetCheck:",
        "LogContentValidation:",
    )
    lines: list[str] = []
    for source_name, text in (("stdout", stdout or ""), ("stderr", stderr or "")):
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if any(skip in line for skip in ignored):
                continue
            if any(marker in lowered for marker in markers):
                lines.append(f"{source_name}: {line}")
    seen: set[str] = set()
    unique = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
    return unique[-limit:]


def _run_unreal_python_script(editor_path: str, project_path: str, script_path: Path, result_path: Path | None = None, timeout_seconds: int = 1800) -> dict[str, Any]:
    editor = _resolve_unreal_cmd_editor(editor_path)
    project = Path(project_path).expanduser().resolve()
    if not project.exists() or not project.is_file() or project.suffix.lower() != ".uproject":
        raise ValueError(f"Unreal project file does not exist: {project_path}")
    if result_path and result_path.exists():
        result_path.unlink()
    args = [
        str(editor),
        str(project),
        f"-ExecutePythonScript={script_path.resolve()}",
        "-unattended",
        "-nop4",
        "-nullrhi",
        "-nosplash",
        "-NoSound",
        "-NoLoadingScreen",
        "-stdout",
        "-FullStdOutLogOutput",
    ]
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_seconds, check=False)
    detected_errors = _extract_unreal_error_lines(result.stdout, result.stderr)
    script_result: dict[str, Any] | None = None
    result_error = ""
    if result_path:
        if result_path.exists():
            try:
                script_result = read_json(result_path)
            except Exception as exc:
                result_error = f"Failed to read Unreal export result file: {exc}"
        else:
            result_error = f"Unreal export result file was not written: {result_path}"
    script_ok = bool(script_result.get("ok")) if isinstance(script_result, dict) else False
    ok = result.returncode == 0 and (script_ok if result_path else True)
    return {
        "ok": ok,
        "returnCode": result.returncode,
        "command": args,
        "stdout": result.stdout[-8000:],
        "stderr": result.stderr[-8000:],
        "detectedErrors": detected_errors,
        "scriptResult": script_result,
        "error": "" if ok else (result_error or (script_result.get("error") if isinstance(script_result, dict) else "") or "Unreal Python script did not report a successful UMG export."),
    }


def export_game_ui_umg_and_maybe_run(
    project_root: Path,
    screen_name: str,
    structure_path: str,
    texture_kit_path: str,
    content_path: str = "/Game/UIM/UI",
    *,
    execute_in_unreal: bool = False,
    unreal_editor_path: str = "",
    unreal_project_path: str = "",
) -> dict[str, Any]:
    result = export_game_ui_umg(project_root, screen_name, structure_path, texture_kit_path, content_path)
    if not execute_in_unreal:
        return result
    if not unreal_editor_path.strip() or not unreal_project_path.strip():
        return {
            **result,
            "mode": "python_script",
            "execution": {
                "ok": False,
                "configured": False,
                "error": "Unreal Editor path and .uproject path are required to execute the script automatically.",
            },
        }
    try:
        execution = _run_unreal_python_script(
            unreal_editor_path,
            unreal_project_path,
            Path(str(result["script"])),
            Path(str(result.get("resultFile") or "")) if result.get("resultFile") else None,
        )
    except Exception as exc:
        return {
            **result,
            "mode": "python_script",
            "execution": {
                "ok": False,
                "configured": True,
                "error": str(exc),
            },
        }
    return {
        **result,
        "mode": "executed" if execution.get("ok") else "python_script",
        "execution": {
            "configured": True,
            **execution,
        },
    }


def generate_texture_kit(
    project_root: Path,
    kit_name: str,
    concept_path: str | None,
    widget_tokens: list[dict[str, Any]] | None,
    provider: str = "openai_api",
    content_path: str = "/Game/UIM/UI",
    coverage: str = "default_full",
    mask_mode: str = "hybrid",
    decontaminate_edges: bool = True,
    debug_artifacts: bool = False,
    max_concurrency: int = 4,
    chroma_key: Any = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    Image, _, _ = _require_pillow()
    chroma_rgb = _normalize_chroma_key(chroma_key)
    if coverage not in {"default_full", "custom"}:
        raise ValueError(f"Unsupported UI texture kit coverage: {coverage}")
    catalog = _normalize_texture_catalog(widget_tokens, coverage)
    worker_count = max(1, min(int(max_concurrency or 1), len(catalog) or 1, 4))
    if progress:
        progress(f"UI 贴图组：准备生成 {len(catalog)} 个控件组，并发 {worker_count}")
    concept = _project_path(root, concept_path)
    def generate_item(item_index: int, item: dict[str, Any]) -> dict[str, Any]:
        token = str(item.get("token") or "uiTexture")
        guide = _create_state_sheet_guide(root, kit_name, item, chroma_rgb)
        source = ui_kit_work_dir(root, kit_name) / "state_sheets" / f"{_safe_name(token)}_states.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        guide_path = root / guide["guidePath"]
        reference_paths = [path for path in (concept, guide_path) if path]
        state_count = len(item.get("states") or [])
        existing_files = _item_generated_files_from_existing_outputs(root, kit_name, item, chroma_rgb)
        if len(existing_files) == state_count and state_count > 0:
            if progress:
                progress(f"UI 贴图组：跳过 {item_index + 1}/{len(catalog)} {token}，状态贴图已完整")
            slot_outputs: dict[tuple[str, str], Path] = {}
            slots: list[dict[str, Any]] = []
            for slot in guide["slots"]:
                state = str(slot["state"])
                output = _state_output_path(root, kit_name, token, state)
                slot_record = dict(slot)
                slot_record["generatedSheetPath"] = _rel(root, source) if source.exists() else ""
                slot_record["outputPath"] = _rel(root, output)
                slot_record["resumeMode"] = "existing_outputs"
                slots.append(slot_record)
                slot_outputs[(token, state)] = output
            return {
                "index": item_index,
                "generatedFiles": existing_files,
                "cutoutReports": [{"token": token, "state": str(file["state"]), "report": {"mode": "skipped_existing_output"}} for file in existing_files],
                "stateSheet": {
                    "token": token,
                    "type": item.get("type") or "panel",
                    "states": list(item.get("states") or []),
                    "guidePath": guide["guidePath"],
                    "metadataPath": guide["metadataPath"],
                    "sheetPath": _rel(root, source) if source.exists() else "",
                    "model": "existing-output",
                    "provider": provider,
                    "providerBaseUrl": "",
                    "streamEvents": [],
                    "resumeMode": "existing_outputs",
                },
                "slots": slots,
                "slotOutputs": slot_outputs,
            }
        expected_outputs = [_state_output_path(root, kit_name, token, str(state)) for state in item.get("states") or []]
        if progress and any(path.exists() for path in expected_outputs):
            progress(f"UI 贴图组：重新生成 {item_index + 1}/{len(catalog)} {token}，旧状态贴图不完整或质量检查未通过")
        if progress:
            progress(f"UI 贴图组：开始 {item_index + 1}/{len(catalog)} {token}，{state_count} 个状态")
        if source.exists() and source.is_file():
            result_model = "existing-state-sheet"
            result_base_url = ""
            result_stream_events: list[str] = []
            if progress:
                progress(f"UI 贴图组：复用 {token} 已有状态图，只重跑拆分")
        else:
            result = _generate_image(_state_sheet_prompt(kit_name, item, guide, chroma_rgb), source, provider, size=UI_TEXTURE_GENERATION_SIZE, reference_paths=reference_paths)
            result_model = result.model
            result_base_url = result.base_url
            result_stream_events = result.stream_events or []
        sheet_record = {
            "token": token,
            "type": item.get("type") or "panel",
            "states": list(item.get("states") or []),
            "guidePath": guide["guidePath"],
            "metadataPath": guide["metadataPath"],
            "sheetPath": _rel(root, source),
            "model": result_model,
            "provider": provider,
            "providerBaseUrl": result_base_url,
            "streamEvents": result_stream_events,
            "resumeMode": "existing_state_sheet" if result_model == "existing-state-sheet" else "generated",
        }
        temp_dir = ui_kit_work_dir(root, kit_name) / "cutout_work" / f"token_{_safe_name(token)}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        generated_files: list[dict[str, Any]] = []
        cutout_reports: list[dict[str, Any]] = []
        slots: list[dict[str, Any]] = []
        slot_outputs: dict[tuple[str, str], Path] = {}
        with Image.open(source) as sheet_image:
            sheet = sheet_image.convert("RGBA")
            if sheet.size != UI_TEXTURE_STATE_SHEET_SIZE:
                sheet = sheet.resize(UI_TEXTURE_STATE_SHEET_SIZE, _lanczos_resample())
                if progress:
                    progress(f"UI 贴图组：{token} 输出尺寸已归一 {sheet_image.width}x{sheet_image.height}->{UI_TEXTURE_STATE_SHEET_SIZE[0]}x{UI_TEXTURE_STATE_SHEET_SIZE[1]}")
            detected_regions = _rembg_component_regions(sheet, temp_dir, token, guide["slots"], chroma_key=chroma_rgb)
            if progress:
                progress(f"UI 贴图组：{token} rembg 检测到 {len(detected_regions)}/{len(guide['slots'])} 个状态区域")
            for slot in guide["slots"]:
                state = str(slot["state"])
                detected_rect = detected_regions.get(state)
                rect, crop_mode = _state_slot_crop_rect(slot, detected_rect)
                target_size = (int(slot["targetSize"]["width"]), int(slot["targetSize"]["height"]))
                crop = sheet.crop((rect["x"], rect["y"], rect["x"] + rect["width"], rect["y"] + rect["height"]))
                output = ui_texture_dir(root, kit_name) / f"{_safe_name(token)}_{_safe_name(state)}.png"
                report = _cleanup_ui_crop(
                    crop,
                    output,
                    temp_dir,
                    mask_mode=mask_mode,
                    decontaminate_edges=decontaminate_edges,
                    debug_artifacts=debug_artifacts,
                    target_size=target_size,
                    chroma_key=chroma_rgb,
                    prefer_chroma_cutout=_transparent_center_token(token),
                )
                with Image.open(output) as texture_image:
                    quality = _ui_texture_quality_report(texture_image, token, target_size, chroma_rgb)
                report["quality"] = quality
                rel_output = _rel(root, output)
                generated_files.append({"token": token, "state": state, "path": rel_output, "quality": quality})
                cutout_reports.append({"token": token, "state": state, "report": report})
                slot_record = dict(slot)
                slot_record["detectedRect"] = detected_rect
                slot_record["cropRect"] = rect
                slot_record["cropMode"] = crop_mode
                slot_record["generatedSheetPath"] = _rel(root, source)
                slot_record["outputPath"] = rel_output
                slot_record["model"] = result_model
                slot_record["providerBaseUrl"] = result_base_url
                slots.append(slot_record)
                slot_outputs[(token, state)] = output
        if progress:
            progress(f"UI 贴图组：完成 {item_index + 1}/{len(catalog)} {token}，已拆出 {len(generated_files)} 张状态贴图")
        return {
            "index": item_index,
            "generatedFiles": generated_files,
            "cutoutReports": cutout_reports,
            "stateSheet": sheet_record,
            "slots": slots,
            "slotOutputs": slot_outputs,
        }

    item_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(generate_item, index, item) for index, item in enumerate(catalog)]
        for future in as_completed(futures):
            item_results.append(future.result())
    item_results.sort(key=lambda item: int(item["index"]))
    generated_files: list[dict[str, Any]] = []
    cutout_reports: list[dict[str, Any]] = []
    state_sheets: list[dict[str, Any]] = []
    all_slots: list[dict[str, Any]] = []
    slot_outputs: dict[tuple[str, str], Path] = {}
    for item in item_results:
        generated_files.extend(item["generatedFiles"])
        cutout_reports.extend(item["cutoutReports"])
        state_sheets.append(item["stateSheet"])
        all_slots.extend(item["slots"])
        slot_outputs.update(item["slotOutputs"])
    quality_reports = [
        {"token": report["token"], "state": report["state"], **dict(report.get("report", {}).get("quality") or {})}
        for report in cutout_reports
        if isinstance(report.get("report"), dict) and isinstance(report["report"].get("quality"), dict)
    ]
    quality_issues = [
        f"{report.get('token')}.{report.get('state')}: {issue}"
        for report in quality_reports
        for issue in (report.get("issues") or [])
    ]

    pages = []
    for page_index, page_slots in enumerate(_atlas_pages(all_slots)):
        page = _create_atlas_guide(root, kit_name, page_index, page_slots)
        page["generationMode"] = "per_token"
        page["provider"] = provider
        page["slots"] = [dict(slot) for slot in page["slots"]]
        page["atlasPath"] = _compose_local_texture_page(root, kit_name, page, slot_outputs)
        pages.append(page)
    if progress:
        progress(f"UI 贴图组：完成全部控件组，共 {len(generated_files)} 张状态贴图")
    generation = {
        "mode": "per_token",
        "coverage": coverage,
        "stateSheets": state_sheets,
        "atlasPages": pages,
        "slotCatalogVersion": UI_ATLAS_CATALOG_VERSION,
        "sourceGenerationSize": UI_TEXTURE_GENERATION_SIZE,
        "chromaKey": list(chroma_rgb),
        "chromaKeyHex": _hex_color(chroma_rgb),
        "maxConcurrency": worker_count,
        "maskMode": mask_mode,
        "decontaminateEdges": decontaminate_edges,
        "debugArtifacts": debug_artifacts,
        "cutoutReports": cutout_reports,
        "qualityReports": quality_reports,
        "qualityOk": len(quality_issues) == 0,
        "qualityIssues": quality_issues,
    }
    return register_texture_kit(root, kit_name, generated_files, content_path=content_path, generation=generation)
