from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .image_processing import _require_pillow

PixelMaskMode = Literal["hybrid", "rembg", "classic"]
PixelRestoreMode = Literal["none", "clean", "safe", "pixel"]


@dataclass(slots=True)
class PixelDependencyStatus:
    id: str
    label: str
    available: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "available": self.available, "detail": self.detail}


def _require_mask_dependencies():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from scipy import ndimage  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Hybrid Mask 需要安装 OpenCV/scipy：请安装 backend requirements 中的 opencv-python-headless 和 scipy。") from exc
    return cv2, np, ndimage


def pixel_dependency_statuses() -> list[PixelDependencyStatus]:
    statuses: list[PixelDependencyStatus] = []
    for module_name, label in (("cv2", "OpenCV"), ("scipy", "scipy")):
        try:
            module = __import__(module_name)
            version = str(getattr(module, "__version__", "installed"))
            statuses.append(PixelDependencyStatus(module_name, label, True, version))
        except ImportError:
            statuses.append(PixelDependencyStatus(module_name, label, False, "未安装"))
    unfake = _find_unfake_executable()
    statuses.append(PixelDependencyStatus("unfake", "unfake CLI", bool(unfake), unfake or "未找到 unfake 命令"))
    return statuses


def _find_unfake_executable() -> str | None:
    for command in ("unfake", "unfake.exe"):
        found = shutil.which(command)
        if found:
            return found
    scripts_dir = Path(sys.executable).resolve().parent
    for name in ("unfake.exe", "unfake"):
        candidate = scripts_dir / name
        if candidate.exists():
            return str(candidate)
    return None


def _estimate_border_background(rgb, alpha, np):
    height, width = alpha.shape
    border = np.zeros((height, width), dtype=bool)
    border[0, :] = True
    border[-1, :] = True
    border[:, 0] = True
    border[:, -1] = True
    visible_border = border & (alpha > 0)
    samples = rgb[visible_border] if np.any(visible_border) else rgb[border]
    if samples.size == 0:
        return np.array([255, 0, 255], dtype=np.uint8)
    return np.median(samples.reshape(-1, 3), axis=0).astype(np.uint8)


def _near_background_mask(rgb, alpha, bg_rgb, tolerance: int, cv2, np):
    rgb_distance = np.linalg.norm(rgb.astype(np.int16) - bg_rgb.astype(np.int16), axis=2)
    lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB)
    bg_lab = cv2.cvtColor(bg_rgb.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2LAB)[0, 0]
    lab_distance = np.linalg.norm(lab.astype(np.int16) - bg_lab.astype(np.int16), axis=2)
    transparent = alpha <= 0
    return transparent | ((rgb_distance <= tolerance) & (lab_distance <= max(tolerance * 1.6, tolerance + 8)))


def _background_distance_masks(rgb, alpha, bg_rgb, tolerance: int, cv2, np):
    rgb_distance = np.linalg.norm(rgb.astype(np.int16) - bg_rgb.astype(np.int16), axis=2)
    lab = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB)
    bg_lab = cv2.cvtColor(bg_rgb.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2LAB)[0, 0]
    lab_distance = np.linalg.norm(lab.astype(np.int16) - bg_lab.astype(np.int16), axis=2)
    transparent = alpha <= 0
    near_bg = transparent | ((rgb_distance <= tolerance) & (lab_distance <= max(tolerance * 1.6, tolerance + 8)))
    strict_bg = transparent | ((rgb_distance <= max(12, tolerance * 0.72)) & (lab_distance <= max(16, tolerance * 1.05)))
    return near_bg, strict_bg


def _edge_connected_background(near_bg, cv2, np):
    labels_count, labels = cv2.connectedComponents(near_bg.astype(np.uint8), connectivity=8)
    if labels_count <= 1:
        return near_bg.astype(bool)
    edge_labels = set(int(value) for value in labels[0, near_bg[0, :]])
    edge_labels.update(int(value) for value in labels[-1, near_bg[-1, :]])
    edge_labels.update(int(value) for value in labels[near_bg[:, 0], 0])
    edge_labels.update(int(value) for value in labels[near_bg[:, -1], -1])
    edge_labels.discard(0)
    if not edge_labels:
        return np.zeros_like(near_bg, dtype=bool)
    return np.isin(labels, list(edge_labels))


