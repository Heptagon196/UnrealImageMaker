from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uim_core.image_processing import alpha_bounds, nearest_scale, split_fixed_grid, trim_transparent


class ImageProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        self.Image = Image

    def test_trim_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "trimmed.png"
            image = self.Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            for x in range(4, 8):
                for y in range(5, 9):
                    image.putpixel((x, y), (255, 0, 0, 255))
            image.save(source)

            bounds = trim_transparent(source, output, padding=1)
            self.assertIsNotNone(bounds)
            self.assertEqual(bounds.width, 6)
            self.assertEqual(bounds.height, 6)
            self.assertEqual(alpha_bounds(output).width, 4)

    def test_split_fixed_grid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.png"
            image = self.Image.new("RGBA", (8, 4), (0, 0, 0, 0))
            for x in range(0, 4):
                for y in range(0, 4):
                    image.putpixel((x, y), (255, 255, 255, 255))
            image.save(sheet)
            frames = split_fixed_grid(sheet, root / "frames", 4, 4)
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]["width"], 4)

    def test_nearest_scale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "scaled.png"
            self.Image.new("RGBA", (2, 3), (255, 0, 0, 255)).save(source)
            nearest_scale(source, output, 3)
            with self.Image.open(output) as scaled:
                self.assertEqual(scaled.size, (6, 9))


if __name__ == "__main__":
    unittest.main()
