from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Bounds:
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def _require_pillow():
    try:
        from PIL import Image, ImageChops, ImageFilter
    except ImportError as exc:
        raise RuntimeError("Pillow is required for image processing. Install backend requirements.") from exc
    return Image, ImageChops, ImageFilter


def alpha_bounds(image_path: Path) -> Bounds | None:
    Image, _, _ = _require_pillow()
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        box = alpha.getbbox()
        if box is None:
            return None
        left, top, right, bottom = box
        return Bounds(x=left, y=top, width=right - left, height=bottom - top)


def trim_transparent(input_path: Path, output_path: Path, padding: int = 0) -> Bounds | None:
    Image, _, _ = _require_pillow()
    with Image.open(input_path) as image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        box = alpha.getbbox()
        if box is None:
            return None
        left, top, right, bottom = box
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(rgba.width, right + padding)
        bottom = min(rgba.height, bottom + padding)
        cropped = rgba.crop((left, top, right, bottom))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output_path)
        return Bounds(left, top, right - left, bottom - top)


def clean_alpha_halo(input_path: Path, output_path: Path, threshold: int = 2) -> None:
    Image, _, ImageFilter = _require_pillow()
    with Image.open(input_path) as image:
        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        a = a.point(lambda value: 0 if value <= threshold else value)
        cleaned = Image.merge("RGBA", (r, g, b, a))
        cleaned = cleaned.filter(ImageFilter.UnsharpMask(radius=0.5, percent=80, threshold=3))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned.save(output_path)


def edge_extrude(input_path: Path, output_path: Path, padding: int = 2) -> None:
    Image, _, _ = _require_pillow()
    with Image.open(input_path) as image:
        rgba = image.convert("RGBA")
        output = Image.new("RGBA", (rgba.width + padding * 2, rgba.height + padding * 2), (0, 0, 0, 0))
        output.paste(rgba, (padding, padding), rgba)
        # Simple MVP extrusion: duplicate edge pixels around the sprite canvas.
        for i in range(padding):
            output.paste(rgba.crop((0, 0, rgba.width, 1)), (padding, i))
            output.paste(rgba.crop((0, rgba.height - 1, rgba.width, rgba.height)), (padding, padding + rgba.height + i))
            output.paste(rgba.crop((0, 0, 1, rgba.height)), (i, padding))
            output.paste(rgba.crop((rgba.width - 1, 0, rgba.width, rgba.height)), (padding + rgba.width + i, padding))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_path)


def nearest_scale(input_path: Path, output_path: Path, scale: int) -> None:
    if scale <= 0:
        raise ValueError("scale must be positive")
    Image, _, _ = _require_pillow()
    with Image.open(input_path) as image:
        rgba = image.convert("RGBA")
        scaled = rgba.resize((rgba.width * scale, rgba.height * scale), Image.Resampling.NEAREST)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        scaled.save(output_path)


def quantize_palette(input_path: Path, output_path: Path, colors: int = 32) -> None:
    Image, _, _ = _require_pillow()
    with Image.open(input_path) as image:
        rgba = image.convert("RGBA")
        rgb = rgba.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        quantized = rgb.convert("RGBA")
        quantized.putalpha(rgba.getchannel("A"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        quantized.save(output_path)


def split_fixed_grid(
    sheet_path: Path,
    output_dir: Path,
    cell_width: int,
    cell_height: int,
    prefix: str = "frame",
) -> list[dict]:
    Image, _, _ = _require_pillow()
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    with Image.open(sheet_path) as image:
        rgba = image.convert("RGBA")
        columns = rgba.width // cell_width
        rows = rgba.height // cell_height
        index = 0
        for row in range(rows):
            for column in range(columns):
                x = column * cell_width
                y = row * cell_height
                frame = rgba.crop((x, y, x + cell_width, y + cell_height))
                if frame.getchannel("A").getbbox() is None:
                    continue
                name = f"{prefix}_{index:03d}"
                frame_path = output_dir / f"{name}.png"
                frame.save(frame_path)
                frames.append(
                    {
                        "name": name,
                        "path": str(frame_path),
                        "x": x,
                        "y": y,
                        "width": cell_width,
                        "height": cell_height,
                        "pivot": (0.5, 0.5),
                    }
                )
                index += 1
    return frames


def detect_alpha_frames(sheet_path: Path, output_dir: Path, prefix: str = "frame") -> list[dict]:
    Image, _, _ = _require_pillow()
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    with Image.open(sheet_path) as image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        box = alpha.getbbox()
        if box is None:
            return frames
        left, top, right, bottom = box
        name = f"{prefix}_000"
        frame = rgba.crop((left, top, right, bottom))
        frame_path = output_dir / f"{name}.png"
        frame.save(frame_path)
        frames.append(
            {
                "name": name,
                "path": str(frame_path),
                "x": left,
                "y": top,
                "width": right - left,
                "height": bottom - top,
                "pivot": (0.5, 0.5),
            }
        )
    return frames
