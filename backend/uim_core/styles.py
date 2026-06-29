from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .constants import BUILTIN_STYLE_IDS
from .json_io import write_json


@dataclass(slots=True)
class UnrealImportSettings:
    srgb: bool
    mipmaps: bool
    compression: str
    texture_group: str
    filter_mode: str


@dataclass(slots=True)
class StyleProfile:
    id: str
    display_name: str
    prompt_template: str
    negative_constraints: list[str]
    default_size: str
    processing_chain: list[str]
    validation_rules: list[str]
    unreal_import: UnrealImportSettings
    model_route: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


BUILTIN_STYLES: dict[str, StyleProfile] = {
    "pixel_art": StyleProfile(
        id="pixel_art",
        display_name="像素风 2D",
        prompt_template=(
            "Create a clean pixel art game asset. Subject: {prompt}. "
            "Use crisp edges, limited palette, orthographic game-asset presentation, "
            "plain background, no text."
        ),
        negative_constraints=[
            "no anti-aliased blurry edges",
            "no realistic rendering",
            "no text",
            "no watermark",
        ],
        default_size="1024x1024",
        processing_chain=["rembg", "trim", "padding", "nearest_scale", "validate_pixel_edges"],
        validation_rules=["alpha_not_empty", "pixel_antialiasing_risk", "unreal_target_path"],
        unreal_import=UnrealImportSettings(
            srgb=True,
            mipmaps=False,
            compression="TC_EditorIcon",
            texture_group="TEXTUREGROUP_Pixels2D",
            filter_mode="nearest",
        ),
        model_route={"generate": "gpt-image-2", "background": "rembg:isnet-anime"},
    ),
    "hand_drawn_cartoon": StyleProfile(
        id="hand_drawn_cartoon",
        display_name="手绘 / 卡通 2D",
        prompt_template=(
            "Create a hand-drawn cartoon 2D game asset. Subject: {prompt}. "
            "Use clear silhouette, consistent outline, production-ready sprite style, "
            "plain background, no text."
        ),
        negative_constraints=["no watermark", "no text", "no cropped subject"],
        default_size="1024x1024",
        processing_chain=["rembg", "alpha_clean", "trim", "padding", "edge_extrude"],
        validation_rules=["alpha_not_empty", "transparent_edge_dirt", "unreal_target_path"],
        unreal_import=UnrealImportSettings(
            srgb=True,
            mipmaps=False,
            compression="TC_EditorIcon",
            texture_group="TEXTUREGROUP_UI",
            filter_mode="default",
        ),
        model_route={"generate": "gpt-image-2", "background": "rembg:isnet-anime"},
    ),
    "semi_realistic_ui": StyleProfile(
        id="semi_realistic_ui",
        display_name="半写实 UI 图标",
        prompt_template=(
            "Create a semi-realistic game UI asset. Subject: {prompt}. "
            "Use readable shape language, consistent lighting, centered composition, "
            "plain background, no text."
        ),
        negative_constraints=["no text", "no watermark", "no busy background"],
        default_size="1024x1024",
        processing_chain=["rembg", "alpha_clean", "trim", "padding"],
        validation_rules=["alpha_not_empty", "ui_state_size_match", "unreal_target_path"],
        unreal_import=UnrealImportSettings(
            srgb=True,
            mipmaps=True,
            compression="TC_EditorIcon",
            texture_group="TEXTUREGROUP_UI",
            filter_mode="default",
        ),
        model_route={"generate": "gpt-image-2", "background": "rembg:isnet-general-use"},
    ),
}


def get_style(style_id: str) -> StyleProfile:
    try:
        return BUILTIN_STYLES[style_id]
    except KeyError as exc:
        raise ValueError(f"Unknown style profile: {style_id}") from exc


def write_builtin_styles(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    for style_id in BUILTIN_STYLE_IDS:
        write_json(profile_dir / f"{style_id}.json", BUILTIN_STYLES[style_id].to_dict())
