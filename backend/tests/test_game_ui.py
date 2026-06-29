from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uim_core import mcp_game_ui
from uim_core.asset_index import load_asset_index
from uim_core.game_ui import (
    _bake_html_with_playwright,
    _layout_for_anchor_preset,
    _cleanup_ui_crop,
    _create_state_sheet_guide,
    _decontaminate_ui_chroma_spill,
    _fit_ui_texture_to_canvas,
    _normalize_chroma_key,
    _remove_ui_chroma_fringe,
    _state_slot_crop_rect,
    _state_sheet_prompt,
    _ui_chroma_cutout,
    _ui_texture_quality_report,
    bake_game_ui_html,
    clear_texture_kit,
    delete_game_ui_html,
    delete_game_ui_structure,
    default_texture_catalog,
    export_game_ui_umg,
    generate_texture_kit,
    game_ui_dsl_prompt,
    list_texture_kits,
    list_game_ui_html_prototypes,
    migrate_texture_kit_from_existing_outputs,
    read_game_ui_html,
    register_texture_kit,
    validate_html_source,
    validate_structure_with_kit,
    write_game_ui_html,
)
from uim_core.project import create_project, load_project_workspace, save_current_project_root


RESPONSIVE_SCREEN_HTML = (
    '<div data-u-type="screen" data-u-name="shopScreen" '
    'style="width:100vw;height:100vh;min-width:100vw;min-height:100vh;position:relative;overflow:hidden"></div>'
)


def _touch_texture(root: Path, rel_path: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")


def _write_png_texture(root: Path, rel_path: str, size: tuple[int, int] = (32, 32)) -> None:
    from PIL import Image

    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (64, 128, 220, 255)).save(path)


def _fake_bake(_html: str, width: int, height: int) -> dict:
    return {
        "width": width,
        "height": height,
        "root": {
            "name": "shopScreen",
            "type": "screen",
            "styleToken": "",
            "x": 0,
            "y": 0,
            "width": width,
            "height": height,
            "color": "#000000",
            "fontColor": "#ffffff",
            "fontSize": 16,
            "textAlign": "start",
            "text": "",
            "children": [
                {
                    "name": "confirmButton",
                    "type": "button",
                    "styleToken": "primaryButton",
                    "x": 100,
                    "y": 900,
                    "width": 240,
                    "height": 72,
                    "color": "#ffffff",
                    "fontColor": "#ffffff",
                    "fontSize": 18,
                    "textAlign": "center",
                    "text": "",
                    "children": [],
                }
            ],
        },
    }


