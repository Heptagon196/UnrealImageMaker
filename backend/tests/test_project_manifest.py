from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uim_core.manifest import AssetFile, AssetManifest, SpriteFrame, validate_manifest
from uim_core.models import MODEL_REGISTRY, delete_model, install_marker, model_status
from uim_core.pipelines import create_sprite_asset
from uim_core.project import create_project, load_project
from uim_core.providers.openai_image import ImageGenerationResult


class ProjectManifestTests(unittest.TestCase):
    def test_create_and_load_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            created = create_project(root, "Demo")
            loaded = load_project(root)
            self.assertEqual(created.id, loaded.id)
            self.assertTrue((root / "project.uim.json").exists())
            self.assertTrue((root / "models.lock.json").exists())
            self.assertTrue((root / "profiles" / "pixel_art.json").exists())

    def test_read_json_accepts_utf8_bom(self) -> None:
        from uim_core.json_io import read_json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.index.json"
            path.write_text('{"schema":"uim.asset_index.v1","assetId":"hero"}', encoding="utf-8-sig")
            data = read_json(path)
            self.assertEqual(data["assetId"], "hero")

    def test_validate_spritesheet_manifest(self) -> None:
        manifest = AssetManifest(
            asset_type="spritesheet",
            asset_id="hero_run",
            display_name="Hero Run",
            style_profile="pixel_art",
            files=[AssetFile(role="spritesheet", path="assets/hero_run/generated/sheet.png")],
            frames=[SpriteFrame(name="run_000", x=0, y=0, width=64, height=64)],
        )
        self.assertEqual(validate_manifest(manifest), [])

    def test_create_sprite_asset_serializes_unreal_import_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            def fake_generate(_provider, _prompt: str, output_path: Path, *, size: str) -> ImageGenerationResult:
                from PIL import Image

                image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
                for x in range(2, 6):
                    for y in range(2, 6):
                        image.putpixel((x, y), (255, 80, 20, 255))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(output_path)
                return ImageGenerationResult(
                    output_path=output_path,
                    model="test-model",
                    prompt=_prompt,
                    size=size,
                    quality="auto",
                    request_id="test-request",
                )

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", fake_generate):
                manifest = create_sprite_asset(
                    project_root=root,
                    prompt="fire spell",
                    style_id="pixel_art",
                    asset_name="Fire Spell",
                    content_path="/Game/UIM",
                    image_provider="openai_api",
                )

            data = manifest.to_dict()
            import_settings = data["targets"]["unreal"]["importSettings"]
            self.assertEqual(import_settings["filter_mode"], "nearest")
            self.assertTrue((root / "assets" / "fire_spell" / "manifests" / "manifest.json").exists())
            self.assertTrue((root / "assets" / "fire_spell" / "asset.index.json").exists())

    def test_create_sprite_asset_keeps_multiple_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            def fake_generate(_provider, _prompt: str, output_path: Path, *, size: str) -> ImageGenerationResult:
                from PIL import Image

                image = Image.new("RGBA", (8, 8), (255, 80, 20, 255))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(output_path)
                return ImageGenerationResult(output_path=output_path, model="test-model", prompt=_prompt, size=size, quality="auto", request_id="test-request")

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", fake_generate):
                first = create_sprite_asset(root, "fire spell", "pixel_art", "Fire Spell", "/Game/UIM", "openai_api")
                second = create_sprite_asset(root, "fire spell", "pixel_art", "Fire Spell", "/Game/UIM", "openai_api")

            first_path = first.files[0].path
            second_path = second.files[0].path
            self.assertNotEqual(first_path, second_path)
            self.assertTrue((root / first_path).exists())
            self.assertTrue((root / second_path).exists())
            from uim_core.json_io import read_json

            index = read_json(root / "assets" / "fire_spell" / "asset.index.json")
            self.assertEqual(len(index["versions"]), 2)

    def test_rembg_marker_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "model-cache"
            model_id = "rembg:u2netp"
            self.assertEqual(model_status(cache, model_id), "not_installed")
            install_marker(cache, MODEL_REGISTRY[model_id])
            self.assertEqual(model_status(cache, model_id), "installed")

    def test_sam_marker_requires_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "model-cache"
            model_id = "sam2.1_hiera_small"
            self.assertEqual(model_status(cache, model_id), "not_installed")
            install_marker(cache, MODEL_REGISTRY[model_id])
            self.assertEqual(model_status(cache, model_id), "broken")
            (cache / model_id / f"{model_id}.pt").write_bytes(b"checkpoint")
            self.assertEqual(model_status(cache, model_id), "installed")

    def test_delete_model_rejects_unknown_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "model-cache"
            with self.assertRaises(KeyError):
                delete_model(cache, "../outside")


if __name__ == "__main__":
    unittest.main()
