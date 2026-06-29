import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uim_core import mcp_pixel
from uim_core.asset_index import load_asset_index
from uim_core.project import create_project, load_project_workspace
from uim_core.providers.openai_image import ImageGenerationResult


def _fake_generate(_provider, prompt: str, output_path: Path, *, size: str = "1024x1024", reference_path: Path | None = None) -> ImageGenerationResult:
    from PIL import Image

    width, height = [int(part) for part in size.lower().split("x")]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (width, height), (255, 0, 255, 255)).save(output_path)
    return ImageGenerationResult(output_path=output_path, model="fake", prompt=prompt, size=size, quality="auto", base_url="fake", stream_events=["fake.event"])


def _fake_edit(_provider, prompt: str, image_path: Path, output_path: Path, *, size: str = "1024x1024") -> ImageGenerationResult:
    return _fake_generate(_provider, prompt, output_path, size=size, reference_path=image_path)


def _thumbnail(color: tuple[int, int, int]) -> str:
    from base64 import b64encode
    from io import BytesIO
    from PIL import Image

    image = Image.new("RGBA", (32, 32), (*color, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{b64encode(buffer.getvalue()).decode('ascii')}"


class McpPixelTests(unittest.TestCase):
    def test_set_context_writes_workspace_ui_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            result = mcp_pixel.pixel_set_context(str(root), "Hero", "character", "sheet", "walk", "west", "video")
            workspace = load_project_workspace(root)

            self.assertTrue(result["ok"])
            self.assertEqual(workspace["mcpUiState"]["assetName"], "Hero")
            self.assertEqual(workspace["mcpUiState"]["pixelStage"], "sheet")
            self.assertEqual(workspace["mcpUiState"]["pixelSheetMode"], "video")

    def test_generate_concept_uses_existing_pipeline_and_updates_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False), patch("uim_core.providers.openai_image.OpenAIImageProvider.generate", _fake_generate), patch(
                "uim_core.providers.openai_image.OpenAIImageProvider.edit", _fake_edit
            ):
                result = mcp_pixel.pixel_generate_concept(str(root), "Sword", "silver sword", "weapon")

            self.assertTrue(result["ok"])
            self.assertEqual(result["nextSuggestedStage"], "south_anchor")
            self.assertEqual(result["mcpUiState"]["pixelKind"], "weapon")
            self.assertEqual(result["mcpUiState"]["pixelStage"], "south_anchor")
            self.assertEqual(result["mcpUiState"]["pixelSheetMode"], "video")
            self.assertEqual(len(load_asset_index(root, "sword").versions), 1)

    def test_seedance_video_preserves_non_character_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            anchor = root / "assets" / "sword" / "generated" / "anchor.png"
            anchor.parent.mkdir(parents=True, exist_ok=True)
            anchor.write_bytes(b"png")
            fake_result = {"path": "assets/sword/generated/idle_single.mp4", "output_path": str(anchor.with_suffix(".mp4"))}

            with patch("uim_core.mcp_pixel.create_seedance_walk_video", return_value=fake_result):
                result = mcp_pixel.pixel_generate_seedance_video(str(root), "Sword", str(anchor), "idle", "single", "glint loop", asset_kind="weapon")

            self.assertTrue(result["ok"])
            self.assertEqual(result["mcpUiState"]["pixelKind"], "weapon")
            self.assertEqual(result["mcpUiState"]["pixelDirection"], "single")
            self.assertEqual(result["mcpUiState"]["pixelSheetMode"], "video")

    def test_tilemap_tool_uses_tilemap_manifest(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            tiles = root / "assets" / "grass" / "generated" / "tiles.png"
            tiles.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (256, 192), (0, 128, 0, 255)).save(tiles)

            result = mcp_pixel.pixel_tilemap_47(str(root), "Grass", str(tiles), 32)

            self.assertTrue(result["ok"])
            self.assertEqual(result["manifest"]["processing"]["tilemap"]["standard"], "47-tile")
            self.assertEqual(result["mcpUiState"]["pixelKind"], "tilemap")

    def test_dual_grid_tilemap_tool_uses_dual_grid_manifest(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            tiles = root / "assets" / "grass" / "generated" / "dual_grid.png"
            tiles.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (128, 128), (0, 128, 0, 255)).save(tiles)

            result = mcp_pixel.pixel_tilemap_dual_grid(str(root), "Grass", str(tiles), 32)

            self.assertTrue(result["ok"])
            self.assertEqual(result["manifest"]["processing"]["tilemap"]["standard"], "dual-grid-16")
            self.assertEqual(result["manifest"]["processing"]["tilemap"]["maskBits"], {"NW": 1, "NE": 2, "SW": 4, "SE": 8})
            self.assertEqual(result["manifest"]["files"][0]["role"], "tileset:dual-grid-16")
            self.assertEqual(result["mcpUiState"]["pixelKind"], "tilemap")

    def test_video_find_loop_returns_all_candidates_and_selects_highest(self) -> None:
        frames = {
            "extractor": "mock",
            "frames": [
                {"time": 0.0, "thumbnail": _thumbnail((255, 0, 255))},
                {"time": 0.1, "thumbnail": _thumbnail((0, 0, 255))},
                {"time": 0.2, "thumbnail": _thumbnail((255, 0, 255))},
                {"time": 0.3, "thumbnail": _thumbnail((254, 0, 255))},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "video.mp4"
            video.write_bytes(b"mock")
            with patch("uim_core.mcp_pixel.extract_video_frame_thumbnails", return_value=frames):
                result = mcp_pixel.pixel_video_find_loop(str(root), str(video), [0.0, 0.1, 0.2, 0.3], min_score=0.9)

            self.assertTrue(result["ok"])
            self.assertGreaterEqual(len(result["result"]["candidates"]), 2)
            self.assertEqual(result["result"]["selected"]["index"], 2)

    def test_video_select_frames_fps_preserves_time_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            video = root / "video.mp4"
            video.write_bytes(b"mock")

            def fake_thumbnails(_video_path: Path, frame_times: list[float], _thumbnail_size: int):
                return {"extractor": "mock", "frames": [{"time": time, "thumbnail": _thumbnail((255, 0, 255))} for time in frame_times]}

            with patch("uim_core.mcp_pixel.extract_video_frame_thumbnails", fake_thumbnails):
                result = mcp_pixel.pixel_video_select_frames(str(root), str(video), "fps", 0.0, 0.5, 4.0)

            times = result["result"]["frameTimes"]
            self.assertTrue(result["ok"])
            self.assertEqual(times, sorted(times))
            self.assertGreaterEqual(len(times), 1)


if __name__ == "__main__":
    unittest.main()