def _fake_atlas_generate(_prompt: str, output_path: Path, _provider: str, *, size: str = "1536x1024", reference_path: Path | None = None, reference_paths: list[Path] | None = None):
    from PIL import Image, ImageDraw
    from uim_core.providers.openai_image import ImageGenerationResult

    width, height = (int(part) for part in size.split("x", 1))
    image = Image.new("RGBA", (width, height), (255, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    cell_width = width // 4
    cell_height = height // 4
    for row in range(4):
        for column in range(4):
            x0 = column * cell_width + 48
            y0 = row * cell_height + 48
            draw.rectangle((x0, y0, x0 + cell_width - 96, y0 + cell_height - 96), fill=(40 + column * 20, 120 + row * 20, 220, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return ImageGenerationResult(output_path=output_path, model="fake", prompt=_prompt, size=size, quality="auto")


def _fake_rembg(_self, input_path: Path, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(input_path.read_bytes())
    return None


class GameUiPipelineTests(unittest.TestCase):
    def test_dsl_prompt_contains_required_constraints(self) -> None:
        prompt = game_ui_dsl_prompt()
        self.assertIn('data-u-type="screen"', prompt)
        self.assertIn("width:100vw", prompt)
        self.assertIn("data-u-anchor", prompt)
        self.assertIn("data-u-pivot", prompt)
        self.assertIn("top-stretch", prompt)
        self.assertNotIn("width:1920px", prompt)
        self.assertNotIn("height:1080px", prompt)
        self.assertIn("button", prompt)
        self.assertIn("禁止外部图片", prompt)
        self.assertIn("一次性写入许可", prompt)
        self.assertIn("dsl_prompt_token", prompt)
        self.assertIn("不要用普通文件写入", prompt)
        self.assertIn("调用 game_ui_write_current_html", prompt)
        self.assertIn("不要创建、查找、打开、切换或确认工作区", prompt)
        self.assertIn("如果用户没有提供 HTML 原型名称", prompt)
        self.assertIn("先向用户询问", prompt)

    def test_mcp_dsl_prompt_returns_explicit_current_workspace_write_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            result = mcp_game_ui.game_ui_get_dsl_prompt(str(root))
            workflow = result["writeWorkflow"]

            self.assertTrue(result["ok"])
            self.assertEqual(workflow["projectRoot"], str(root.resolve()))
            self.assertEqual(workflow["htmlOnlyCurrentToolOrder"][0]["tool"], "game_ui_get_current_dsl_prompt")
            self.assertEqual(workflow["htmlOnlyCurrentToolOrder"][1]["tool"], "game_ui_write_current_html")
            self.assertNotIn("preferredCurrentWorkspaceToolOrder", workflow)
            self.assertTrue(any("Do not write the HTML with shell commands" in item for item in workflow["mustNot"]))
            self.assertTrue(any("Do not create, search for, or switch workspaces" in item for item in workflow["mustNot"]))

    def test_slider_thumb_prompt_requires_knob_only_and_concept_reference(self) -> None:
        guide = {
            "slots": [
                {"state": "normal", "targetSize": {"width": 160, "height": 160}},
                {"state": "hover", "targetSize": {"width": 160, "height": 160}},
                {"state": "disabled", "targetSize": {"width": 160, "height": 160}},
            ]
        }
        prompt = _state_sheet_prompt(
            "defaultUiKit",
            {
                "token": "sliderThumb",
                "type": "slider",
                "description": "slider draggable knob",
                "states": ["normal", "hover", "disabled"],
            },
            guide,
        )

        lowered = prompt.lower()
        self.assertIn("video game ui / hud skin texture", lowered)
        self.assertIn("unreal engine umg", lowered)
        self.assertIn("not a physical object", lowered)
        self.assertIn("scene prop", lowered)
        self.assertIn("draw only the draggable thumb/knob handle", lowered)
        self.assertIn("do not draw a slider track", lowered)
        self.assertIn("progress fill", lowered)
        self.assertIn("complete slider bar", lowered)
        self.assertIn("first reference image", lowered)
        self.assertIn("primary visual target", lowered)

    def test_default_ui_chroma_key_is_magenta(self) -> None:
        self.assertEqual(_normalize_chroma_key(None), (255, 0, 255))

    def test_state_sheet_guide_uses_custom_chroma_key(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            item = {
                "token": "buttonDefault",
                "type": "button",
                "states": ["normal"],
                "description": "button",
            }

            guide = _create_state_sheet_guide(root, "defaultUiKit", item, chroma_key=(0, 255, 0))

            self.assertEqual(guide["chromaKey"], [0, 255, 0])
            self.assertEqual(guide["chromaKeyHex"], "#00FF00")
            with Image.open(root / guide["guidePath"]) as image:
                self.assertEqual(image.convert("RGBA").getpixel((0, 0)), (0, 255, 0, 255))

    def test_state_sheet_prompt_uses_custom_key_and_token_contract(self) -> None:
        guide = {
            "chromaKey": [0, 255, 0],
            "slots": [
                {"state": "normal", "targetSize": {"width": 256, "height": 256}},
            ],
        }

        image_frame_prompt = _state_sheet_prompt(
            "defaultUiKit",
            {
                "token": "imageFrame",
                "type": "image",
                "description": "image frame",
                "states": ["normal"],
            },
            guide,
            chroma_key=(0, 255, 0),
        )
        slider_prompt = _state_sheet_prompt(
            "defaultUiKit",
            {
                "token": "sliderThumb",
                "type": "slider",
                "description": "slider thumb",
                "states": ["normal"],
            },
            guide,
            chroma_key=(0, 255, 0),
        )

        self.assertIn("#00FF00", image_frame_prompt)
        self.assertIn("The key color #00FF00 is background only", image_frame_prompt)
        self.assertIn("transparent center", image_frame_prompt.lower())
        self.assertIn("solid panels", image_frame_prompt.lower())
        self.assertIn("Unreal Engine UMG", image_frame_prompt)
        self.assertIn("slider track", slider_prompt.lower())
        self.assertIn("progress fill", slider_prompt.lower())
        self.assertIn("complete slider bar", slider_prompt.lower())

    def test_ui_chroma_cutout_uses_custom_green_key(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (0, 255, 0, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 47, 47), fill=(255, 0, 255, 255))

        cleaned, report = _ui_chroma_cutout(image, (0, 255, 0))

        self.assertEqual(report["chromaKey"], [0, 255, 0])
        self.assertEqual(cleaned.getpixel((0, 0))[3], 0)
        self.assertEqual(cleaned.getpixel((24, 24)), (255, 0, 255, 255))

    def test_image_frame_chroma_cutout_preserves_transparent_center(self) -> None:
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            crop = Image.new("RGBA", (256, 256), (0, 255, 0, 255))
            draw = ImageDraw.Draw(crop)
            draw.rectangle((24, 24, 231, 231), outline=(40, 40, 48, 255), width=24)
            output = temp_root / "imageframe.png"

            report = _cleanup_ui_crop(
                crop,
                output,
                temp_root,
                mask_mode="hybrid",
                decontaminate_edges=True,
                debug_artifacts=False,
                target_size=(256, 256),
                chroma_key=(0, 255, 0),
                prefer_chroma_cutout=True,
            )

            self.assertEqual(report["mode"], "ui_chroma_preferred")
            with Image.open(output) as image:
                rgba = image.convert("RGBA")
                self.assertEqual(rgba.getpixel((128, 128))[3], 0)
                self.assertGreater(rgba.getpixel((24, 128))[3], 180)

    def test_ui_texture_quality_report_flags_visible_key_color(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 55, 55), fill=(40, 40, 48, 255))
        draw.rectangle((12, 12, 24, 24), fill=(0, 255, 0, 255))

        report = _ui_texture_quality_report(image, "buttonDefault", (64, 64), (0, 255, 0))

        self.assertFalse(report["ok"])
        self.assertGreater(report["residualKeyPixels"], 0)
        self.assertTrue(any("key color contamination" in issue for issue in report["issues"]))

    def test_ui_texture_hybrid_mask_preserves_dark_button_center_on_chroma_background(self) -> None:
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            crop = Image.new("RGBA", (360, 160), (255, 0, 255, 255))
            draw = ImageDraw.Draw(crop)
            draw.rounded_rectangle((20, 28, 340, 132), radius=18, fill=(18, 20, 18, 255), outline=(220, 176, 70, 255), width=6)

            def fake_rembg(image, _temp_dir, _stem, model_name="isnet-general-use"):
                output = Image.new("RGBA", image.size, (0, 0, 0, 0))
                bottom_strip = image.crop((20, 112, 340, 132))
                output.alpha_composite(bottom_strip, (20, 112))
                return output

            output = temp_root / "button.png"
            with patch("uim_core.game_ui._rembg_rgba", fake_rembg):
                report = _cleanup_ui_crop(
                    crop,
                    output,
                    temp_root,
                    mask_mode="hybrid",
                    decontaminate_edges=True,
                    debug_artifacts=True,
                    target_size=(320, 128),
                )

            self.assertEqual(report["mode"], "hybrid")
            with Image.open(output) as image:
                rgba = image.convert("RGBA")
                center_alpha = rgba.getpixel((rgba.width // 2, rgba.height // 2))[3]
                pixels = getattr(rgba, "get_flattened_data", rgba.getdata)()
                purple_pixels = sum(
                    1
                    for r, g, b, a in pixels
                    if a > 0 and r > 100 and b > 100 and g < 80 and abs(r - b) < 140
                )
            self.assertGreater(center_alpha, 200)
            self.assertEqual(purple_pixels, 0)

    def test_ui_texture_fit_does_not_bleed_chroma_rgb_from_transparent_padding(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (360, 180), (255, 0, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((20, 36, 340, 132), radius=18, fill=(18, 20, 18, 255), outline=(220, 176, 70, 255), width=6)

        fitted = _fit_ui_texture_to_canvas(image, (320, 128))
        fitted_pixels = getattr(fitted, "get_flattened_data", fitted.getdata)()

        purple_pixels = sum(
            1
            for r, g, b, a in fitted_pixels
            if a > 0 and r > 100 and b > 100 and g < 80 and abs(r - b) < 140
        )
        self.assertEqual(purple_pixels, 0)

    def test_ui_chroma_fringe_removes_dark_purple_edge_residue(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (48, 24), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 6, 39, 16), fill=(28, 28, 28, 255))
        draw.line((10, 17, 37, 17), fill=(53, 2, 53, 186))

        cleaned, report = _remove_ui_chroma_fringe(image, [247, 4, 248])

        self.assertGreater(report["removedUiChromaFringePixels"], 0)
        self.assertEqual(cleaned.getpixel((20, 17))[3], 0)
        self.assertEqual(cleaned.getpixel((20, 12))[3], 255)

    def test_ui_chroma_fringe_preserves_opaque_dark_purple_frame(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 55, 55), radius=8, outline=(58, 8, 64, 255), width=6)

        cleaned, report = _remove_ui_chroma_fringe(image, [247, 4, 248])

        self.assertEqual(report["removedUiChromaFringePixels"], 0)
        self.assertEqual(cleaned.getpixel((10, 32)), (58, 8, 64, 255))

    def test_ui_chroma_spill_decontaminates_visible_magenta_edge_rgb(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 8, 51, 23), fill=(40, 42, 48, 255))
        draw.line((12, 8, 51, 8), fill=(246, 4, 248, 255))

        cleaned, report = _decontaminate_ui_chroma_spill(image, (255, 0, 255), edge_pixels=4)

        self.assertGreater(report["decontaminatedUiChromaSpillPixels"], 0)
        self.assertEqual(cleaned.getpixel((20, 8))[3], 255)
        r, g, b, _a = cleaned.getpixel((20, 8))
        self.assertLess(r, 100)
        self.assertLess(b, 120)
        self.assertGreater(g, 20)

    def test_ui_chroma_spill_decontaminates_visible_interior_key_tint(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (96, 48), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 87, 39), fill=(38, 42, 48, 255))
        draw.rectangle((36, 18, 60, 30), fill=(244, 8, 247, 255))

        cleaned, report = _decontaminate_ui_chroma_spill(image, (255, 0, 255), edge_pixels=4)

        self.assertGreater(report["decontaminatedUiChromaSpillPixels"], 0)
        r, g, b, a = cleaned.getpixel((48, 24))
        self.assertEqual(a, 255)
        self.assertLess(r, 100)
        self.assertLess(b, 120)
        self.assertGreater(g, 20)

    def test_state_sheet_prompt_forbids_key_colored_reflections(self) -> None:
        guide = {
            "chromaKey": [255, 0, 255],
            "slots": [
                {"state": "normal", "targetSize": {"width": 320, "height": 128}},
            ],
        }

        prompt = _state_sheet_prompt(
            "defaultUiKit",
            {
                "token": "buttonDefault",
                "type": "button",
                "description": "button",
                "states": ["normal"],
            },
            guide,
        ).lower()

        self.assertIn("forbidden pigment", prompt)
        self.assertIn("key-colored rim light", prompt)
        self.assertIn("key-colored ambient reflection", prompt)
        self.assertIn("color bleeding", prompt)

    def test_state_slot_crop_rect_prefers_detected_region(self) -> None:
        slot = {"rect": {"x": 64, "y": 112, "width": 896, "height": 176}}
        detected = {"x": 82, "y": 35, "width": 859, "height": 233}

        rect, mode = _state_slot_crop_rect(slot, detected)

        self.assertEqual(rect, detected)
        self.assertEqual(mode, "detected_rect")

    def test_state_slot_crop_rect_falls_back_to_guide_rect(self) -> None:
        slot = {"rect": {"x": 64, "y": 112, "width": 896, "height": 176}}

        rect, mode = _state_slot_crop_rect(slot, None)

        self.assertEqual(rect, slot["rect"])
        self.assertEqual(mode, "guide_rect")

    def test_validate_html_rejects_external_urls(self) -> None:
        with self.assertRaises(ValueError):
            validate_html_source('<div data-u-type="screen" data-u-name="root"><img src="https://example.com/a.png"></div>')

    def test_validate_html_accepts_spaced_single_quoted_screen_attribute(self) -> None:
        validate_html_source("<div data-u-type = 'screen' data-u-name='root' style='width:100vw;height:100vh;position:relative'></div>")

    def test_validate_html_rejects_fixed_screen_resolution(self) -> None:
        with self.assertRaises(ValueError):
            validate_html_source('<div data-u-type="screen" data-u-name="root" style="width:1920px;height:1080px;position:relative"></div>')

    def test_validate_html_requires_explicit_anchor_on_children(self) -> None:
        html = (
            '<div data-u-type="screen" data-u-name="root" style="width:100vw;height:100vh;position:relative">'
            '<div data-u-type="panel" data-u-name="topHud" style="position:absolute;left:0;top:0;width:400px;height:80px"></div>'
            "</div>"
        )
        with self.assertRaises(ValueError):
            validate_html_source(html)

    def test_validate_html_accepts_explicit_anchor_on_children(self) -> None:
        html = (
            '<div data-u-type="screen" data-u-name="root" style="width:100vw;height:100vh;position:relative">'
            '<div data-u-type="panel" data-u-name="topHud" data-u-anchor="top-stretch" data-u-pivot="0,0" style="position:absolute;left:0;right:0;top:0;height:80px"></div>'
            "</div>"
        )
        validate_html_source(html)

    def test_validate_html_requires_explicit_pivot_on_children(self) -> None:
        html = (
            '<div data-u-type="screen" data-u-name="root" style="width:100vw;height:100vh;position:relative">'
            '<div data-u-type="panel" data-u-name="modal" data-u-anchor="center" style="position:absolute;left:760px;top:390px;width:400px;height:300px"></div>'
            "</div>"
        )
        with self.assertRaises(ValueError):
            validate_html_source(html)

    def test_validate_html_rejects_invalid_pivot(self) -> None:
        html = (
            '<div data-u-type="screen" data-u-name="root" style="width:100vw;height:100vh;position:relative">'
            '<div data-u-type="panel" data-u-name="modal" data-u-anchor="center" data-u-pivot="2,0.5" style="position:absolute;left:760px;top:390px;width:400px;height:300px"></div>'
            "</div>"
        )
        with self.assertRaises(ValueError):
            validate_html_source(html)

    def test_bake_html_writes_structure_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            html = root / "ui" / "html" / "shop_screen.html"
            html.parent.mkdir(parents=True)
            html.write_text(RESPONSIVE_SCREEN_HTML, encoding="utf-8")

            with patch("uim_core.game_ui._bake_html_with_playwright", _fake_bake):
                result = bake_game_ui_html(root, "shopScreen", "ui/html/shop_screen.html")

            structure_path = root / result["path"]
            self.assertTrue(structure_path.exists())
            self.assertEqual(result["structure"]["schema"], "uim.game_ui.structure.v1")
            self.assertEqual(result["structure"]["root"]["children"][0]["styleToken"], "primaryButton")
            child = result["structure"]["root"]["children"][0]
            self.assertEqual(child["anchorPreset"], "top-left")
            self.assertEqual(child["anchors"]["minimum"], {"x": 0.0, "y": 0.0})
            self.assertEqual(child["offsets"], {"left": 100, "top": 900, "right": 240, "bottom": 72})

    def test_html_prototype_list_read_delete_updates_asset_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            written = write_game_ui_html(root, "shopScreen", RESPONSIVE_SCREEN_HTML)
            prototypes = list_game_ui_html_prototypes(root)["htmlPrototypes"]
            self.assertEqual([item["path"] for item in prototypes], [written["path"]])

            loaded = read_game_ui_html(root, written["path"])
            self.assertEqual(loaded["html"], RESPONSIVE_SCREEN_HTML)

            deleted = delete_game_ui_html(root, written["path"])
            self.assertEqual(deleted["deleted"], written["path"])
            self.assertEqual(deleted["removedVersions"], 1)
            self.assertFalse((root / written["path"]).exists())

            index = load_asset_index(root, "shopscreen")
            self.assertFalse(any(version.path == written["path"] and version.role == "ui_html:prototype" for version in index.versions))

    def test_delete_structure_removes_file_and_asset_index_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            written = write_game_ui_html(root, "shopScreen", RESPONSIVE_SCREEN_HTML)
            with patch("uim_core.game_ui._bake_html_with_playwright", _fake_bake):
                baked = bake_game_ui_html(root, "shopScreen", written["path"])

            deleted = delete_game_ui_structure(root, baked["path"])
            self.assertEqual(deleted["deleted"], baked["path"])
            self.assertEqual(deleted["removedVersions"], 1)
            self.assertFalse((root / baked["path"]).exists())

            index = load_asset_index(root, "shopscreen")
            self.assertFalse(any(version.path == baked["path"] and version.role == "ui_structure:json" for version in index.versions))

    def test_delete_game_ui_files_reject_project_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            outside_html = Path(tmp) / "outside.html"
            outside_html.write_text(RESPONSIVE_SCREEN_HTML, encoding="utf-8")
            outside_structure = Path(tmp) / "outside.uim-ui.json"
            outside_structure.write_text("{}", encoding="utf-8")

            with self.assertRaises(ValueError):
                delete_game_ui_html(root, str(outside_html))
            with self.assertRaises(ValueError):
                delete_game_ui_structure(root, str(outside_structure))

    def test_anchor_layout_offsets_match_umg_canvas_semantics(self) -> None:
        bottom_right = _layout_for_anchor_preset("bottom-right", 1600, 900, 240, 72, 1920, 1080)
        self.assertEqual(bottom_right["anchors"], {"minimum": {"x": 1.0, "y": 1.0}, "maximum": {"x": 1.0, "y": 1.0}})
        self.assertEqual(bottom_right["offsets"], {"left": -320, "top": -180, "right": 240, "bottom": 72})

        top_stretch = _layout_for_anchor_preset("top-stretch", 100, 24, 1720, 80, 1920, 1080)
        self.assertEqual(top_stretch["anchors"], {"minimum": {"x": 0.0, "y": 0.0}, "maximum": {"x": 1.0, "y": 0.0}})
        self.assertEqual(top_stretch["offsets"], {"left": 100, "top": 24, "right": 100, "bottom": 80})

        pivoted_bottom_right = _layout_for_anchor_preset("bottom-right", 1600, 900, 240, 72, 1920, 1080, (1.0, 1.0))
        self.assertEqual(pivoted_bottom_right["alignment"], {"x": 1.0, "y": 1.0})
        self.assertEqual(pivoted_bottom_right["offsets"], {"left": -80, "top": -108, "right": 240, "bottom": 72})

    def test_bake_html_nested_layout_offsets_are_relative_to_parent_canvas(self) -> None:
        html = (
            '<div data-u-type="screen" data-u-name="Root" style="width:100vw;height:100vh;position:relative">'
            '<div data-u-type="panel" data-u-name="Parent" data-u-anchor="top-left" data-u-pivot="0,0" '
            'style="position:absolute;left:100px;top:50px;width:200px;height:100px">'
            '<div data-u-type="text" data-u-name="Child" data-u-anchor="center" data-u-pivot="0.5,0.5" '
            'style="position:absolute;left:60px;top:40px;width:80px;height:20px">OK</div>'
            "</div></div>"
        )

        baked = _bake_html_with_playwright(html, 1920, 1080)
        parent = baked["root"]["children"][0]
        child = parent["children"][0]

        self.assertEqual(parent["offsets"], {"left": 100, "top": 50, "right": 200, "bottom": 100})
        self.assertEqual(child["x"], 160)
        self.assertEqual(child["y"], 90)
        self.assertEqual(child["offsets"], {"left": 0, "top": 0, "right": 80, "bottom": 20})

    def test_export_umg_requires_complete_button_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            html = root / "ui" / "html" / "shop_screen.html"
            html.parent.mkdir(parents=True)
            html.write_text(RESPONSIVE_SCREEN_HTML, encoding="utf-8")
            with patch("uim_core.game_ui._bake_html_with_playwright", _fake_bake):
                structure = bake_game_ui_html(root, "shopScreen", "ui/html/shop_screen.html")

            _touch_texture(root, "ui/textures/button_normal.png")
            kit = register_texture_kit(root, "Default", [{"token": "primaryButton", "state": "normal", "path": "ui/textures/button_normal.png"}])

            with self.assertRaises(ValueError):
                export_game_ui_umg(root, "shopScreen", structure["path"], kit["path"])

    def test_export_umg_script_uses_absolute_texture_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            html = root / "ui" / "html" / "shop_screen.html"
            html.parent.mkdir(parents=True)
            html.write_text(RESPONSIVE_SCREEN_HTML, encoding="utf-8")
            with patch("uim_core.game_ui._bake_html_with_playwright", _fake_bake):
                structure = bake_game_ui_html(root, "shopScreen", "ui/html/shop_screen.html")
            files = [{"token": "primaryButton", "state": state, "path": f"ui/textures/button_{state}.png"} for state in ("normal", "hover", "pressed", "disabled")]
            for file in files:
                _touch_texture(root, str(file["path"]))
            kit = register_texture_kit(root, "Default", files)

            result = export_game_ui_umg(root, "shopScreen", structure["path"], kit["path"])
            script = Path(result["script"]).read_text(encoding="utf-8")

            self.assertIn("WidgetBlueprintFactory", script)
            self.assertIn(str((root / "ui/textures/button_normal.png").resolve()).replace("\\", "\\\\"), script)
            self.assertIn("/Game/UIM/UI/WBP_shopscreen", script)
            self.assertIn("ButtonStyle", script)
            self.assertIn("set_editor_property(\"widget_style\"", script)
            self.assertIn("SlateBrushDrawType.BOX", script)
            self.assertIn("set_editor_property(\"margin\"", script)
            self.assertIn("factory.set_editor_property(\"parent_class\", unreal.UserWidget)", script)
            self.assertIn("def _widget_tree(widget_blueprint):", script)
            self.assertIn('node_type in ("screen", "scroll")', script)
            self.assertIn("slot.set_anchors", script)
            self.assertIn("slot.set_offsets", script)
            self.assertIn("unreal.Margin", script)

    def test_texture_kit_rejects_missing_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            with self.assertRaises(ValueError):
                register_texture_kit(root, "Broken", [{"token": "primaryButton", "state": "normal", "path": "ui/textures/missing.png"}])

    def test_texture_kit_accepts_existing_unreal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            files = [
                {"token": "primaryButton", "state": state, "unrealPath": f"/Game/UIM/UI/T_primary_{state}"}
                for state in ("normal", "hover", "pressed", "disabled")
            ]
            kit = register_texture_kit(root, "Existing", files)

            self.assertTrue(kit["validation"]["ok"])
            self.assertEqual(kit["kit"]["textures"]["primaryButton"]["states"]["normal"]["path"], "")
            self.assertEqual(kit["kit"]["textures"]["primaryButton"]["states"]["normal"]["unrealPath"], "/Game/UIM/UI/T_primary_normal")

    def test_clear_texture_kit_deletes_config_and_generated_ui_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            _touch_texture(root, "ui/textures/default/button_normal.png")
            _touch_texture(root, "ui/textures/default/button_hover.png")
            _touch_texture(root, "assets/keep/keep.png")
            work_file = root / "ui" / "kits" / "default" / "state_sheets" / "button_states.png"
            work_file.parent.mkdir(parents=True, exist_ok=True)
            work_file.write_bytes(b"sheet")
            files = [
                {"token": "buttonDefault", "state": "normal", "path": "ui/textures/default/button_normal.png"},
                {"token": "buttonDefault", "state": "hover", "path": "ui/textures/default/button_hover.png"},
                {"token": "buttonDefault", "state": "pressed", "path": "assets/keep/keep.png"},
            ]
            kit = register_texture_kit(root, "Default", files)
            kit_path = root / kit["path"]
            data = kit_path.read_text(encoding="utf-8")
            data = data.replace('"generation": {}', '"generation": {"stateSheets": [{"sheetPath": "ui/kits/default/state_sheets/button_states.png"}]}')
            kit_path.write_text(data, encoding="utf-8")

            result = clear_texture_kit(root, kit["path"])

            self.assertEqual(result["deleted"], "ui/kits/default.uim-uikit.json")
            self.assertFalse(kit_path.exists())
            self.assertFalse((root / "ui/textures/default/button_normal.png").exists())
            self.assertFalse((root / "ui/textures/default/button_hover.png").exists())
            self.assertFalse((root / "ui/kits/default").exists())
            self.assertTrue((root / "assets/keep/keep.png").exists())

    def test_texture_kit_mapping_string_game_paths_are_unreal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            kit = register_texture_kit(
                root,
                "Mapped",
                {
                    "primaryButton": {
                        "states": {
                            "normal": "/Game/UIM/UI/T_primary_normal",
                            "hover": "/Game/UIM/UI/T_primary_hover",
                        }
                    }
                },
            )

            self.assertEqual(kit["kit"]["textures"]["primaryButton"]["states"]["normal"]["unrealPath"], "/Game/UIM/UI/T_primary_normal")

    def test_default_texture_catalog_covers_all_supported_controls(self) -> None:
        catalog = default_texture_catalog()
        by_token = {item["token"]: item for item in catalog}

        self.assertEqual({item["type"] for item in catalog}, {"panel", "image", "text", "button", "input", "scroll", "checkbox", "slider", "dropdown"})
        self.assertEqual(by_token["buttonDefault"]["states"], ["normal", "hover", "pressed", "disabled"])
        self.assertEqual(by_token["inputDefault"]["states"], ["normal", "focused", "disabled", "error"])
        self.assertEqual(by_token["checkboxBox"]["states"], ["unchecked", "uncheckedHover", "checked", "checkedHover", "disabled"])
        self.assertEqual(by_token["dropdownOption"]["states"], ["normal", "hover", "selected"])

    def test_generate_texture_kit_atlas_splits_default_full_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            progress_events: list[str] = []
            with patch("uim_core.game_ui._generate_image", _fake_atlas_generate), patch("uim_core.game_ui.RembgAdapter.remove_background", _fake_rembg):
                kit = generate_texture_kit(root, "Default", None, [], provider="openai_api", debug_artifacts=True, progress=progress_events.append)

            kit_file = root / kit["path"]
            self.assertTrue(kit_file.exists())
            self.assertTrue(kit["validation"]["ok"])
            textures = kit["kit"]["textures"]
            self.assertIn("panelDefault", textures)
            self.assertIn("dropdownOption", textures)
            self.assertIn("selected", textures["dropdownOption"]["states"])
            self.assertEqual(kit["kit"]["generation"]["mode"], "per_token")
            self.assertEqual(kit["kit"]["generation"]["coverage"], "default_full")
            self.assertEqual(kit["kit"]["generation"]["slotCatalogVersion"], "ui-texture-atlas-v3")
            self.assertEqual(kit["kit"]["generation"]["sourceGenerationSize"], "1024x1024")
            self.assertEqual(len(kit["kit"]["generation"]["stateSheets"]), 14)
            self.assertIn("sheetPath", kit["kit"]["generation"]["stateSheets"][0])
            self.assertEqual(kit["kit"]["generation"]["maxConcurrency"], 4)
            self.assertTrue(any("准备生成 14 个控件组" in event for event in progress_events))
            self.assertTrue(any("完成全部控件组" in event for event in progress_events))
            self.assertEqual(len(kit["kit"]["generation"]["atlasPages"]), 3)
            for entry in textures.values():
                for state in entry["states"].values():
                    self.assertTrue((root / state["path"]).exists())
            from PIL import Image

            with Image.open(root / textures["buttonDefault"]["states"]["normal"]["path"]) as button:
                self.assertEqual(button.size, (320, 128))
            with Image.open(root / textures["checkboxBox"]["states"]["checked"]["path"]) as checkbox:
                self.assertEqual(checkbox.size, (160, 160))
            self.assertEqual(kit["kit"]["generation"]["atlasPages"][0]["generationMode"], "per_token")
            self.assertIn("targetSize", kit["kit"]["generation"]["atlasPages"][0]["slots"][0])

    def test_generate_texture_kit_skips_tokens_with_complete_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            for state in ("normal", "hover", "pressed", "disabled"):
                _write_png_texture(root, f"ui/textures/default/buttondefault_{state}.png", size=(320, 128))
            progress_events: list[str] = []

            with patch("uim_core.game_ui._generate_image", side_effect=AssertionError("complete token should be skipped")):
                kit = generate_texture_kit(
                    root,
                    "Default",
                    None,
                    [{"token": "buttonDefault", "type": "button", "states": ["normal", "hover", "pressed", "disabled"]}],
                    coverage="custom",
                    progress=progress_events.append,
                )

            self.assertTrue(kit["validation"]["ok"])
            self.assertEqual(kit["kit"]["generation"]["stateSheets"][0]["resumeMode"], "existing_outputs")
            self.assertTrue(any("跳过" in event and "buttonDefault" in event for event in progress_events))

    def test_list_texture_kits_discovers_in_progress_generated_outputs_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            _write_png_texture(root, "ui/textures/defaultuikit/buttondefault_normal.png", size=(320, 128))
            state_sheet = root / "ui" / "kits" / "defaultuikit" / "state_sheets" / "buttondefault_states.png"
            _fake_atlas_generate("existing", state_sheet, "openai_api", size="1024x1024")

            result = list_texture_kits(root)

            self.assertEqual(len(result["kits"]), 1)
            kit = result["kits"][0]
            self.assertEqual(kit["kitName"], "defaultuikit")
            self.assertEqual(kit["path"], "")
            self.assertTrue(kit["inProgress"])
            self.assertEqual(kit["generatedStateCount"], 1)
            self.assertEqual(kit["stateSheetCount"], 1)
            self.assertIn("buttonDefault", kit["tokens"])

    def test_clear_texture_kit_deletes_in_progress_directories_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            _write_png_texture(root, "ui/textures/defaultuikit/buttondefault_normal.png", size=(320, 128))
            state_sheet = root / "ui" / "kits" / "defaultuikit" / "state_sheets" / "buttondefault_states.png"
            _fake_atlas_generate("existing", state_sheet, "openai_api", size="1024x1024")

            result = clear_texture_kit(root, "", "defaultuikit")

            self.assertEqual(result["kitName"], "defaultuikit")
            self.assertEqual(result["deleted"], "")
            self.assertFalse((root / "ui/textures/defaultuikit").exists())
            self.assertFalse((root / "ui/kits/defaultuikit").exists())
            self.assertIn("ui/textures/defaultuikit", result["deletedDirs"])
            self.assertIn("ui/kits/defaultuikit", result["deletedDirs"])

    def test_generate_texture_kit_rebuilds_bad_magenta_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from PIL import Image, ImageDraw

            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            bad_output = root / "ui" / "textures" / "default" / "paneldefault_normal.png"
            bad_output.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (384, 256), (255, 0, 255, 255))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 120, 120), fill=(28, 34, 48, 255))
            image.save(bad_output)
            progress_events: list[str] = []

            with patch("uim_core.game_ui._generate_image", _fake_atlas_generate), patch("uim_core.game_ui.RembgAdapter.remove_background", _fake_rembg):
                kit = generate_texture_kit(
                    root,
                    "Default",
                    None,
                    [{"token": "panelDefault", "type": "panel", "states": ["normal"]}],
                    coverage="custom",
                    progress=progress_events.append,
                )

            self.assertEqual(kit["kit"]["generation"]["stateSheets"][0]["resumeMode"], "generated")
            self.assertTrue(any("重新生成" in event and "panelDefault" in event for event in progress_events))

    def test_generate_texture_kit_reuses_existing_state_sheet_when_outputs_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            source = root / "ui" / "kits" / "default" / "state_sheets" / "buttondefault_states.png"
            _fake_atlas_generate("existing", source, "openai_api", size="1024x1024")
            progress_events: list[str] = []

            with patch("uim_core.game_ui._generate_image", side_effect=AssertionError("existing state sheet should be reused")), patch("uim_core.game_ui.RembgAdapter.remove_background", _fake_rembg):
                kit = generate_texture_kit(
                    root,
                    "Default",
                    None,
                    [{"token": "buttonDefault", "type": "button", "states": ["normal", "hover", "pressed", "disabled"]}],
                    coverage="custom",
                    progress=progress_events.append,
                )

            self.assertTrue(kit["validation"]["ok"])
            self.assertEqual(kit["kit"]["generation"]["stateSheets"][0]["resumeMode"], "existing_state_sheet")
            self.assertTrue(any("复用 buttonDefault 已有状态图" in event for event in progress_events))
            self.assertTrue((root / "ui/textures/default/buttondefault_normal.png").exists())

    def test_generate_texture_kit_crops_from_detected_region_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from PIL import Image, ImageDraw

            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            source = root / "ui" / "kits" / "default" / "state_sheets" / "paneldefault_states.png"
            source.parent.mkdir(parents=True, exist_ok=True)
            sheet = Image.new("RGBA", (1024, 1024), (255, 0, 255, 255))
            draw = ImageDraw.Draw(sheet)
            draw.rectangle((64, 360, 960, 664), fill=(20, 40, 80, 255))
            sheet.save(source)
            detected_rect = {"x": 40, "y": 336, "width": 944, "height": 352}

            with (
                patch("uim_core.game_ui._generate_image", side_effect=AssertionError("existing state sheet should be reused")),
                patch("uim_core.game_ui.RembgAdapter.remove_background", _fake_rembg),
                patch("uim_core.game_ui._rembg_component_regions", return_value={"normal": detected_rect}),
            ):
                kit = generate_texture_kit(
                    root,
                    "Default",
                    None,
                    [{"token": "panelDefault", "type": "panel", "states": ["normal"]}],
                    coverage="custom",
                )

            output_path = root / kit["kit"]["textures"]["panelDefault"]["states"]["normal"]["path"]
            with Image.open(output_path) as output:
                alpha = output.convert("RGBA").getchannel("A")
                alpha_data = getattr(alpha, "get_flattened_data", alpha.getdata)()
                visible = sum(1 for value in alpha_data if value > 0)
            self.assertGreater(visible, 384 * 256 * 0.35)
            atlas_slot = kit["kit"]["generation"]["atlasPages"][0]["slots"][0]
            self.assertEqual(atlas_slot["cropMode"], "detected_rect")
            self.assertEqual(atlas_slot["cropRect"], detected_rect)

    def test_migrate_texture_kit_from_existing_outputs_registers_completed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            for state in ("normal", "hover", "pressed", "disabled"):
                _write_png_texture(root, f"ui/textures/default/buttondefault_{state}.png", size=(320, 128))

            kit = migrate_texture_kit_from_existing_outputs(
                root,
                "Default",
                [{"token": "buttonDefault", "type": "button", "states": ["normal", "hover", "pressed", "disabled"]}],
                coverage="custom",
            )

            self.assertTrue((root / kit["path"]).exists())
            self.assertEqual(kit["kit"]["generation"]["mode"], "migrated_existing_outputs")
            self.assertIn("pressed", kit["kit"]["textures"]["buttonDefault"]["states"])

    def test_validate_structure_with_default_kit_requires_control_skin_tokens(self) -> None:
        structure = {
            "root": {
                "type": "screen",
                "children": [
                    {"type": "button", "styleToken": "", "children": []},
                    {"type": "input", "styleToken": "", "children": []},
                    {"type": "slider", "styleToken": "", "children": []},
                    {"type": "dropdown", "styleToken": "", "children": []},
                ],
            }
        }
        kit = {
            "textures": {
                "buttonDefault": {"states": {state: {"unrealPath": f"/Game/Button/{state}"} for state in ("normal", "hover", "pressed", "disabled")}},
                "inputDefault": {"states": {state: {"unrealPath": f"/Game/Input/{state}"} for state in ("normal", "focused", "disabled", "error")}},
                "sliderTrack": {"states": {state: {"unrealPath": f"/Game/SliderTrack/{state}"} for state in ("normal", "disabled")}},
                "sliderFill": {"states": {state: {"unrealPath": f"/Game/SliderFill/{state}"} for state in ("normal", "disabled")}},
                "sliderThumb": {"states": {state: {"unrealPath": f"/Game/SliderThumb/{state}"} for state in ("normal", "hover", "disabled")}},
                "dropdownBox": {"states": {state: {"unrealPath": f"/Game/DropdownBox/{state}"} for state in ("normal", "open", "disabled")}},
                "dropdownArrow": {"states": {state: {"unrealPath": f"/Game/DropdownArrow/{state}"} for state in ("normal", "open", "disabled")}},
                "dropdownOption": {"states": {state: {"unrealPath": f"/Game/DropdownOption/{state}"} for state in ("normal", "hover", "selected")}},
            }
        }

        result = validate_structure_with_kit(structure, kit)

        self.assertTrue(result["ok"])
        self.assertEqual(result["required"]["buttonDefault"], ["disabled", "hover", "normal", "pressed"])
        self.assertEqual(result["required"]["sliderThumb"], ["disabled", "hover", "normal"])

    def test_validate_structure_falls_back_from_custom_style_token_to_default_type_token(self) -> None:
        structure = {
            "root": {
                "type": "screen",
                "children": [
                    {"type": "panel", "styleToken": "topHudPanel", "width": 320, "height": 96, "children": []},
                    {"type": "button", "styleToken": "resourceBox", "width": 160, "height": 64, "children": []},
                    {"type": "text", "styleToken": "", "children": []},
                ],
            }
        }
        kit = {
            "textures": {
                "panelDefault": {"states": {"normal": {"unrealPath": "/Game/UI/Panel"}}},
                "buttonDefault": {"states": {state: {"unrealPath": f"/Game/UI/Button_{state}"} for state in ("normal", "hover", "pressed", "disabled")}},
            }
        }

        result = validate_structure_with_kit(structure, kit)

        self.assertTrue(result["ok"])
        self.assertIn("panelDefault", result["required"])
        self.assertIn("buttonDefault", result["required"])
        self.assertNotIn("topHudPanel", result["required"])
        self.assertNotIn("resourceBox", result["required"])
        self.assertNotIn("textPlate", result["required"])

    def test_export_umg_script_loads_existing_unreal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            html = root / "ui" / "html" / "shop_screen.html"
            html.parent.mkdir(parents=True)
            html.write_text(RESPONSIVE_SCREEN_HTML, encoding="utf-8")
            with patch("uim_core.game_ui._bake_html_with_playwright", _fake_bake):
                structure = bake_game_ui_html(root, "shopScreen", "ui/html/shop_screen.html")
            files = [
                {"token": "primaryButton", "state": state, "unrealPath": f"/Game/UIM/UI/T_primary_{state}"}
                for state in ("normal", "hover", "pressed", "disabled")
            ]
            kit = register_texture_kit(root, "Existing", files)

            result = export_game_ui_umg(root, "shopScreen", structure["path"], kit["path"])
            script = Path(result["script"]).read_text(encoding="utf-8")

            self.assertIn('unreal.load_asset(unreal_path)', script)
            self.assertIn("/Game/UIM/UI/T_primary_normal", script)

    def test_mcp_write_html_updates_game_ui_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            prompt_result = mcp_game_ui.game_ui_get_dsl_prompt(str(root))
            result = mcp_game_ui.game_ui_write_html(
                str(root),
                "shopScreen",
                RESPONSIVE_SCREEN_HTML,
                dsl_prompt_token=str(prompt_result["dslPromptToken"]),
            )
            workspace = load_project_workspace(root)
            index = load_asset_index(root, "shopscreen")

            self.assertTrue(result["ok"])
            self.assertTrue(result["dslPromptGrant"]["used"])
            self.assertEqual(workspace["mcpUiState"]["mainTab"], "game_ui")
            self.assertEqual(workspace["mcpUiState"]["assetName"], "shopScreen")
            self.assertEqual(index.kind, "game_ui")

    def test_mcp_current_html_flow_writes_without_project_root_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            with patch.dict(os.environ, {"UIM_CURRENT_PROJECT": str(root)}):
                prompt_result = mcp_game_ui.game_ui_get_current_dsl_prompt()
                result = mcp_game_ui.game_ui_write_current_html(
                    "shopScreen",
                    RESPONSIVE_SCREEN_HTML,
                    dsl_prompt_token=str(prompt_result["dslPromptToken"]),
                )

            self.assertTrue(prompt_result["ok"])
            self.assertTrue(result["ok"])
            self.assertEqual(result["path"], "ui/html/shopscreen.html")

    def test_mcp_current_workspace_flow_uses_saved_current_project_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            pointer = Path(tmp) / "current-project.json"
            create_project(root, "Demo")

            with (
                patch("uim_core.project.current_project_pointer_path", return_value=pointer),
                patch("uim_core.project.workspace_root", return_value=Path(tmp)),
                patch.dict(os.environ, {"UIM_CURRENT_PROJECT": "", "UIM_CURRENT_PROJECT_POINTER": ""}, clear=False),
            ):
                save_current_project_root(root)
                prompt_result = mcp_game_ui.game_ui_get_current_dsl_prompt()
                result = mcp_game_ui.game_ui_write_current_html(
                    "shopScreen",
                    RESPONSIVE_SCREEN_HTML,
                    dsl_prompt_token=str(prompt_result["dslPromptToken"]),
                )

            self.assertTrue(prompt_result["ok"])
            self.assertTrue(result["ok"])
            self.assertEqual(result["path"], "ui/html/shopscreen.html")

    def test_mcp_write_html_requires_dsl_prompt_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")

            result = mcp_game_ui.game_ui_write_html(str(root), "shopScreen", '<div data-u-type="screen" data-u-name="shopScreen"></div>')

            self.assertFalse(result["ok"])
            self.assertIn("requires dsl_prompt_token", result["error"])
            self.assertFalse((root / "ui" / "html" / "shopscreen.html").exists())

    def test_mcp_write_html_consumes_dsl_prompt_token_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            create_project(root, "Demo")
            prompt_result = mcp_game_ui.game_ui_get_dsl_prompt(str(root))
            token = str(prompt_result["dslPromptToken"])
            html = RESPONSIVE_SCREEN_HTML

            first = mcp_game_ui.game_ui_write_html(str(root), "shopScreen", html, dsl_prompt_token=token)
            second = mcp_game_ui.game_ui_write_html(str(root), "shopScreen2", html, dsl_prompt_token=token)

            self.assertTrue(first["ok"])
            self.assertFalse(second["ok"])
            self.assertIn("No active Game UI DSL prompt grant", second["error"])


if __name__ == "__main__":
    unittest.main()
