from __future__ import annotations

import sys
import subprocess
import json
import tempfile
import types
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uim_core.asset_index import load_asset_index
from uim_core.manifest import validate_manifest
from uim_core.pixel_postprocess import apply_pixel_mask, run_unfake_restore
from uim_core.project import create_project
from uim_core.providers.openai_image import ImageGenerationResult, OpenAIImageProvider
from uim_core.providers.seedance_provider import DEFAULT_SEEDANCE_ENDPOINT, SeedanceProvider, SeedanceResult
from uim_core.specialized import (
    TILEMAP_47_IDS,
    TILEMAP_DUAL_GRID_16_IDS,
    _cleanup_tilemap_wang_source,
    _cleanup_boundary_refined_wang_source,
    _compose_wang_47_tile,
    _compose_wang_dual_grid_tile,
    _create_hard_wang_source_from_material_pair,
    _create_tilemap_boundary_mask,
    _is_primary_quadrant_source_pixel,
    _tilemap_boundary_refine_prompt,
    _tilemap_material_pair_prompt,
    _tilemap_seed_prompt,
    _tilemap_wang_source_prompt,
    _terrain_mask,
    _wang_source_quadrants_for_cell,
    create_animation_sheet,
    import_animation_sheet,
    create_pixel_anchor,
    create_pixel_concept,
    create_seedance_walk_video,
    create_spritesheet_cutout,
    create_spritesheet_from_video,
    create_tilemap_47_manifest,
    create_tilemap_from_seed_manifest,
    create_tilemap_seed_concept,
    create_tilemap_dual_grid_manifest,
    create_video_debug_export,
    create_ui_concept,
    import_ui_concept,
    create_ui_widget,
    extract_video_frame_thumbnails,
    normalize_spritesheet,
)


