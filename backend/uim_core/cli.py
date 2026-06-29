from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .manifest import AssetManifest
from .models import MODEL_REGISTRY, install_marker, model_status
from .paths import model_cache_dir
from .pipelines import create_spritesheet_manifest, create_ui_kit_manifest
from .project import create_project, load_project
from .unreal.python_export import generate_import_script


def _print(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="uim")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-project")
    create.add_argument("root")
    create.add_argument("name")
    create.add_argument("--overwrite", action="store_true")

    open_project = sub.add_parser("open-project")
    open_project.add_argument("root")

    models = sub.add_parser("models")
    models.add_argument("--cache-root")

    install = sub.add_parser("install-marker")
    install.add_argument("model_id")
    install.add_argument("--cache-root")

    sheet = sub.add_parser("spritesheet")
    sheet.add_argument("project_root")
    sheet.add_argument("sheet_path")
    sheet.add_argument("asset_name")
    sheet.add_argument("--style-id", default="pixel_art")
    sheet.add_argument("--cell-width", type=int, required=True)
    sheet.add_argument("--cell-height", type=int, required=True)
    sheet.add_argument("--content-path", default="/Game/UIM")

    ui = sub.add_parser("ui-kit")
    ui.add_argument("project_root")
    ui.add_argument("asset_name")
    ui.add_argument("--style-id", default="semi_realistic_ui")
    ui.add_argument("--state", action="append", default=[], help="stateName=path")
    ui.add_argument("--content-path", default="/Game/UIM/UI")

    unreal = sub.add_parser("unreal-script")
    unreal.add_argument("project_root")
    unreal.add_argument("manifest_json")
    unreal.add_argument("output_path")

    args = parser.parse_args()

    if args.command == "create-project":
        _print(create_project(Path(args.root), args.name, args.overwrite).to_dict())
    elif args.command == "open-project":
        _print(load_project(Path(args.root)).to_dict())
    elif args.command == "models":
        cache = Path(args.cache_root) if args.cache_root else model_cache_dir()
        _print({"cacheDir": str(cache), "models": [{**asdict(spec), "status": model_status(cache, spec.id)} for spec in MODEL_REGISTRY.values()]})
    elif args.command == "install-marker":
        cache = Path(args.cache_root) if args.cache_root else model_cache_dir()
        marker = install_marker(cache, MODEL_REGISTRY[args.model_id])
        _print({"marker": str(marker), "status": model_status(cache, args.model_id)})
    elif args.command == "spritesheet":
        manifest = create_spritesheet_manifest(
            Path(args.project_root),
            Path(args.sheet_path),
            args.asset_name,
            args.style_id,
            args.cell_width,
            args.cell_height,
            args.content_path,
        )
        _print(manifest.to_dict())
    elif args.command == "ui-kit":
        states = {}
        for raw_state in args.state:
            name, value = raw_state.split("=", 1)
            states[name] = Path(value)
        manifest = create_ui_kit_manifest(Path(args.project_root), args.asset_name, args.style_id, states, content_path=args.content_path)
        _print(manifest.to_dict())
    elif args.command == "unreal-script":
        manifest = AssetManifest.from_dict(json.loads(Path(args.manifest_json).read_text(encoding="utf-8")))
        path = generate_import_script(manifest, Path(args.project_root), Path(args.output_path))
        _print({"script": str(path)})


if __name__ == "__main__":
    main()
