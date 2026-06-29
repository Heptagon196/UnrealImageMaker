from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..models import MODEL_REGISTRY, install_marker, model_dir, model_status


@dataclass(slots=True)
class SamPrompt:
    points: Sequence[tuple[int, int]] | None = None
    labels: Sequence[int] | None = None
    box: tuple[int, int, int, int] | None = None


class Sam21Adapter:
    def __init__(self, cache_dir: Path, model_id: str = "sam2.1_hiera_small") -> None:
        self.cache_dir = cache_dir
        self.model_id = model_id

    def status(self) -> str:
        return model_status(self.cache_dir, self.model_id)

    def ensure_declared(self) -> Path:
        spec = MODEL_REGISTRY[self.model_id]
        return install_marker(self.cache_dir, spec)

    def checkpoint_path(self) -> Path:
        return self.local_path() / f"{self.model_id}.pt"

    def download_checkpoint(self) -> Path:
        spec = MODEL_REGISTRY[self.model_id]
        if not spec.download_url:
            raise RuntimeError(f"Model {self.model_id} has no download URL")
        import requests

        path = self.local_path()
        path.mkdir(parents=True, exist_ok=True)
        checkpoint = self.checkpoint_path()
        with requests.get(spec.download_url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with checkpoint.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        install_marker(self.cache_dir, spec)
        return checkpoint

    def local_path(self) -> Path:
        return model_dir(self.cache_dir, self.model_id)

    def available(self) -> bool:
        try:
            import torch  # noqa: F401
            import torchvision  # noqa: F401
        except ImportError:
            return False
        return self.status() == "installed"

    def segment(self, image_path: Path, output_mask_path: Path, prompt: SamPrompt) -> Path:
        if not self.available():
            raise RuntimeError(
                "SAM 2.1 runtime is not installed or the selected checkpoint is missing. "
                "Install SAM runtime and download the checkpoint before using it."
            )
        import numpy as np
        import torch
        from PIL import Image
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        spec = MODEL_REGISTRY[self.model_id]
        checkpoint = self.checkpoint_path()
        if not checkpoint.exists():
            raise RuntimeError(f"SAM checkpoint is missing: {checkpoint}")
        if not spec.config_name:
            raise RuntimeError(f"SAM config is missing for {self.model_id}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        predictor = SAM2ImagePredictor(build_sam2(spec.config_name, str(checkpoint), device=device))
        image = np.array(Image.open(image_path).convert("RGB"))
        point_coords = np.array(prompt.points, dtype=np.float32) if prompt.points else None
        point_labels = np.array(prompt.labels, dtype=np.int32) if prompt.labels else None
        box = np.array(prompt.box, dtype=np.float32) if prompt.box else None

        context = torch.autocast("cuda", dtype=torch.bfloat16) if device == "cuda" else torch.autocast("cpu", enabled=False)
        with torch.inference_mode(), context:
            predictor.set_image(image)
            masks, scores, _ = predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                box=box,
                multimask_output=True,
            )

        best_index = int(np.argmax(scores)) if len(scores) else 0
        mask = (masks[best_index] > 0).astype(np.uint8) * 255
        output_mask_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(mask, mode="L").save(output_mask_path)
        return output_mask_path