def _fake_image(output_path: Path, size: tuple[int, int] = (64, 64)) -> None:
    from PIL import Image

    image = Image.new("RGBA", size, (255, 0, 255, 255))
    for x in range(size[0] // 4, size[0] * 3 // 4):
        for y in range(size[1] // 4, size[1] * 3 // 4):
            image.putpixel((x, y), (40, 90, 210, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _mock_wang_source(tile_size: int = 32):
    from PIL import Image

    colors = {
        (0, 0): (201, 32, 32, 255),
        (1, 0): (220, 132, 36, 255),
        (2, 0): (221, 211, 46, 255),
        (0, 1): (53, 176, 59, 255),
        (1, 1): (42, 132, 220, 255),
        (2, 1): (125, 78, 210, 255),
        (0, 2): (226, 85, 176, 255),
        (1, 2): (64, 205, 207, 255),
        (2, 2): (105, 68, 37, 255),
        (3, 0): (245, 105, 83, 255),
        (4, 0): (84, 224, 126, 255),
        (3, 1): (91, 116, 240, 255),
        (4, 1): (234, 209, 71, 255),
        (3, 2): (245, 245, 245, 255),
        (4, 2): (12, 12, 12, 255),
    }
    source = Image.new("RGBA", (5 * tile_size, 3 * tile_size), (0, 0, 0, 0))
    for row in range(3):
        for col in range(5):
            tile = Image.new("RGBA", (tile_size, tile_size), colors[(col, row)])
            source.paste(tile, (col * tile_size, row * tile_size))
    return source


class _FakeSeedanceHttpResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> "_FakeSeedanceHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _FakeOpenAIEditResponse:
    status_code = 200
    text = "{}"
    headers = {"x-request-id": "req-edit"}

    def json(self) -> dict[str, object]:
        return {
            "data": [
                {
                    "b64_json": (
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEA"
                        "gh6FOQAAAABJRU5ErkJggg=="
                    )
                }
            ]
        }


def _fake_generate(_provider, prompt: str, output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
    width, height = (int(part) for part in size.split("x", 1))
    _fake_image(output_path, (width, height))
    return ImageGenerationResult(output_path=output_path, model=model, prompt=prompt, size=size, quality=quality, stream_events=["fake image event"])


def _fake_edit(_provider, prompt: str, _image_path: Path, output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
    return _fake_generate(_provider, prompt, output_path, size=size, quality=quality, model=model)


def _fake_edit_many(_provider, prompt: str, _image_paths: list[Path], output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
    return _fake_generate(_provider, prompt, output_path, size=size, quality=quality, model=model)


class SpecializedPipelineTests(unittest.TestCase):
    def test_seedance_default_endpoint_uses_ark_task_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "anchor.png"
            output = root / "video.mp4"
            _fake_image(anchor)
            calls: list[urllib.request.Request] = []

            def fake_open_external_url(request: urllib.request.Request, timeout: int) -> _FakeSeedanceHttpResponse:
                calls.append(request)
                if request.full_url == DEFAULT_SEEDANCE_ENDPOINT:
                    payload = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
                    self.assertEqual(payload["model"], "doubao-seedance-2-0-mini-260615")
                    self.assertEqual(payload["resolution"], "480p")
                    self.assertEqual(payload["duration"], 5)
                    self.assertIs(payload["generate_audio"], False)
                    self.assertEqual(payload["content"][0]["type"], "text")
                    self.assertEqual(payload["content"][1]["type"], "image_url")
                    return _FakeSeedanceHttpResponse(b'{"id":"task-1","status":"running"}', {"x-request-id": "req-1"})
                if request.full_url == f"{DEFAULT_SEEDANCE_ENDPOINT}/task-1":
                    return _FakeSeedanceHttpResponse(b'{"id":"task-1","status":"succeeded","result":{"video_url":"https://cdn.example/video.mp4"}}')
                if request.full_url == "https://cdn.example/video.mp4":
                    return _FakeSeedanceHttpResponse(b"video")
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            with patch("uim_core.providers.seedance_provider.open_external_url", fake_open_external_url), patch("time.sleep", lambda _seconds: None):
                result = SeedanceProvider(api_key="key", model="seedance2.0-mini", resolution="480p").generate_walk_video(anchor, "walk", output, seconds=5)

            self.assertEqual(output.read_bytes(), b"video")
            self.assertEqual(result.request_id, "req-1")
            self.assertEqual(len(calls), 3)

    def test_seedance_provider_migrates_old_inferred_model_ids(self) -> None:
        self.assertEqual(SeedanceProvider(api_key="key", model="doubao-seedance-2-0-pro-260128").model, "doubao-seedance-2-0-260128")
        self.assertEqual(SeedanceProvider(api_key="key", model="doubao-seedance-2-0-mini-260128").model, "doubao-seedance-2-0-mini-260615")

    def test_seedance_task_can_be_cancelled_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "anchor.png"
            output = root / "video.mp4"
            _fake_image(anchor)
            cancel_checks = 0

            def fake_open_external_url(request: urllib.request.Request, timeout: int) -> _FakeSeedanceHttpResponse:
                if request.full_url == DEFAULT_SEEDANCE_ENDPOINT:
                    return _FakeSeedanceHttpResponse(b'{"id":"task-1","status":"running"}', {})
                if request.full_url == f"{DEFAULT_SEEDANCE_ENDPOINT}/task-1":
                    return _FakeSeedanceHttpResponse(b'{"id":"task-1","status":"running"}')
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            def is_cancelled() -> bool:
                nonlocal cancel_checks
                cancel_checks += 1
                return cancel_checks > 1

            with patch("uim_core.providers.seedance_provider.open_external_url", fake_open_external_url), patch("time.sleep", lambda _seconds: None):
                with self.assertRaisesRegex(RuntimeError, "cancelled by user"):
                    SeedanceProvider(api_key="key").generate_walk_video(anchor, "walk", output, seconds=5, is_cancelled=is_cancelled)

    def test_pixel_anchor_and_sheet_register_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", _fake_edit_many
            ):
                concept = create_pixel_concept(root, "Hero", "red cape swordsman", "character", "pixel_art", "openai_api", "/Game/UIM/Pixels", output_size="1024x1024")
                anchor = create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "south", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                sheet = create_animation_sheet(root, "Hero", "red cape swordsman", "character", "idle", "south", "pixel_art", "openai_api", "/Game/UIM/Pixels")

            self.assertEqual(concept.processing["specialized"]["stage"], "concept_box_art")
            self.assertEqual(concept.processing["specialized"]["outputSize"], "1024x1024")
            self.assertIn("referenceImage", concept.processing["specialized"])
            self.assertEqual(anchor.processing["specialized"]["kind"], "character")
            self.assertIn("anchorGridReference", anchor.processing["specialized"])
            self.assertIn("sheetGuideReference", sheet.processing["specialized"])
            self.assertEqual(sheet.asset_type, "spritesheet")
            self.assertEqual(len(sheet.frames), 10)
            index = load_asset_index(root, "hero")
            self.assertEqual(index.kind, "character")
            self.assertEqual(len(index.versions), 3)
            self.assertTrue((root / sheet.files[0].path).exists())

    def test_character_mirrored_direction_uses_existing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", _fake_edit_many
            ):
                create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "south", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "west", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                create_animation_sheet(root, "Hero", "red cape swordsman", "character", "idle", "west", "pixel_art", "openai_api", "/Game/UIM/Pixels", columns=2, rows=1, cell_size=64)
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", side_effect=AssertionError("mirror must not call provider")), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", side_effect=AssertionError("mirror must not call provider")
            ), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", side_effect=AssertionError("mirror must not call provider")
            ):
                anchor = create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "east", "pixel_art", "openai_api", "/Game/UIM/Pixels", mirror_from="west")
                sheet = create_animation_sheet(root, "Hero", "red cape swordsman", "character", "idle", "east", "pixel_art", "openai_api", "/Game/UIM/Pixels", columns=2, rows=1, cell_size=64, mirror_from="west")

            self.assertEqual(anchor.processing["specialized"]["mirroredFrom"], "west")
            self.assertEqual(sheet.processing["specialized"]["mirroredFrom"], "west")
            self.assertTrue((root / anchor.files[0].path).exists())
            self.assertTrue((root / sheet.files[0].path).exists())

    def test_east_direction_can_be_generated_without_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            captured: dict[str, object] = {"edit_many_calls": 0}

            def fake_edit_many(_provider, prompt: str, image_paths: list[Path], output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
                captured["edit_many_calls"] = int(captured["edit_many_calls"]) + 1
                captured["prompt"] = prompt
                captured["image_paths"] = image_paths
                return _fake_generate(_provider, prompt, output_path, size=size, quality=quality, model=model)

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", fake_edit_many
            ):
                create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "south", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "west", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                anchor = create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "east", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                sheet = create_animation_sheet(root, "Hero", "red cape swordsman", "character", "idle", "east", "pixel_art", "openai_api", "/Game/UIM/Pixels", columns=2, rows=1, cell_size=64)

            self.assertGreaterEqual(int(captured["edit_many_calls"]), 2)
            self.assertNotIn("mirroredFrom", anchor.processing["specialized"])
            self.assertNotIn("mirroredFrom", sheet.processing["specialized"])
            reference_images = anchor.processing["specialized"]["referenceImages"]
            self.assertIn("anchor_south", reference_images[0])
            self.assertIn("anchor_west", reference_images[1])
            self.assertIn("anchor_grid_east", reference_images[2])
            self.assertIn("Image 2 is the approved WEST-facing side anchor", anchor.processing["specialized"]["prompt"])
            self.assertIn("EAST-facing", str(captured["prompt"]))

    def test_independent_east_anchor_requires_west_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit):
                create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "south", "pixel_art", "openai_api", "/Game/UIM/Pixels")

            with self.assertRaisesRegex(ValueError, "Generate anchor:west before independent directional anchor:east"):
                create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "east", "pixel_art", "openai_api", "/Game/UIM/Pixels")

    def test_south_anchor_can_use_grid_without_concept_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            captured: dict[str, str | Path] = {}

            def fake_edit(_provider, prompt: str, image_path: Path, output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
                captured["image_path"] = image_path
                captured["size"] = size
                captured["prompt"] = prompt
                return _fake_generate(_provider, prompt, output_path, size=size, quality=quality, model=model)

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.edit", fake_edit):
                manifest = create_pixel_anchor(
                    root,
                    "Hero",
                    "red cape swordsman",
                    "character",
                    "south",
                    "pixel_art",
                    "openai_api",
                    "/Game/UIM/Pixels",
                    logical_frame_size="128x128",
                    output_size="512x512",
                )

            self.assertIn("anchor_grid_south", captured["image_path"].name)
            self.assertEqual(captured["size"], "512x512")
            self.assertNotIn("conceptUsedAsImageReference", manifest.processing["specialized"])
            self.assertEqual(manifest.processing["specialized"]["logicalFrameSize"], "128x128")
            self.assertEqual(manifest.processing["specialized"]["outputSize"], "512x512")
            self.assertEqual(manifest.processing["specialized"]["anchorScale"], 4)
            self.assertIn("128x128 logical pixel grid", str(captured["prompt"]))
            self.assertIn("4x4 same-color block", str(captured["prompt"]))
            self.assertEqual(manifest.processing["specialized"]["logicalGridSnap"]["scale"], 4)

    def test_south_anchor_uses_concept_and_grid_reference_when_concept_path_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            concept_path = root / "assets" / "hero" / "generated" / "concept.png"
            _fake_image(concept_path)
            captured: dict[str, str | Path] = {}

            def fake_edit_many(_provider, prompt: str, image_paths: list[Path], output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
                captured["image_paths"] = image_paths
                captured["prompt"] = prompt
                return _fake_generate(_provider, prompt, output_path, size=size, quality=quality, model=model)

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.edit_many", fake_edit_many):
                manifest = create_pixel_anchor(
                    root,
                    "Hero",
                    "red cape swordsman",
                    "character",
                    "south",
                    "pixel_art",
                    "openai_api",
                    "/Game/UIM/Pixels",
                    concept_path,
                    logical_frame_size="128x128",
                    output_size="512x512",
                )

            image_paths = captured["image_paths"]
            self.assertIsInstance(image_paths, list)
            self.assertEqual(image_paths[0], concept_path)
            self.assertIn("anchor_grid_south", image_paths[1].name)
            self.assertIn("concept art", str(captured["prompt"]))
            self.assertIn("Do not copy Image 1 pose", str(captured["prompt"]))
            self.assertTrue(manifest.processing["specialized"]["conceptUsedAsImageReference"])
            self.assertEqual(manifest.processing["specialized"]["conceptPath"], concept_path.relative_to(root).as_posix())
            self.assertEqual(manifest.processing["specialized"]["referenceImages"][0], concept_path.relative_to(root).as_posix())

    def test_anchor_output_is_snapped_to_logical_pixel_grid(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            def fake_edit(_provider, _prompt: str, _image_path: Path, output_path: Path, *, size: str = "512x512", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
                image = Image.new("RGBA", (512, 512), (255, 0, 255, 255))
                for y in range(512):
                    for x in range(512):
                        image.putpixel((x, y), ((x + y) % 255, (x * 3) % 255, (y * 5) % 255, 255))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(output_path)
                return ImageGenerationResult(output_path=output_path, model=model, prompt=_prompt, size=size, quality=quality)

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.edit", fake_edit):
                manifest = create_pixel_anchor(
                    root,
                    "Hero",
                    "red cape swordsman",
                    "character",
                    "south",
                    "pixel_art",
                    "openai_api",
                    "/Game/UIM/Pixels",
                    logical_frame_size="128x128",
                    output_size="512x512",
                )

            output = root / manifest.files[0].path
            with Image.open(output) as image:
                rgba = image.convert("RGBA")
                self.assertLessEqual(len(set(rgba.getdata())), 32)
                expected = rgba.getpixel((0, 0))
                for y in range(4):
                    for x in range(4):
                        self.assertEqual(rgba.getpixel((x, y)), expected)
            self.assertEqual(manifest.processing["specialized"]["logicalGridSnap"]["logicalWidth"], 128)
            self.assertEqual(manifest.processing["specialized"]["logicalGridSnap"]["paletteColors"], 32)
            self.assertEqual(manifest.processing["specialized"]["logicalGridSnap"]["backgroundMode"], "opaque_edge_connected_chroma")

    def test_anchor_snap_forces_opaque_chroma_background(self) -> None:
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            def fake_edit(_provider, _prompt: str, _image_path: Path, output_path: Path, *, size: str = "512x512", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
                image = Image.new("RGBA", (512, 512), (0, 0, 0, 255))
                draw = ImageDraw.Draw(image)
                draw.rectangle((210, 120, 302, 390), fill=(238, 184, 80, 255))
                draw.rectangle((0, 0, 80, 80), fill=(0, 0, 0, 0))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(output_path)
                return ImageGenerationResult(output_path=output_path, model=model, prompt=_prompt, size=size, quality=quality)

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.edit", fake_edit):
                manifest = create_pixel_anchor(
                    root,
                    "Hero",
                    "red cape swordsman",
                    "character",
                    "south",
                    "pixel_art",
                    "openai_api",
                    "/Game/UIM/Pixels",
                    logical_frame_size="128x128",
                    output_size="512x512",
                )

            output = root / manifest.files[0].path
            with Image.open(output) as image:
                rgba = image.convert("RGBA")
                self.assertEqual(rgba.getchannel("A").getextrema(), (255, 255))
                self.assertEqual(rgba.getpixel((0, 0)), (255, 0, 255, 255))
                self.assertEqual(rgba.getpixel((511, 511)), (255, 0, 255, 255))
                self.assertNotEqual(rgba.getpixel((256, 256))[:3], (255, 0, 255))
            self.assertEqual(manifest.processing["specialized"]["logicalGridSnap"]["backgroundMode"], "opaque_edge_connected_chroma")

    def test_anchor_output_size_must_match_logical_frame_scale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with self.assertRaisesRegex(ValueError, "integer upscale"):
                create_pixel_anchor(
                    root,
                    "Hero",
                    "red cape swordsman",
                    "character",
                    "south",
                    "pixel_art",
                    "openai_api",
                    "/Game/UIM/Pixels",
                    logical_frame_size="192x192",
                    output_size="1024x1024",
                )

    def test_custom_action_sheet_uses_action_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", _fake_edit_many
            ):
                create_pixel_anchor(root, "Hero", "red cape swordsman", "character", "south", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                sheet = create_animation_sheet(
                    root,
                    "Hero",
                    "red cape swordsman",
                    "character",
                    "dodge_roll",
                    "south",
                    "pixel_art",
                    "openai_api",
                    "/Game/UIM/Pixels",
                    action_description="quick low dodge roll then recover to ready stance",
                )

            prompt = sheet.processing["specialized"]["prompt"]
            self.assertIn("quick low dodge roll", prompt)
            self.assertIn("action animation", prompt)
            self.assertNotIn("subtle idle loop", prompt)

    def test_weapon_generation_prompts_are_object_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", _fake_edit_many
            ):
                concept = create_pixel_concept(root, "Sword", "silver sword with blue gem guard", "weapon", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                anchor = create_pixel_anchor(root, "Sword", "silver sword with blue gem guard", "weapon", "single", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                sheet = create_animation_sheet(root, "Sword", "silver sword with blue gem guard", "weapon", "idle", "single", "pixel_art", "openai_api", "/Game/UIM/Pixels")

            concept_prompt = concept.processing["specialized"]["prompt"]
            anchor_prompt = anchor.processing["specialized"]["prompt"]
            sheet_prompt = sheet.processing["specialized"]["prompt"]
            self.assertIn("single game weapon asset", concept_prompt)
            self.assertIn("grip/handle orientation", concept_prompt)
            self.assertNotIn("full-body", concept_prompt)
            self.assertNotIn("face", concept_prompt.lower())
            self.assertNotIn("personality", concept_prompt.lower())
            self.assertIn("single pixel-art weapon anchor", anchor_prompt)
            self.assertIn("no character", anchor_prompt)
            self.assertIn("no hand", anchor_prompt)
            self.assertIn("no text", anchor_prompt)
            self.assertIn("same single weapon", sheet_prompt)
            self.assertNotIn("game character", sheet_prompt)

    def test_decoration_generation_prompts_are_prop_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", _fake_edit_many
            ):
                concept = create_pixel_concept(root, "Crystal", "glowing crystal pillar on a stone base", "decoration", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                anchor = create_pixel_anchor(root, "Crystal", "glowing crystal pillar on a stone base", "decoration", "single", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                sheet = create_animation_sheet(root, "Crystal", "glowing crystal pillar on a stone base", "decoration", "idle", "single", "pixel_art", "openai_api", "/Game/UIM/Pixels")

            concept_prompt = concept.processing["specialized"]["prompt"]
            anchor_prompt = anchor.processing["specialized"]["prompt"]
            sheet_prompt = sheet.processing["specialized"]["prompt"]
            self.assertIn("single placeable decoration", concept_prompt)
            self.assertIn("footprint", concept_prompt)
            self.assertNotIn("full-body", concept_prompt)
            self.assertNotIn("face", concept_prompt.lower())
            self.assertNotIn("personality", concept_prompt.lower())
            self.assertIn("single pixel-art decoration prop anchor", anchor_prompt)
            self.assertIn("no character", anchor_prompt)
            self.assertIn("no hand", anchor_prompt)
            self.assertIn("no text", anchor_prompt)
            self.assertIn("same single decoration", sheet_prompt)
            self.assertNotIn("game character", sheet_prompt)

    def test_tilemap_does_not_use_pixel_image_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with self.assertRaisesRegex(ValueError, "Tilemap assets do not use pixel image generation"):
                create_pixel_concept(root, "Tiles", "grass and cliffs", "tilemap", "pixel_art", "openai_api", "/Game/UIM/Tiles")

    def test_pixel_generation_prompts_do_not_include_asset_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            asset_name = "Forbidden Asset Name"
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit_many", _fake_edit_many
            ):
                concept = create_pixel_concept(root, asset_name, "red cape swordsman", "character", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                south = create_pixel_anchor(root, asset_name, "red cape swordsman", "character", "south", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                west = create_pixel_anchor(root, asset_name, "red cape swordsman", "character", "west", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                north = create_pixel_anchor(root, asset_name, "red cape swordsman", "character", "north", "pixel_art", "openai_api", "/Game/UIM/Pixels")
                sheet = create_animation_sheet(root, asset_name, "red cape swordsman", "character", "idle", "west", "pixel_art", "openai_api", "/Game/UIM/Pixels")

            prompts = [
                concept.processing["specialized"]["prompt"],
                south.processing["specialized"]["prompt"],
                west.processing["specialized"]["prompt"],
                north.processing["specialized"]["prompt"],
                sheet.processing["specialized"]["prompt"],
            ]
            for prompt in prompts:
                self.assertNotIn(asset_name, prompt)
            self.assertIn("facing left in profile", west.processing["specialized"]["prompt"])
            self.assertIn("no frontal face or front-facing torso", west.processing["specialized"]["prompt"])
            self.assertIn("facing away from the camera, back view", north.processing["specialized"]["prompt"])
            self.assertIn("no visible front face or front-facing torso", north.processing["specialized"]["prompt"])

    def test_ui_generation_prompts_do_not_include_asset_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            asset_name = "Forbidden UI Asset"
            captured_prompts: list[str] = []

            def fake_generate(_provider, prompt: str, output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
                captured_prompts.append(prompt)
                return _fake_generate(_provider, prompt, output_path, size=size, quality=quality, model=model)

            def fake_edit(_provider, prompt: str, image_path: Path, output_path: Path, *, size: str = "1024x1024", quality: str = "auto", model: str = "gpt-image-2") -> ImageGenerationResult:
                captured_prompts.append(prompt)
                return _fake_edit(_provider, prompt, image_path, output_path, size=size, quality=quality, model=model)

            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", fake_edit
            ):
                concept = create_ui_concept(root, asset_name, "pixel RPG", "bottom skill bar", "semi_realistic_ui", "openai_api", "/Game/UIM/UI")
                create_ui_widget(root, asset_name, "button", "primary action button", root / concept.files[0].path, "semi_realistic_ui", "openai_api", "/Game/UIM/UI")

            self.assertGreaterEqual(len(captured_prompts), 2)
            for prompt in captured_prompts:
                self.assertNotIn(asset_name, prompt)

    def test_normalize_spritesheet_outputs_runtime_sheet_and_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            _fake_image(sheet, (512, 256))

            manifest = normalize_spritesheet(root, sheet, "Hero", "idle", 2, 1, 256, 256, "pixel_art", "/Game/UIM/Pixels", pixel_restore_mode="none")

            self.assertEqual(manifest.asset_type, "spritesheet")
            self.assertEqual(len(manifest.frames), 2)
            self.assertEqual(manifest.frames[0].pivot, (0.5, 1.0))
            self.assertTrue((root / manifest.files[0].path).exists())
            self.assertTrue((root / manifest.files[1].path).exists())

    def test_normalize_spritesheet_preview_gif_uses_stable_full_frame_canvas(self) -> None:
        from PIL import Image, ImageSequence

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
            for x in range(4, 28):
                for y in range(20, 52):
                    image.putpixel((x, y), (40, 90, 210, 255))
            for x in range(100, 124):
                for y in range(20, 52):
                    image.putpixel((x, y), (210, 90, 40, 255))
            image.save(sheet)

            manifest = normalize_spritesheet(root, sheet, "Hero", "idle", 2, 1, 64, 64, "pixel_art", "/Game/UIM/Pixels", chroma_key=None, pixel_restore_mode="none")
            preview_path = root / next(file.path for file in manifest.files if file.role == "preview:idle")

            with Image.open(preview_path) as preview:
                frames = [frame.convert("RGBA") for frame in ImageSequence.Iterator(preview)]
            self.assertEqual([frame.size for frame in frames], [(64, 64), (64, 64)])
            self.assertTrue(all(frame.getpixel((0, 0))[3] == 255 for frame in frames))

    def test_normalize_spritesheet_can_record_direction_specific_runtime_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            _fake_image(sheet, (128, 64))

            manifest = normalize_spritesheet(root, sheet, "Hero", "idle", 2, 1, 64, 64, "pixel_art", "/Game/UIM/Pixels", direction="south", pixel_restore_mode="none")

            self.assertEqual([file.role for file in manifest.files], ["runtime:idle:south", "preview:idle:south"])
            self.assertEqual(manifest.processing["normalization"]["direction"], "south")
            self.assertEqual(manifest.processing["normalization"]["pipelineVersion"], "pixel-sheet-v2")

    def test_normalize_spritesheet_aligns_bottom_anchor_not_bbox_center(self) -> None:
        from PIL import Image

        def paint_frame(image: object, offset_x: int, arm_side: str) -> None:
            for x in range(offset_x + 28, offset_x + 37):
                for y in range(20, 58):
                    image.putpixel((x, y), (40, 90, 210, 255))
            for x in range(offset_x + 30, offset_x + 35):
                for y in range(56, 62):
                    image.putpixel((x, y), (20, 40, 80, 255))
            arm_range = range(offset_x + 10, offset_x + 28) if arm_side == "left" else range(offset_x + 37, offset_x + 58)
            for x in arm_range:
                for y in range(36, 44):
                    image.putpixel((x, y), (210, 90, 40, 255))

        def bottom_anchor_x(frame: object) -> float:
            alpha = frame.getchannel("A")
            box = alpha.getbbox()
            self.assertIsNotNone(box)
            left, top, right, bottom = box
            xs = []
            for y in range(max(top, bottom - 8), bottom):
                for x in range(left, right):
                    if alpha.getpixel((x, y)) > 0:
                        xs.append(x)
            return (min(xs) + max(xs)) / 2

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
            paint_frame(image, 0, "left")
            paint_frame(image, 64, "right")
            image.save(sheet)

            manifest = normalize_spritesheet(root, sheet, "Hero", "idle", 2, 1, 64, 64, "pixel_art", "/Game/UIM/Pixels", chroma_key=None, pixel_restore_mode="none")
            runtime_path = root / next(file.path for file in manifest.files if file.role == "runtime:idle")

            with Image.open(runtime_path) as runtime:
                rgba = runtime.convert("RGBA")
                first = rgba.crop((0, 0, 64, 64))
                second = rgba.crop((64, 0, 128, 64))
            self.assertEqual(bottom_anchor_x(first), bottom_anchor_x(second))
            self.assertEqual(manifest.processing["normalization"]["layoutMode"], "preserve_cell_origin")

    def test_spritesheet_cutout_runs_rembg_per_frame_and_preserves_grid(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (128, 64), (255, 0, 255, 255))
            for offset_x in (16, 80):
                for x in range(offset_x, offset_x + 24):
                    for y in range(18, 46):
                        image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)
            calls: list[Path] = []
            progress_events: list[str] = []

            def fake_remove(_adapter: object, input_path: Path, output_path: Path) -> object:
                calls.append(input_path)
                with Image.open(input_path) as frame_image:
                    rgba = frame_image.convert("RGBA")
                    cleaned = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
                    for x in range(rgba.width):
                        for y in range(rgba.height):
                            pixel = rgba.getpixel((x, y))
                            if pixel[:3] != (255, 0, 255):
                                cleaned.putpixel((x, y), pixel)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    cleaned.save(output_path)
                return object()

            with patch("uim_core.specialized.RembgAdapter.available", return_value=True), patch("uim_core.specialized.RembgAdapter.remove_background", fake_remove):
                manifest = create_spritesheet_cutout(
                    root,
                    sheet,
                    "Hero",
                    "attack",
                    "west",
                    2,
                    1,
                    64,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    "isnet-general-use",
                    progress_events.append,
                )

            output = root / manifest.files[0].path
            self.assertEqual(len(calls), 2)
            self.assertEqual(output.exists(), True)
            with Image.open(output) as output_image:
                self.assertEqual(output_image.size, (128, 64))
                self.assertEqual(output_image.getpixel((0, 0))[3], 0)
                self.assertGreater(output_image.getpixel((20, 20))[3], 0)
                self.assertGreater(output_image.getpixel((84, 20))[3], 0)
            self.assertEqual(manifest.files[0].role, "cutout:attack:west")
            self.assertEqual(manifest.processing["cutout"]["mode"], "per-frame-hybrid-preserve-cell-origin")
            self.assertEqual(manifest.processing["cutout"]["maskMode"], "hybrid")
            self.assertTrue(any(event.startswith("pixel.cutout.frame done index=2/2 visible=") for event in progress_events))

    def test_normalize_accepts_high_resolution_source_cells_and_outputs_runtime_cells(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input_highres.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (256, 128), (255, 0, 255, 255))
            for offset_x in (24, 152):
                for x in range(offset_x, offset_x + 64):
                    for y in range(28, 104):
                        image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)

            manifest = normalize_spritesheet(
                root,
                sheet,
                "Hero",
                "idle",
                2,
                1,
                64,
                64,
                "pixel_art",
                "/Game/UIM/Pixels",
                pixel_restore_mode="none",
                source_cell_width=128,
                source_cell_height=128,
            )

            runtime_path = root / next(file.path for file in manifest.files if file.role == "runtime:idle")
            with Image.open(runtime_path) as runtime:
                self.assertEqual(runtime.size, (128, 64))
                self.assertGreater(runtime.convert("RGBA").getpixel((16, 20))[3], 0)
            self.assertEqual(manifest.processing["normalization"]["sourceCellWidth"], 128)
            self.assertEqual(manifest.processing["normalization"]["cellWidth"], 64)

    def test_normalize_infers_grid_when_columns_and_rows_are_omitted(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input_highres.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (256, 128), (255, 0, 255, 255))
            for offset_x in (24, 152):
                for x in range(offset_x, offset_x + 64):
                    for y in range(28, 104):
                        image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)

            manifest = normalize_spritesheet(
                root,
                sheet,
                "Hero",
                "idle",
                0,
                0,
                64,
                64,
                "pixel_art",
                "/Game/UIM/Pixels",
                pixel_restore_mode="none",
                source_cell_width=128,
                source_cell_height=128,
            )

            runtime_path = root / next(file.path for file in manifest.files if file.role == "runtime:idle")
            with Image.open(runtime_path) as runtime:
                self.assertEqual(runtime.size, (128, 64))
            self.assertEqual(manifest.processing["normalization"]["columns"], 2)
            self.assertEqual(manifest.processing["normalization"]["rows"], 1)
            self.assertEqual(manifest.processing["normalization"]["requestedColumns"], 0)
            self.assertEqual(manifest.processing["normalization"]["requestedRows"], 0)

    def test_normalize_infers_legacy_runtime_cell_grid_when_source_size_mismatches(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "legacy_video_sheet.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (320, 512), (255, 0, 255, 255))
            for row in range(8):
                for column in range(5):
                    x0 = column * 64 + 20
                    y0 = row * 64 + 24
                    for x in range(x0, x0 + 20):
                        for y in range(y0, y0 + 28):
                            image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)

            manifest = normalize_spritesheet(
                root,
                sheet,
                "Hero",
                "walk",
                5,
                2,
                64,
                64,
                "pixel_art",
                "/Game/UIM/Pixels",
                pixel_restore_mode="none",
                source_cell_width=128,
                source_cell_height=128,
            )

            runtime_path = root / next(file.path for file in manifest.files if file.role == "runtime:walk")
            with Image.open(runtime_path) as runtime:
                self.assertEqual(runtime.size, (320, 512))
            self.assertEqual(manifest.processing["normalization"]["sourceCellWidth"], 64)
            self.assertEqual(manifest.processing["normalization"]["columns"], 5)
            self.assertEqual(manifest.processing["normalization"]["rows"], 8)
            self.assertEqual(manifest.processing["normalization"]["requestedRows"], 2)

    def test_normalize_reports_progress_and_honors_cancel(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (128, 64), (255, 0, 255, 255)).save(sheet)
            events: list[str] = []

            normalize_spritesheet(
                root,
                sheet,
                "Hero",
                "idle",
                2,
                1,
                64,
                64,
                "pixel_art",
                "/Game/UIM/Pixels",
                pixel_restore_mode="none",
                progress=events.append,
            )

            self.assertTrue(any(event.startswith("pixel.normalize.start frames=2") for event in events))
            self.assertTrue(any(event == "pixel.normalize.frame start index=1/2" for event in events))
            self.assertTrue(any(event.startswith("pixel.normalize.frame done index=2/2") for event in events))
            self.assertTrue(any(event.startswith("pixel.normalize.done frames=2") for event in events))

            cancel_events: list[str] = []
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                normalize_spritesheet(
                    root,
                    sheet,
                    "Hero",
                    "idle",
                    2,
                    1,
                    64,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    pixel_restore_mode="none",
                    progress=cancel_events.append,
                    is_cancelled=lambda: len([event for event in cancel_events if "frame done" in event]) >= 1,
                )

    def test_normalize_runs_unfake_per_source_cell_not_whole_sheet(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input_highres.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (256, 128), (255, 0, 255, 255))
            for offset_x in (24, 152):
                for x in range(offset_x, offset_x + 64):
                    for y in range(28, 104):
                        image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)
            call_sizes: list[tuple[int, int]] = []

            def fake_restore(input_path: Path, output_path: Path, _mode: str) -> Path:
                with Image.open(input_path) as input_image:
                    call_sizes.append(input_image.size)
                    input_image.convert("RGBA").save(output_path)
                return output_path

            with patch("uim_core.specialized.run_unfake_restore", fake_restore):
                manifest = normalize_spritesheet(
                    root,
                    sheet,
                    "Hero",
                    "idle",
                    2,
                    1,
                    64,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    pixel_restore_mode="safe",
                    source_cell_width=128,
                    source_cell_height=128,
                )

            runtime_path = root / next(file.path for file in manifest.files if file.role == "runtime:idle")
            with Image.open(runtime_path) as runtime:
                self.assertEqual(runtime.size, (128, 64))
            self.assertEqual(call_sizes, [(128, 128), (128, 128)])
            self.assertIn("restoredFramesDir", manifest.processing["normalization"])

    def test_normalize_defaults_to_unfake_safe(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (64, 64), (255, 0, 255, 255)).save(sheet)
            modes: list[str] = []

            def fake_restore(input_path: Path, output_path: Path, mode: str) -> Path:
                modes.append(mode)
                with Image.open(input_path) as input_image:
                    input_image.convert("RGBA").save(output_path)
                return output_path

            with patch("uim_core.specialized.run_unfake_restore", fake_restore):
                manifest = normalize_spritesheet(root, sheet, "Hero", "idle", 1, 1, 64, 64, "pixel_art", "/Game/UIM/Pixels")

            self.assertEqual(modes, ["safe"])
            self.assertEqual(manifest.processing["normalization"]["pixelRestoreMode"], "safe")

    def test_spritesheet_cutout_expands_rows_to_match_source_sheet_height(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (128, 128), (255, 0, 255, 255))
            for offset_x, offset_y in ((16, 18), (80, 18), (16, 82), (80, 82)):
                for x in range(offset_x, offset_x + 24):
                    for y in range(offset_y, offset_y + 28):
                        image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)
            calls: list[Path] = []

            def fake_remove(_adapter: object, input_path: Path, output_path: Path) -> object:
                calls.append(input_path)
                with Image.open(input_path) as frame_image:
                    rgba = frame_image.convert("RGBA")
                    cleaned = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
                    for x in range(rgba.width):
                        for y in range(rgba.height):
                            pixel = rgba.getpixel((x, y))
                            if pixel[:3] != (255, 0, 255):
                                cleaned.putpixel((x, y), pixel)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    cleaned.save(output_path)
                return object()

            with patch("uim_core.specialized.RembgAdapter.available", return_value=True), patch("uim_core.specialized.RembgAdapter.remove_background", fake_remove):
                manifest = create_spritesheet_cutout(
                    root,
                    sheet,
                    "Hero",
                    "walk",
                    "west",
                    2,
                    1,
                    64,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    "isnet-general-use",
                )

            output = root / manifest.files[0].path
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(manifest.frames), 4)
            self.assertEqual(manifest.processing["cutout"]["requestedRows"], 1)
            self.assertEqual(manifest.processing["cutout"]["rows"], 2)
            with Image.open(output) as output_image:
                self.assertEqual(output_image.size, (128, 128))
                self.assertGreater(output_image.getpixel((20, 88))[3], 0)

    def test_spritesheet_cutout_preserves_original_cell_pixels_and_position(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (64, 64), (255, 0, 255, 255))
            for x in range(12, 28):
                for y in range(18, 44):
                    image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)

            def fake_remove(_adapter: object, input_path: Path, output_path: Path) -> object:
                with Image.open(input_path) as frame_image:
                    rgba = frame_image.convert("RGBA")
                    shifted = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
                    for x in range(12, 28):
                        for y in range(18, 44):
                            shifted.putpixel((x, y), (255, 0, 0, 255))
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shifted.save(output_path)
                return object()

            with patch("uim_core.specialized.RembgAdapter.available", return_value=True), patch("uim_core.specialized.RembgAdapter.remove_background", fake_remove):
                manifest = create_spritesheet_cutout(
                    root,
                    sheet,
                    "Hero",
                    "idle",
                    "south",
                    1,
                    1,
                    64,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                )

            output = root / manifest.files[0].path
            with Image.open(output) as output_image:
                rgba = output_image.convert("RGBA")
                self.assertEqual(rgba.getpixel((12, 18)), (40, 90, 210, 255))
                self.assertEqual(rgba.getpixel((27, 43)), (40, 90, 210, 255))
                self.assertEqual(rgba.getpixel((5, 5))[3], 0)

    def test_spritesheet_cutout_classic_mode_uses_edge_connected_background_without_rembg(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (64, 64), (255, 0, 255, 255))
            for x in range(20, 44):
                for y in range(18, 48):
                    image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)

            with patch("uim_core.specialized.RembgAdapter.remove_background", side_effect=AssertionError("classic mode must not call rembg")):
                manifest = create_spritesheet_cutout(
                    root,
                    sheet,
                    "Hero",
                    "idle",
                    "south",
                    1,
                    1,
                    64,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    mask_mode="classic",
                )

            output = root / manifest.files[0].path
            with Image.open(output) as output_image:
                self.assertEqual(output_image.getpixel((0, 0))[3], 0)
                self.assertEqual(output_image.getpixel((24, 24))[3], 255)
            self.assertEqual(manifest.processing["cutout"]["maskMode"], "classic")

    def test_pixel_mask_decontaminates_white_edge_rgb_without_shifting_subject(self) -> None:
        from PIL import Image

        image = Image.new("RGBA", (32, 32), (255, 0, 255, 255))
        for x in range(10, 22):
            for y in range(9, 23):
                color = (255, 255, 255, 255) if x in (10, 21) or y in (9, 22) else (40, 90, 210, 255)
                image.putpixel((x, y), color)

        cutout, report = apply_pixel_mask(image, mode="classic", decontaminate_edges=True)

        self.assertEqual(report["visiblePixels"], 168)
        self.assertEqual(cutout.getpixel((10, 10))[:3], (40, 90, 210))
        self.assertEqual(cutout.getpixel((10, 10))[3], 255)
        self.assertEqual(cutout.getpixel((9, 10))[3], 0)

    def test_hybrid_mask_removes_low_alpha_background_colored_internal_holes(self) -> None:
        from PIL import Image

        image = Image.new("RGBA", (32, 32), (255, 0, 255, 255))
        for x in range(8, 24):
            for y in range(8, 24):
                image.putpixel((x, y), (40, 90, 210, 255))
        for x in range(14, 18):
            for y in range(14, 22):
                image.putpixel((x, y), (255, 0, 255, 255))

        rembg_alpha = Image.new("L", (32, 32), 0)
        for x in range(8, 24):
            for y in range(8, 24):
                rembg_alpha.putpixel((x, y), 255)
        for x in range(14, 18):
            for y in range(14, 22):
                rembg_alpha.putpixel((x, y), 244)

        cutout, report = apply_pixel_mask(image, rembg_alpha=rembg_alpha, mode="hybrid", decontaminate_edges=False)

        self.assertEqual(cutout.getpixel((12, 12))[3], 255)
        self.assertEqual(cutout.getpixel((15, 16))[3], 0)
        self.assertGreater(report["removedBackgroundLeakPixels"], 0)

    def test_normalize_spritesheet_writes_qa_and_preserves_exact_output_size(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            sheet = root / "assets" / "hero" / "generated" / "input.png"
            sheet.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (140, 80), (0, 0, 0, 0))
            for x in range(8, 24):
                for y in range(16, 46):
                    image.putpixel((x, y), (40, 90, 210, 255))
            image.save(sheet)

            manifest = normalize_spritesheet(root, sheet, "Hero", "idle", 2, 1, 64, 64, "pixel_art", "/Game/UIM/Pixels", chroma_key=None, direction="south", pixel_restore_mode="none")
            output = root / next(file.path for file in manifest.files if file.role == "runtime:idle:south")
            qa_path = root / manifest.processing["normalization"]["qaReport"]

            with Image.open(output) as output_image:
                self.assertEqual(output_image.size, (128, 64))
            self.assertTrue(qa_path.exists())
            self.assertEqual(manifest.processing["normalization"]["qaSummary"]["emptyFrameCount"], 1)

    def test_unfake_restore_reports_missing_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.png"
            output = Path(tmp) / "output.png"
            _fake_image(source)
            with patch("uim_core.pixel_postprocess._find_unfake_executable", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "unfake CLI is not available"):
                    run_unfake_restore(source, output, "safe")

    def test_tilemap_47_manifest_records_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            tileset = root / "assets" / "grass" / "generated" / "tiles.png"
            _fake_image(tileset, (256, 192))

            manifest = create_tilemap_47_manifest(root, "Grass Terrain", tileset, 32, "pixel_art", "/Game/UIM/Tiles")

            self.assertEqual(len(TILEMAP_47_IDS), 47)
            self.assertEqual(len(manifest.frames), 47)
            self.assertEqual(manifest.processing["tilemap"]["standard"], "47-tile")

    def test_tilemap_dual_grid_manifest_records_mask_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            tileset = root / "assets" / "grass" / "generated" / "dual_grid.png"
            _fake_image(tileset, (128, 128))

            manifest = create_tilemap_dual_grid_manifest(root, "Grass Terrain", tileset, 32, "pixel_art", "/Game/UIM/Tiles")

            self.assertEqual(len(TILEMAP_DUAL_GRID_16_IDS), 16)
            self.assertEqual(len(manifest.frames), 16)
            self.assertEqual(manifest.frames[15].name, "mask_15")
            self.assertEqual(manifest.frames[15].x, 96)
            self.assertEqual(manifest.frames[15].y, 96)
            self.assertEqual(manifest.files[0].role, "tileset:dual-grid-16")
            self.assertEqual(manifest.processing["tilemap"]["standard"], "dual-grid-16")
            self.assertEqual(manifest.processing["tilemap"]["layout"]["columns"], 4)
            self.assertEqual(manifest.processing["tilemap"]["maskBits"], {"NW": 1, "NE": 2, "SW": 4, "SE": 8})

    def test_tilemap_manifest_rejects_missing_tileset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with self.assertRaises(ValueError):
                create_tilemap_47_manifest(root, "Grass Terrain", root / "missing.png", 32, "pixel_art", "/Game/UIM/Tiles")

    def test_openai_edit_many_posts_array_images_before_mask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hard_source = root / "hard.png"
            style_seed = root / "seed.png"
            material_pair = root / "materials.png"
            boundary_mask = root / "mask.png"
            output = root / "output.png"
            for path in (hard_source, style_seed, material_pair, boundary_mask):
                _fake_image(path)
            captured: dict[str, object] = {}

            def fake_post(url: str, *, headers: dict[str, str], data: dict[str, str], files: list[tuple[str, tuple[str, object, str]]], proxies: object, timeout: int) -> _FakeOpenAIEditResponse:
                captured["url"] = url
                captured["fields"] = [field for field, _payload in files]
                captured["filenames"] = [payload[0] for _field, payload in files]
                captured["data"] = data
                captured["timeout"] = timeout
                return _FakeOpenAIEditResponse()

            with patch("requests.post", fake_post):
                result = OpenAIImageProvider(api_key="key", base_url="https://example.test").edit_many(
                    "refine boundary",
                    [hard_source, style_seed, material_pair],
                    output,
                    size="1600x960",
                    mask_path=boundary_mask,
                )

            self.assertEqual(captured["url"], "https://example.test/images/edits")
            self.assertEqual(captured["fields"], ["image[]", "image[]", "image[]", "mask"])
            self.assertEqual(captured["filenames"], ["hard.png", "seed.png", "materials.png", "mask.png"])
            self.assertEqual(captured["data"]["size"], "1600x960")
            self.assertEqual(result.request_id, "req-edit")
            self.assertTrue(output.exists())

    def test_tilemap_seed_and_compose_are_separate_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate):
                seed_manifest = create_tilemap_seed_concept(root, "Grass Terrain", "grass into dirt", "47-tile", 32, "pixel_art", "openai_api", "/Game/UIM/Tiles")

            self.assertEqual(seed_manifest.asset_type, "texture")
            self.assertEqual(seed_manifest.files[0].role, "seed:tilemap-3x3")
            calls: list[dict[str, object]] = []

            def fake_generate_image(
                prompt: str,
                output_path: Path,
                image_provider: str,
                *,
                size: str = "1024x1024",
                reference_path: Path | None = None,
                reference_paths: list[Path] | None = None,
                mask_path: Path | None = None,
            ) -> ImageGenerationResult:
                calls.append(
                    {
                        "prompt": prompt,
                        "image_provider": image_provider,
                        "reference_path": reference_path,
                        "reference_paths": reference_paths,
                        "mask_path": mask_path,
                        "size": size,
                    }
                )
                if "materials" in output_path.name:
                    from PIL import Image

                    image = Image.new("RGBA", (1536, 768), (180, 130, 72, 255))
                    image.paste(Image.new("RGBA", (768, 768), (42, 150, 54, 255)), (768, 0))
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    image.save(output_path)
                else:
                    _fake_image(output_path, (1600, 960))
                return ImageGenerationResult(output_path=output_path, model="fake-model", prompt=prompt, size=size, quality="auto", stream_events=[f"fake {len(calls)} event"])

            with patch("uim_core.specialized._generate_image", fake_generate_image):
                composed = create_tilemap_from_seed_manifest(root, "Grass Terrain", root / seed_manifest.files[0].path, "grass into dirt", "dual-grid-16", 32, "pixel_art", "openai_api", "/Game/UIM/Tiles")
            roles = {file.role for file in composed.files}
            self.assertIn("tileset:dual-grid-16", roles)
            self.assertIn("source:tilemap:materials", roles)
            self.assertIn("source:tilemap:wang-5x3-hard", roles)
            self.assertIn("mask:tilemap:wang-5x3-boundary", roles)
            self.assertIn("source:tilemap:wang-5x3", roles)
            self.assertIn("preview:tilemap:dual-grid-16", roles)
            self.assertNotIn("tileset:47", roles)
            seed_file = next(file for file in composed.files if file.role == "seed:tilemap-3x3")
            material_file = next(file for file in composed.files if file.role == "source:tilemap:materials")
            hard_file = next(file for file in composed.files if file.role == "source:tilemap:wang-5x3-hard")
            mask_file = next(file for file in composed.files if file.role == "mask:tilemap:wang-5x3-boundary")
            source_file = next(file for file in composed.files if file.role == "source:tilemap:wang-5x3")
            self.assertEqual(composed.processing["tilemap"]["source"], "ai-materials-programmatic-wang-refined")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["image_provider"], "openai_api")
            self.assertEqual(calls[0]["size"], "1536x768")
            self.assertEqual(calls[0]["reference_path"], root / seed_file.path)
            self.assertIsNone(calls[0]["mask_path"])
            self.assertIn("2-cell horizontal", str(calls[0]["prompt"]))
            self.assertIn("no 5x3 Wang source", str(calls[0]["prompt"]))
            self.assertEqual(calls[1]["size"], "1600x960")
            self.assertIsNone(calls[1]["reference_path"])
            self.assertEqual(calls[1]["reference_paths"], [root / hard_file.path, root / seed_file.path, root / material_file.path])
            self.assertEqual(calls[1]["mask_path"], root / mask_file.path)
            self.assertIn("Refine the boundary band", str(calls[1]["prompt"]))
            self.assertIn("geometry is mandatory", str(calls[1]["prompt"]))
            self.assertIn("materialPairPath", composed.processing["tilemap"])
            self.assertIn("hardWangSourcePath", composed.processing["tilemap"])
            self.assertIn("boundaryMaskPath", composed.processing["tilemap"])
            self.assertIn("aiRefinedWangSourcePath", composed.processing["tilemap"])
            self.assertIn("wangSourcePath", composed.processing["tilemap"])
            self.assertEqual(composed.processing["tilemap"]["materialPairPath"], material_file.path)
            self.assertEqual(composed.processing["tilemap"]["hardWangSourcePath"], hard_file.path)
            self.assertEqual(composed.processing["tilemap"]["boundaryMaskPath"], mask_file.path)
            self.assertEqual(composed.processing["tilemap"]["wangSourcePath"], source_file.path)
            self.assertEqual(composed.processing["tilemap"]["sourceCleanup"], "boundary-refine-mask-guided-wang")
            self.assertEqual(composed.processing["tilemap"]["referencePurpose"], "style-only")
            self.assertEqual(composed.processing["tilemap"]["assembly"], "wang-5x3-half-quarter")
            self.assertEqual(composed.processing["tilemap"]["layout"]["columns"], 4)
            self.assertEqual(composed.processing["tilemap"]["streamEvents"], ["fake 1 event", "fake 2 event"])

    def test_tilemap_wang_source_cleanup_forces_mask_geometry(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tile_size = 32
            source_path = Path(tmp) / "bad_source.png"
            output_path = Path(tmp) / "cleaned_source.png"
            source = Image.new("RGBA", (5 * tile_size, 3 * tile_size), (255, 0, 255, 255))
            source.paste(Image.new("RGBA", (tile_size, tile_size), (245, 245, 245, 255)), (3 * tile_size, 2 * tile_size))
            source.paste(Image.new("RGBA", (tile_size, tile_size), (12, 12, 12, 255)), (4 * tile_size, 2 * tile_size))
            source.save(source_path)

            _cleanup_tilemap_wang_source(source_path, output_path, tile_size)

            with Image.open(output_path) as cleaned_image:
                cleaned = cleaned_image.convert("RGBA")
                self.assertEqual(cleaned.getpixel((1, 1)), (245, 245, 245, 255))
                self.assertEqual(cleaned.getpixel((tile_size - 2, tile_size - 2)), (12, 12, 12, 255))
                self.assertNotEqual(cleaned.getpixel((1, 1)), (255, 0, 255, 255))

    def test_tilemap_material_prompt_asks_only_for_full_materials(self) -> None:
        prompt = _tilemap_material_pair_prompt("grass into dirt", "47-tile", 32)

        self.assertIn("2-cell horizontal", prompt)
        self.assertIn("left cell: full outer terrain", prompt)
        self.assertIn("right cell: full primary terrain", prompt)
        self.assertIn("no 5x3 Wang source", prompt)
        self.assertNotIn("draw exactly 47", prompt)

    def test_tilemap_boundary_refine_prompt_locks_geometry(self) -> None:
        prompt = _tilemap_boundary_refine_prompt("grass into dirt", "dual-grid-16", 32)

        self.assertIn("Refine the boundary band", prompt)
        self.assertIn("geometry is mandatory", prompt)
        self.assertIn("do not move the transition line", prompt)
        self.assertIn("full dirt and full grass interiors must remain unchanged", prompt)

    def test_tilemap_hard_wang_source_uses_exact_material_masks(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tile_size = 32
            material_pair = Path(tmp) / "materials.png"
            hard_source = Path(tmp) / "hard.png"
            outer = (180, 130, 72, 255)
            primary = (42, 150, 54, 255)
            image = Image.new("RGBA", (2 * tile_size, tile_size), outer)
            image.paste(Image.new("RGBA", (tile_size, tile_size), primary), (tile_size, 0))
            image.save(material_pair)

            _create_hard_wang_source_from_material_pair(material_pair, hard_source, tile_size)

            with Image.open(hard_source) as source_image:
                source = source_image.convert("RGBA")
                self.assertEqual(source.size, (5 * tile_size, 3 * tile_size))
                self.assertEqual(source.getpixel((1, 1)), outer)
                self.assertEqual(source.getpixel((tile_size - 2, tile_size - 2)), primary)
                self.assertEqual(source.getpixel((4 * tile_size + 8, 2 * tile_size + 8)), primary)
                self.assertEqual(source.getpixel((3 * tile_size + 8, 2 * tile_size + 8)), outer)

    def test_tilemap_boundary_mask_only_opens_transition_band(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tile_size = 32
            mask_path = Path(tmp) / "mask.png"

            _create_tilemap_boundary_mask(mask_path, tile_size)

            with Image.open(mask_path) as mask_image:
                mask = mask_image.convert("RGBA")
                self.assertEqual(mask.size, (5 * tile_size, 3 * tile_size))
                self.assertEqual(mask.getpixel((4 * tile_size + 8, 2 * tile_size + 8))[3], 255)
                self.assertEqual(mask.getpixel((3 * tile_size + 8, 2 * tile_size + 8))[3], 255)
                self.assertEqual(mask.getpixel((tile_size // 2, 12))[3], 0)
                self.assertEqual(mask.getpixel((4, 4))[3], 255)

    def test_tilemap_boundary_cleanup_restores_locked_pixels(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tile_size = 32
            hard_path = Path(tmp) / "hard.png"
            refined_path = Path(tmp) / "refined.png"
            mask_path = Path(tmp) / "mask.png"
            output_path = Path(tmp) / "output.png"
            hard = Image.new("RGBA", (5 * tile_size, 3 * tile_size), (10, 20, 30, 255))
            refined = Image.new("RGBA", hard.size, (250, 20, 200, 255))
            hard.save(hard_path)
            refined.save(refined_path)
            _create_tilemap_boundary_mask(mask_path, tile_size)

            _cleanup_boundary_refined_wang_source(refined_path, hard_path, mask_path, output_path, tile_size)

            with Image.open(output_path) as output_image:
                output = output_image.convert("RGBA")
                self.assertEqual(output.getpixel((4, 4)), (10, 20, 30, 255))
                self.assertEqual(output.getpixel((tile_size // 2, 12)), (250, 20, 200, 255))

    def test_tilemap_wang_47_mask_zero_keeps_center_island(self) -> None:
        from PIL import Image

        tile_size = 32
        primary = (12, 12, 12, 255)
        outer = (245, 245, 245, 255)
        source = Image.new("RGBA", (5 * tile_size, 3 * tile_size), outer)
        for row in range(3):
            for col in range(5):
                quadrants = _wang_source_quadrants_for_cell(col, row)
                tile_x = col * tile_size
                tile_y = row * tile_size
                for y in range(tile_size):
                    for x in range(tile_size):
                        if _is_primary_quadrant_source_pixel(quadrants, x, y, tile_size):
                            source.putpixel((tile_x + x, tile_y + y), primary)

        tile = _compose_wang_47_tile(source, tile_size, 0)

        for point in [(0, 0), (tile_size - 1, 0), (0, tile_size - 1), (tile_size - 1, tile_size - 1)]:
            self.assertEqual(tile.getpixel(point), outer)
        for point in [(20, 20), (11, 20), (20, 11)]:
            self.assertEqual(tile.getpixel(point), primary)

    def test_tilemap_wang_47_uses_expected_quarter_sources(self) -> None:
        tile_size = 32
        source = _mock_wang_source(tile_size)

        full = _compose_wang_47_tile(source, tile_size, _terrain_mask(n=True, e=True, s=True, w=True, ne=True, se=True, sw=True, nw=True))
        self.assertEqual(full.getpixel((4, 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + 4)))

        north = _compose_wang_47_tile(source, tile_size, _terrain_mask(n=True, e=False, s=False, w=False))
        self.assertEqual(north.getpixel((4, 4)), source.getpixel((3 * tile_size + 4, 2 * tile_size + 4)))

        outer = _compose_wang_47_tile(source, tile_size, 0)
        self.assertEqual(outer.getpixel((4, 4)), source.getpixel((3 * tile_size + 4, 2 * tile_size + 4)))
        self.assertEqual(outer.getpixel((20, 20)), source.getpixel((4 * tile_size + 20, 2 * tile_size + 20)))

        inner = _compose_wang_47_tile(source, tile_size, _terrain_mask(n=True, e=True, s=True, w=True, ne=False, se=True, sw=True, nw=True))
        self.assertEqual(inner.getpixel((tile_size - 4, 4)), source.getpixel((4 * tile_size + tile_size - 4, 4)))
        self.assertEqual(inner.getpixel((4, 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + 4)))

    def test_tilemap_wang_dual_grid_uses_transition_quarters(self) -> None:
        tile_size = 32
        source = _mock_wang_source(tile_size)

        empty = _compose_wang_dual_grid_tile(source, tile_size, 0)
        self.assertEqual(empty.getpixel((4, 4)), source.getpixel((3 * tile_size + 4, 2 * tile_size + 4)))

        single_nw = _compose_wang_dual_grid_tile(source, tile_size, 1)
        self.assertEqual(single_nw.getpixel((4, 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + 4)))
        self.assertEqual(single_nw.getpixel((tile_size - 4, tile_size - 4)), source.getpixel((3 * tile_size + tile_size - 4, 2 * tile_size + tile_size - 4)))

        top = _compose_wang_dual_grid_tile(source, tile_size, 3)
        self.assertEqual(top.getpixel((4, 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + 4)))
        self.assertEqual(top.getpixel((tile_size - 4, 4)), source.getpixel((4 * tile_size + tile_size - 4, 2 * tile_size + 4)))

        left = _compose_wang_dual_grid_tile(source, tile_size, 5)
        self.assertEqual(left.getpixel((4, 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + 4)))
        self.assertEqual(left.getpixel((4, tile_size - 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + tile_size - 4)))

        diagonal = _compose_wang_dual_grid_tile(source, tile_size, 9)
        self.assertEqual(diagonal.getpixel((4, 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + 4)))
        self.assertEqual(diagonal.getpixel((tile_size - 4, tile_size - 4)), source.getpixel((4 * tile_size + tile_size - 4, 2 * tile_size + tile_size - 4)))

        three = _compose_wang_dual_grid_tile(source, tile_size, 7)
        self.assertEqual(three.getpixel((tile_size - 4, tile_size - 4)), source.getpixel((3 * tile_size + tile_size - 4, 2 * tile_size + tile_size - 4)))

        full = _compose_wang_dual_grid_tile(source, tile_size, 15)
        self.assertEqual(full.getpixel((4, 4)), source.getpixel((4 * tile_size + 4, 2 * tile_size + 4)))

    def test_tilemap_seed_prompt_describes_style_reference_only(self) -> None:
        prompt = _tilemap_seed_prompt("grass into dirt", "47-tile", 32)

        self.assertIn("style reference only", prompt)
        self.assertIn("not a structural tileset guide", prompt)
        self.assertIn("do not attempt to solve the final 47-tile or dual-grid structure", prompt)
        self.assertNotIn("Fixed 3x3 semantics", prompt)

    def test_tilemap_wang_source_prompt_uses_style_reference_and_structural_guide(self) -> None:
        prompt = _tilemap_wang_source_prompt("grass into dirt", "dual-grid-16", 32)

        self.assertIn("style reference only", prompt)
        self.assertIn("do not copy its layout or geometry", prompt)
        self.assertIn("Wang guide controls structure", prompt)
        self.assertIn("final full tileset will be assembled programmatically", prompt)

    def test_ui_concept_and_widget_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ):
                concept = create_ui_concept(root, "Fantasy HUD", "pixel RPG", "bottom skill bar", "semi_realistic_ui", "openai_api", "/Game/UIM/UI")
                widget = create_ui_widget(root, "Fantasy HUD", "button", "primary action button", root / concept.files[0].path, "semi_realistic_ui", "openai_api", "/Game/UIM/UI")

            self.assertIn("uiConcept", concept.processing)
            self.assertTrue(concept.files[0].path.startswith("ui/concepts/fantasy_hud/"))
            self.assertEqual(validate_manifest(concept), [])
            self.assertEqual(widget.asset_type, "ui_kit")
            self.assertEqual(len([file for file in widget.files if file.role.startswith("ui_widget:button")]), 4)
            self.assertIn("uiConcept", widget.processing)
            self.assertEqual({state.name for state in widget.ui_states}, {"normal", "hover", "pressed", "disabled"})

    def test_import_ui_concept_registers_concept_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            source = Path(tmp) / "concept.png"
            _fake_image(source, (320, 180))

            manifest = import_ui_concept(root, "Fantasy HUD", source, "semi_realistic_ui", "/Game/UIM/UI")

            self.assertEqual(manifest.files[0].role, "ui:concept")
            self.assertTrue(manifest.files[0].path.startswith("ui/concepts/fantasy_hud/"))
            self.assertEqual(manifest.processing["uiConcept"]["source"], "import")
            self.assertTrue((root / manifest.files[0].path).exists())
            index = load_asset_index(root, "fantasy_hud")
            self.assertEqual(index.versions[0].role, "ui:concept")

    def test_import_animation_sheet_registers_sheet_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            source = Path(tmp) / "idle_sheet.png"
            _fake_image(source, (128, 64))

            manifest = import_animation_sheet(root, "Hero", source, "character", "idle", "south", "pixel_art", "/Game/UIM/Pixels", columns=2, rows=1, cell_size=64)

            self.assertEqual(manifest.files[0].role, "sheet:idle:south")
            self.assertEqual(manifest.processing["specialized"]["source"], "import")
            self.assertEqual(len(manifest.frames), 2)
            self.assertTrue((root / manifest.files[0].path).exists())
            index = load_asset_index(root, "hero")
            self.assertEqual(index.versions[0].role, "sheet:idle:south")

    def test_ui_widget_rejects_unknown_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with self.assertRaises(ValueError):
                create_ui_widget(root, "Fantasy HUD", "slider", "unknown widget", None, "semi_realistic_ui", "openai_api", "/Game/UIM/UI")

    def test_codex_oauth_reference_image_uses_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            concept = root / "assets" / "fantasy_hud" / "generated" / "concept.png"
            _fake_image(concept)
            with patch("uim_core.providers.codex_oauth_image.CodexOAuthImageProvider.edit", _fake_edit):
                widget = create_ui_widget(root, "Fantasy HUD", "button", "primary action button", concept, "semi_realistic_ui", "codex_oauth", "/Game/UIM/UI")

            self.assertEqual(len([file for file in widget.files if file.role.startswith("ui_widget:button")]), 4)
            self.assertEqual(validate_manifest(widget), [])

    def test_seedance_walk_registers_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            anchor = root / "assets" / "hero" / "generated" / "anchor.png"
            _fake_image(anchor)
            captured: dict[str, str] = {}

            def fake_video(_provider, _anchor_path: Path, prompt: str, output_path: Path, *, seconds: int, **_kwargs) -> SeedanceResult:
                captured["prompt"] = prompt
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"video")
                return SeedanceResult(output_path=output_path, model="seedance-test", prompt=prompt, request_id="req", events=[f"{seconds}s"])

            with patch("uim_core.providers.seedance_provider.SeedanceProvider.generate_walk_video", fake_video):
                result = create_seedance_walk_video(root, "Hero", anchor, "south", "walk cycle", 5)
                second = create_seedance_walk_video(root, "Hero", anchor, "south", "walk cycle", 5)

            self.assertTrue((root / result["path"]).exists())
            self.assertTrue((root / second["path"]).exists())
            self.assertNotEqual(result["path"], second["path"])
            self.assertIn("#FF00FF", captured["prompt"])
            self.assertIn("must remain pure", captured["prompt"])
            index = load_asset_index(root, "hero")
            self.assertEqual(len([version for version in index.versions if version.role == "video:walk:south"]), 2)

    def test_seedance_action_video_uses_action_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            anchor = root / "assets" / "hero" / "generated" / "anchor.png"
            _fake_image(anchor)

            def fake_video(_provider, _anchor_path: Path, prompt: str, output_path: Path, *, seconds: int, **_kwargs) -> SeedanceResult:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"video")
                return SeedanceResult(output_path=output_path, model="seedance-test", prompt=prompt, request_id="req", events=[f"{seconds}s"])

            with patch("uim_core.providers.seedance_provider.SeedanceProvider.generate_walk_video", fake_video):
                result = create_seedance_walk_video(root, "Hero", anchor, "west", "attack slash", 5, action="attack")

            self.assertIn("attack_west", result["path"])
            index = load_asset_index(root, "hero")
            self.assertEqual(len([version for version in index.versions if version.role == "video:attack:west"]), 1)

    def test_seedance_action_video_uses_requested_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            anchor = root / "assets" / "hero" / "generated" / "anchor.png"
            _fake_image(anchor)
            captured: dict[str, str] = {}

            def fake_video(provider, _anchor_path: Path, prompt: str, output_path: Path, *, seconds: int, **_kwargs) -> SeedanceResult:
                captured["model"] = provider.model
                captured["resolution"] = provider.resolution
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"video")
                return SeedanceResult(output_path=output_path, model=provider.model, prompt=prompt, request_id="req", events=[f"{seconds}s"])

            with patch("uim_core.providers.seedance_provider.SeedanceProvider.generate_walk_video", fake_video):
                result = create_seedance_walk_video(root, "Hero", anchor, "west", "attack slash", 5, action="attack", model="seedance-2.0-fast", resolution="480p")

            self.assertEqual(captured["model"], "doubao-seedance-2-0-fast-260128")
            self.assertEqual(captured["resolution"], "480p")
            self.assertEqual(result["model"], "doubao-seedance-2-0-fast-260128")

    def test_create_spritesheet_from_video_registers_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                pattern = Path(command[-1])
                for index in range(12):
                    _fake_image(pattern.parent / f"frame_{index + 1:04d}.png", size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", fake_run):
                manifest = create_spritesheet_from_video(root, "Hero", video, "attack", "west", 5, 2, 64, "pixel_art", "/Game/UIM/Pixels")

            self.assertEqual(len(manifest.frames), 10)
            self.assertEqual(manifest.files[0].role, "sheet:attack:west")
            self.assertTrue((root / manifest.files[0].path).exists())
            self.assertEqual(validate_manifest(manifest), [])
            index = load_asset_index(root, "hero")
            self.assertEqual(len([version for version in index.versions if version.role == "sheet:attack:west"]), 1)

    def test_create_spritesheet_from_video_uses_bundled_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")
            bundled_ffmpeg = root / "tools" / "ffmpeg.exe"
            bundled_ffmpeg.parent.mkdir(parents=True, exist_ok=True)
            bundled_ffmpeg.write_bytes(b"ffmpeg")
            fake_module = types.SimpleNamespace(get_ffmpeg_exe=lambda: str(bundled_ffmpeg))
            captured_command: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                captured_command.extend(command)
                pattern = Path(command[-1])
                for index in range(4):
                    _fake_image(pattern.parent / f"frame_{index + 1:04d}.png", size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.dict(sys.modules, {"imageio_ffmpeg": fake_module}), patch("shutil.which", return_value=None), patch("subprocess.run", fake_run):
                manifest = create_spritesheet_from_video(root, "Hero", video, "attack", "west", 2, 2, 64, "pixel_art", "/Game/UIM/Pixels")

            self.assertEqual(captured_command[0], str(bundled_ffmpeg))
            self.assertEqual(manifest.processing["videoSpritesheet"]["extractor"], "imageio-ffmpeg")

    def test_create_spritesheet_from_video_uses_selected_times(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")
            captured_times: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                captured_times.append(command[command.index("-ss") + 1])
                _fake_image(Path(command[-1]), size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", fake_run):
                manifest = create_spritesheet_from_video(
                    root,
                    "Hero",
                    video,
                    "attack",
                    "west",
                    2,
                    2,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    frame_times=[0.1, 0.4, 0.8, 1.2],
                )

            self.assertEqual(captured_times, ["0.100", "0.400", "0.800", "1.200"])
            self.assertEqual(manifest.processing["videoSpritesheet"]["selectedFrameTimes"], [0.1, 0.4, 0.8, 1.2])
            self.assertEqual(manifest.processing["videoSpritesheet"]["frameOrderMode"], "user_queue")

    def test_create_spritesheet_from_video_allows_zero_second_selected_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")
            captured_times: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                captured_times.append(command[command.index("-ss") + 1])
                _fake_image(Path(command[-1]), size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", fake_run):
                manifest = create_spritesheet_from_video(
                    root,
                    "Hero",
                    video,
                    "attack",
                    "west",
                    2,
                    2,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    frame_times=[0.0, 0.4, 0.8, 1.2],
                )

            self.assertEqual(captured_times[0], "0.000")
            self.assertEqual(manifest.processing["videoSpritesheet"]["selectedFrameTimes"][0], 0.0)

    def test_create_spritesheet_from_video_uses_selected_frame_count_for_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                _fake_image(Path(command[-1]), size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", fake_run):
                manifest = create_spritesheet_from_video(
                    root,
                    "Hero",
                    video,
                    "attack",
                    "west",
                    2,
                    2,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    frame_times=[0.1, 0.2, 0.3, 0.4, 0.5],
                )

            from PIL import Image

            self.assertEqual(len(manifest.frames), 5)
            self.assertEqual(manifest.processing["videoSpritesheet"]["frameCount"], 5)
            self.assertEqual(manifest.processing["videoSpritesheet"]["rows"], 3)
            self.assertEqual(manifest.processing["videoSpritesheet"]["requestedRows"], 2)
            with Image.open(root / manifest.files[0].path) as sheet:
                self.assertEqual(sheet.size, (128, 192))

    def test_extract_video_frame_thumbnails_returns_data_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")
            captured_times: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                captured_times.append(command[command.index("-ss") + 1])
                _fake_image(Path(command[-1]), size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", fake_run):
                result = extract_video_frame_thumbnails(video, [0.0, 0.25, 0.5], thumbnail_size=96)

            self.assertEqual(captured_times, ["0.000", "0.250", "0.500"])
            self.assertIn(result["extractor"], {"ffmpeg", "imageio-ffmpeg"})
            self.assertEqual(len(result["frames"]), 3)
            self.assertTrue(result["frames"][0]["thumbnail"].startswith("data:image/png;base64,"))

    def test_extract_video_frame_thumbnails_retries_near_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")
            captured_times: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                timestamp = command[command.index("-ss") + 1]
                captured_times.append(timestamp)
                if float(timestamp) >= 5.0:
                    return subprocess.CompletedProcess(command, 1, "", "Output file is empty")
                _fake_image(Path(command[-1]), size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", fake_run):
                result = extract_video_frame_thumbnails(video, [5.077], thumbnail_size=96)

            self.assertIn("4.977", captured_times)
            self.assertEqual(len(result["frames"]), 1)
            self.assertTrue(result["frames"][0]["thumbnail"].startswith("data:image/png;base64,"))

    def test_video_debug_export_outputs_png_sequence_gif_and_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "assets" / "hero" / "generated" / "attack_west.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"video")
            captured_times: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                captured_times.append(command[command.index("-ss") + 1])
                _fake_image(Path(command[-1]), size=(32, 32))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", fake_run):
                png_manifest = create_video_debug_export(
                    root,
                    "Hero",
                    video,
                    "attack",
                    "west",
                    "png_sequence",
                    2,
                    2,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    [0.4, 0.1, 0.8],
                )
                gif_manifest = create_video_debug_export(
                    root,
                    "Hero",
                    video,
                    "attack",
                    "west",
                    "gif",
                    2,
                    2,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    [0.1, 0.2],
                )
                sheet_manifest = create_video_debug_export(
                    root,
                    "Hero",
                    video,
                    "attack",
                    "west",
                    "sheet",
                    2,
                    2,
                    64,
                    "pixel_art",
                    "/Game/UIM/Pixels",
                    [0.1, 0.2, 0.3],
                )

            self.assertEqual(png_manifest.processing["videoDebugExport"]["selectedFrameTimes"], [0.4, 0.1, 0.8])
            self.assertEqual(png_manifest.processing["videoDebugExport"]["frameOrderMode"], "user_queue")
            self.assertEqual(png_manifest.processing["videoDebugExport"]["exportType"], "png_sequence")
            self.assertTrue((root / png_manifest.files[0].path).exists())
            self.assertTrue((root / png_manifest.processing["videoDebugExport"]["outputDirectory"]).is_dir())
            self.assertEqual(gif_manifest.files[0].mime_type, "image/gif")
            self.assertTrue((root / gif_manifest.files[0].path).exists())
            self.assertEqual(sheet_manifest.files[0].role, "debug:video_sheet:attack:west")
            self.assertTrue((root / sheet_manifest.files[0].path).exists())
            self.assertEqual(captured_times[:3], ["0.400", "0.100", "0.800"])

    def test_seedance_walk_rejects_missing_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            with self.assertRaises(ValueError):
                create_seedance_walk_video(root, "Hero", root / "missing.png", "south", "walk cycle", 5)


if __name__ == "__main__":
    unittest.main()