def _clean_subject_mask(subject_mask, cv2, np):
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = subject_mask.astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    labels_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if labels_count <= 1:
        return mask.astype(bool)
    areas = stats[1:, cv2.CC_STAT_AREA]
    if areas.size == 0:
        return mask.astype(bool)
    min_area = max(3, int(areas.max() * 0.003))
    keep = [index + 1 for index, area in enumerate(areas) if area >= min_area]
    return np.isin(labels, keep)


def _erode_mask(mask, pixels: int, cv2, np):
    if pixels <= 0:
        return mask.astype(bool)
    kernel = np.ones((pixels * 2 + 1, pixels * 2 + 1), dtype=np.uint8)
    return cv2.erode(mask.astype(np.uint8), kernel, iterations=1).astype(bool)


def _decontaminate_edge_rgb(rgb, subject_mask, edge_pixels: int, cv2, np, ndimage):
    if edge_pixels <= 0 or not np.any(subject_mask):
        return rgb
    sure_fg = _erode_mask(subject_mask, edge_pixels, cv2, np)
    if not np.any(sure_fg):
        sure_fg = subject_mask
    edge_band = subject_mask & ~sure_fg
    if not np.any(edge_band):
        return rgb
    nearest_indices = ndimage.distance_transform_edt(~sure_fg, return_distances=False, return_indices=True)
    cleaned = rgb.copy()
    cleaned[edge_band] = rgb[nearest_indices[0][edge_band], nearest_indices[1][edge_band]]
    return cleaned


def _remove_chroma_key_spill_from_subject(rgb, bg_rgb, subject_mask, edge_pixels: int, cv2, np):
    if edge_pixels <= 0 or not np.any(subject_mask):
        return np.zeros_like(subject_mask, dtype=bool)
    bg = bg_rgb.astype(np.int16)
    magenta_key = bg[0] >= 180 and bg[2] >= 180 and bg[1] <= 96 and abs(int(bg[0]) - int(bg[2])) <= 96
    if not magenta_key:
        return np.zeros_like(subject_mask, dtype=bool)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    dark_magenta_spill = (
        (r >= 96)
        & (b >= 96)
        & (g <= 96)
        & (g * 2 <= np.minimum(r, b))
        & (np.abs(r - b) <= 128)
    )
    passable_from_background = (~subject_mask) | dark_magenta_spill
    labels_count, labels = cv2.connectedComponents(passable_from_background.astype(np.uint8), connectivity=8)
    edge_labels = set(int(value) for value in labels[0, passable_from_background[0, :]])
    edge_labels.update(int(value) for value in labels[-1, passable_from_background[-1, :]])
    edge_labels.update(int(value) for value in labels[passable_from_background[:, 0], 0])
    edge_labels.update(int(value) for value in labels[passable_from_background[:, -1], -1])
    edge_labels.discard(0)
    removed = np.zeros_like(subject_mask, dtype=bool)
    if labels_count > 1 and edge_labels:
        connected_spill = subject_mask & dark_magenta_spill & np.isin(labels, list(edge_labels))
        removed = removed | connected_spill
        subject_mask = subject_mask & ~connected_spill
    working_subject = subject_mask.copy()
    for _iteration in range(4):
        subject_edge = _edge_band(working_subject, max(4, edge_pixels * 3), cv2, np)
        spill = working_subject & subject_edge & dark_magenta_spill
        if not np.any(spill):
            break
        removed = removed | spill
        working_subject = working_subject & ~spill
    remaining_spill = subject_mask & ~removed & dark_magenta_spill
    if np.any(remaining_spill):
        labels_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(remaining_spill.astype(np.uint8), connectivity=8)
        if labels_count > 1:
            max_speckle_area = max(4, edge_pixels * edge_pixels * 8)
            speckle_labels = [
                label
                for label in range(1, labels_count)
                if stats[label, cv2.CC_STAT_AREA] <= max_speckle_area
            ]
            if speckle_labels:
                removed = removed | np.isin(labels, speckle_labels)
    return removed


