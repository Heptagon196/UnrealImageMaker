from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .asset_index import asset_id_from_name, register_asset_version, versioned_filename
from .image_processing import split_fixed_grid, trim_transparent
from .manifest import AssetFile, AssetManifest, NineSlice, SpriteFrame, UIState, write_manifest
from .providers.codex_oauth_image import CodexOAuthImageProvider
from .providers.openai_image import OpenAIImageProvider
from .styles import get_style


def create_sprite_asset(
    project_root: Path,
    prompt: str,
    style_id: str,
    asset_name: str,
    content_path: str = "/Game/UIM",
    image_provider: str = "openai_api",
) -> AssetManifest:
    style = get_style(style_id)
    asset_id = asset_id_from_name(asset_name)
    asset_root = project_root / "assets" / asset_id
    generated_dir = asset_root / "generated"
    manifests_dir = asset_root / "manifests"
    generated_dir.mkdir(parents=True, exist_ok=True)
    output_file = generated_dir / versioned_filename("source")
    full_prompt = style.prompt_template.format(prompt=prompt)

    if image_provider == "codex_oauth":
        provider = CodexOAuthImageProvider()
    elif image_provider == "openai_api":
        provider = OpenAIImageProvider()
    else:
        raise ValueError(f"Unknown image provider: {image_provider}")
    result = provider.generate(full_prompt, output_file, size=style.default_size)

    final_file = generated_dir / versioned_filename("final")
    bounds = trim_transparent(output_file, final_file, padding=4)
    rel_final = final_file.relative_to(project_root).as_posix()
    manifest = AssetManifest(
        asset_type="texture",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role="final", path=rel_final)],
        processing={
            "prompt": prompt,
            "expandedPrompt": full_prompt,
            "model": result.model,
            "provider": image_provider,
            "providerBaseUrl": result.base_url,
            "size": result.size,
            "quality": result.quality,
            "requestId": result.request_id,
            "streamEvents": result.stream_events or [],
            "trimBounds": bounds.to_dict() if bounds else None,
        },
        targets={
            "unreal": {
                "contentPath": content_path,
                "create": ["Texture2D"],
                "importSettings": asdict(style.unreal_import),
            }
        },
    )
    write_manifest(manifests_dir / "manifest.json", manifest)
    register_asset_version(project_root, asset_name, rel_final, "final", "final", asset_id=asset_id)
    return manifest


def create_ui_kit_manifest(
    project_root: Path,
    asset_name: str,
    style_id: str,
    state_files: dict[str, Path],
    nine_slice: tuple[int, int, int, int] | None = None,
    content_path: str = "/Game/UIM/UI",
) -> AssetManifest:
    asset_id = asset_id_from_name(asset_name)
    asset_root = project_root / "assets" / asset_id
    manifests_dir = asset_root / "manifests"
    files: list[AssetFile] = []
    states: list[UIState] = []
    for state_name, file_path in state_files.items():
        rel_path = file_path.resolve().relative_to(project_root.resolve()).as_posix()
        files.append(AssetFile(role=f"ui_state:{state_name}", path=rel_path))
        states.append(UIState(name=state_name, file=rel_path))
    manifest = AssetManifest(
        asset_type="ui_kit",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=files,
        ui_states=states,
        nine_slice=NineSlice(*nine_slice) if nine_slice else None,
        processing={"ui": {"states": list(state_files.keys())}},
        targets={
            "unreal": {
                "contentPath": content_path,
                "create": ["Texture2D", "SlateBrushMetadata"],
            }
        },
    )
    write_manifest(manifests_dir / "manifest.json", manifest)
    for state_name, file_path in state_files.items():
        register_asset_version(project_root, asset_name, file_path, f"ui_state:{state_name}", state_name, asset_id=asset_id, kind="game_ui")
    return manifest


def create_spritesheet_manifest(
    project_root: Path,
    sheet_path: Path,
    asset_name: str,
    style_id: str,
    cell_width: int,
    cell_height: int,
    content_path: str = "/Game/UIM",
) -> AssetManifest:
    asset_id = asset_id_from_name(asset_name) or str(uuid4())
    asset_root = project_root / "assets" / asset_id
    frame_dir = asset_root / "generated" / "frames"
    manifests_dir = asset_root / "manifests"
    frames_data = split_fixed_grid(sheet_path, frame_dir, cell_width, cell_height, asset_id)
    rel_sheet = sheet_path.resolve().relative_to(project_root.resolve()).as_posix()
    frames = [
        SpriteFrame(
            name=item["name"],
            x=item["x"],
            y=item["y"],
            width=item["width"],
            height=item["height"],
            pivot=item["pivot"],
        )
        for item in frames_data
    ]
    manifest = AssetManifest(
        asset_type="spritesheet",
        asset_id=asset_id,
        display_name=asset_name,
        style_profile=style_id,
        files=[AssetFile(role="spritesheet", path=rel_sheet)],
        frames=frames,
        processing={"split": {"mode": "fixed_grid", "cellWidth": cell_width, "cellHeight": cell_height}},
        targets={
            "unreal": {
                "contentPath": content_path,
                "create": ["Texture2D", "PaperSprite", "PaperFlipbook"],
            }
        },
    )
    write_manifest(manifests_dir / "manifest.json", manifest)
    register_asset_version(project_root, asset_name, rel_sheet, "spritesheet", "spritesheet", asset_id=asset_id)
    return manifest
