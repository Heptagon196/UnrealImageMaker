from __future__ import annotations

from pathlib import Path

from ..manifest import AssetManifest


def _unreal_path(value: str) -> str:
    return value.replace("\\", "/")


def generate_import_script(manifest: AssetManifest, project_root: Path, output_path: Path) -> Path:
    unreal_target = manifest.targets.get("unreal", {})
    content_path = unreal_target.get("contentPath", "/Game/UIM")
    files = [
        {
            "source": str((project_root / asset_file.path).resolve()),
            "destination": content_path,
            "role": asset_file.role,
        }
        for asset_file in manifest.files
    ]
    lines = [
        "import unreal",
        "",
        f"FILES = {files!r}",
        f"CONTENT_PATH = {content_path!r}",
        "",
        "asset_tools = unreal.AssetToolsHelpers.get_asset_tools()",
        "tasks = []",
        "for item in FILES:",
        "    task = unreal.AssetImportTask()",
        "    task.filename = item['source']",
        "    task.destination_path = item['destination']",
        "    task.automated = True",
        "    task.save = True",
        "    task.replace_existing = True",
        "    tasks.append(task)",
        "asset_tools.import_asset_tasks(tasks)",
        "",
        "for task in tasks:",
        "    for object_path in task.imported_object_paths:",
        "        asset = unreal.load_asset(object_path)",
        "        if asset and asset.get_class().get_name() == 'Texture2D':",
        "            try:",
        "                asset.set_editor_property('srgb', True)",
        "                asset.set_editor_property('mip_gen_settings', unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)",
        "                asset.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_EDITOR_ICON)",
        "                asset.post_edit_change()",
        "            except Exception as exc:",
        "                unreal.log_warning(f'Failed to set texture properties for {object_path}: {exc}')",
        "unreal.EditorAssetLibrary.save_directory(CONTENT_PATH, only_if_is_dirty=False, recursive=True)",
        "unreal.log('UnrealImageMaker import complete')",
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return output_path


def unreal_export_summary(manifest: AssetManifest) -> dict:
    target = manifest.targets.get("unreal", {})
    return {
        "contentPath": target.get("contentPath", "/Game/UIM"),
        "create": target.get("create", ["Texture2D"]),
        "files": [asset_file.path for asset_file in manifest.files],
        "frames": len(manifest.frames),
        "animations": len(manifest.animations),
    }