def _edge_band(subject_mask, edge_pixels: int, cv2, np):
    if edge_pixels <= 0 or not np.any(subject_mask):
        return np.zeros_like(subject_mask, dtype=bool)
    sure_fg = _erode_mask(subject_mask, edge_pixels, cv2, np)
    if not np.any(sure_fg):
        return np.zeros_like(subject_mask, dtype=bool)
    return subject_mask & ~sure_fg


def apply_pixel_mask(
    image,
    *,
    rembg_alpha=None,
    mode: PixelMaskMode = "hybrid",
    decontaminate_edges: bool = True,
    bg_tolerance: int = 60,
    alpha_threshold: int = 12,
    hybrid_near_bg_alpha_threshold: int = 192,
    edge_pixels: int = 2,
    debug_dir: Path | None = None,
    debug_prefix: str = "frame",
):
    if mode not in {"hybrid", "rembg", "classic"}:
        raise ValueError(f"Unknown pixel mask mode: {mode}")
    cv2, np, ndimage = _require_mask_dependencies()
    Image, _, _ = _require_pillow()
    rgba_image = image.convert("RGBA")
    data = np.array(rgba_image, dtype=np.uint8)
    rgb = data[:, :, :3]
    alpha = data[:, :, 3]
    bg_rgb = _estimate_border_background(rgb, alpha, np)
    near_bg, strict_bg = _background_distance_masks(rgb, alpha, bg_rgb, bg_tolerance, cv2, np)
    classic_bg = _edge_connected_background(near_bg, cv2, np)

    if rembg_alpha is not None:
        rembg_alpha_array = np.array(rembg_alpha.resize(rgba_image.size, Image.Resampling.NEAREST), dtype=np.uint8)
    else:
        rembg_alpha_array = None
    if mode in {"hybrid", "rembg"} and rembg_alpha_array is None:
        raise ValueError(f"Mask mode {mode} requires rembg alpha data")

    if mode == "classic":
        background = classic_bg
    elif mode == "rembg":
        background = rembg_alpha_array <= alpha_threshold
    else:
        near_bg_alpha_threshold = max(alpha_threshold, hybrid_near_bg_alpha_threshold)
        rembg_near_background = rembg_alpha_array <= near_bg_alpha_threshold
        background = classic_bg | (rembg_near_background & near_bg)
    background = background | (alpha <= 0)
    subject_mask = _clean_subject_mask(~background, cv2, np)
    edge_band = _edge_band(subject_mask, edge_pixels, cv2, np)
    remove_fringe = edge_band & strict_bg
    background_leak = np.zeros_like(subject_mask, dtype=bool)
    if mode == "hybrid" and rembg_alpha_array is not None:
        background_leak = subject_mask & ~remove_fringe & near_bg & (rembg_alpha_array < 255)
    if np.any(remove_fringe):
        subject_mask = subject_mask & ~remove_fringe
    if np.any(background_leak):
        subject_mask = subject_mask & ~background_leak
    chroma_spill = _remove_chroma_key_spill_from_subject(rgb, bg_rgb, subject_mask, edge_pixels, cv2, np)
    if np.any(chroma_spill):
        subject_mask = subject_mask & ~chroma_spill
    cleaned_rgb = rgb
    if decontaminate_edges:
        cleaned_rgb = _decontaminate_edge_rgb(rgb, subject_mask, edge_pixels, cv2, np, ndimage)
    output = np.zeros_like(data)
    output[:, :, :3] = cleaned_rgb
    output[:, :, 3] = np.where(subject_mask, 255, 0).astype(np.uint8)

    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray((near_bg.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_near_bg.png")
        Image.fromarray((strict_bg.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_strict_bg.png")
        Image.fromarray((classic_bg.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_classic_bg.png")
        Image.fromarray((background.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_background.png")
        Image.fromarray((edge_band.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_edge_band.png")
        Image.fromarray((remove_fringe.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_remove_fringe.png")
        Image.fromarray((background_leak.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_background_leak.png")
        Image.fromarray((chroma_spill.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_chroma_spill.png")
        Image.fromarray((subject_mask.astype(np.uint8) * 255), "L").save(debug_dir / f"{debug_prefix}_subject_mask.png")
        if rembg_alpha_array is not None:
            Image.fromarray(rembg_alpha_array, "L").save(debug_dir / f"{debug_prefix}_rembg_alpha.png")

    return Image.fromarray(output, "RGBA"), {
        "mode": mode,
        "backgroundRgb": [int(value) for value in bg_rgb.tolist()],
        "visiblePixels": int(subject_mask.sum()),
        "removedFringePixels": int(remove_fringe.sum()),
        "removedBackgroundLeakPixels": int(background_leak.sum()),
        "removedChromaSpillPixels": int(chroma_spill.sum()),
        "decontaminated": bool(decontaminate_edges),
    }


def frame_qa_summary(sheet_image, columns: int, rows: int, cell_width: int, cell_height: int) -> dict[str, Any]:
    Image, _, _ = _require_pillow()
    rgba = sheet_image.convert("RGBA")
    frame_count = columns * rows
    frames: list[dict[str, Any]] = []
    lefts: list[int] = []
    rights: list[int] = []
    tops: list[int] = []
    bottoms: list[int] = []
    visible_counts: list[int] = []
    for index in range(frame_count):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        cell = rgba.crop((x, y, x + cell_width, y + cell_height))
        alpha = cell.getchannel("A")
        box = alpha.getbbox()
        visible = sum(1 for value in alpha.getdata() if value > 0)
        item: dict[str, Any] = {"index": index, "visiblePixels": visible, "empty": box is None}
        if box:
            left, top, right, bottom = box
            item["bbox"] = {"left": left, "top": top, "right": right, "bottom": bottom, "width": right - left, "height": bottom - top}
            lefts.append(left)
            rights.append(right)
            tops.append(top)
            bottoms.append(bottom)
        frames.append(item)
        visible_counts.append(visible)
    empty_count = sum(1 for item in frames if item["empty"])
    jitter = {
        "leftRange": max(lefts) - min(lefts) if lefts else 0,
        "rightRange": max(rights) - min(rights) if rights else 0,
        "topRange": max(tops) - min(tops) if tops else 0,
        "bottomRange": max(bottoms) - min(bottoms) if bottoms else 0,
    }
    return {
        "columns": columns,
        "rows": rows,
        "cellWidth": cell_width,
        "cellHeight": cell_height,
        "sheetWidth": columns * cell_width,
        "sheetHeight": rows * cell_height,
        "frameCount": frame_count,
        "emptyFrameCount": empty_count,
        "visiblePixelMin": min(visible_counts, default=0),
        "visiblePixelMax": max(visible_counts, default=0),
        "bboxJitter": jitter,
        "frames": frames,
    }


def write_qa_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def run_unfake_restore(input_path: Path, output_path: Path, mode: PixelRestoreMode) -> Path:
    if mode == "none":
        return input_path
    if mode not in {"clean", "safe", "pixel"}:
        raise ValueError(f"Unknown pixel restore mode: {mode}")
    executable = _find_unfake_executable()
    if not executable:
        raise RuntimeError("unfake CLI is not available. Install unfake and make sure it is on PATH before using pixel restore.")
    command = [executable, str(input_path), "-o", str(output_path), "--transparent-background"]
    if mode == "clean":
        command.extend(["--scale", "1"])
    elif mode == "safe":
        command.extend(["--scale", "1", "--no-snap", "--colors", "256"])
    else:
        command.extend(["--detect", "auto", "--colors", "256"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"unfake failed with exit code {result.returncode}: {detail}")
    if not output_path.exists():
        raise RuntimeError(f"unfake did not create output: {output_path}")
    return output_path
