from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .json_io import read_json, write_json

ModelStatus = Literal["not_installed", "downloading", "installed", "update_available", "broken"]


@dataclass(slots=True)
class ModelSpec:
    id: str
    display_name: str
    provider: str
    task: str
    version: str
    license: str
    recommended_vram_gb: int
    size_hint: str
    source: str
    checksum: str | None = None
    download_url: str | None = None
    config_name: str | None = None


@dataclass(slots=True)
class LockedModel:
    id: str
    version: str
    source: str
    license: str
    checksum: str | None = None


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "rembg:u2netp": ModelSpec(
        id="rembg:u2netp",
        display_name="rembg u2netp",
        provider="rembg",
        task="background_removal",
        version="latest",
        license="model-specific",
        recommended_vram_gb=0,
        size_hint="small",
        source="rembg",
    ),
    "rembg:isnet-general-use": ModelSpec(
        id="rembg:isnet-general-use",
        display_name="rembg isnet-general-use",
        provider="rembg",
        task="background_removal",
        version="latest",
        license="model-specific",
        recommended_vram_gb=0,
        size_hint="medium",
        source="rembg",
    ),
    "rembg:isnet-anime": ModelSpec(
        id="rembg:isnet-anime",
        display_name="rembg isnet-anime",
        provider="rembg",
        task="background_removal",
        version="latest",
        license="model-specific",
        recommended_vram_gb=0,
        size_hint="medium",
        source="rembg",
    ),
    "sam2.1_hiera_tiny": ModelSpec(
        id="sam2.1_hiera_tiny",
        display_name="SAM 2.1 Hiera Tiny",
        provider="meta",
        task="segmentation",
        version="2.1",
        license="Apache-2.0",
        recommended_vram_gb=6,
        size_hint="39M params",
        source="https://github.com/facebookresearch/sam2",
        download_url="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt",
        config_name="configs/sam2.1/sam2.1_hiera_t.yaml",
    ),
    "sam2.1_hiera_small": ModelSpec(
        id="sam2.1_hiera_small",
        display_name="SAM 2.1 Hiera Small",
        provider="meta",
        task="segmentation",
        version="2.1",
        license="Apache-2.0",
        recommended_vram_gb=8,
        size_hint="small",
        source="https://github.com/facebookresearch/sam2",
        download_url="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt",
        config_name="configs/sam2.1/sam2.1_hiera_s.yaml",
    ),
    "sam2.1_hiera_base_plus": ModelSpec(
        id="sam2.1_hiera_base_plus",
        display_name="SAM 2.1 Hiera Base Plus",
        provider="meta",
        task="segmentation",
        version="2.1",
        license="Apache-2.0",
        recommended_vram_gb=10,
        size_hint="base_plus",
        source="https://github.com/facebookresearch/sam2",
        download_url="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt",
        config_name="configs/sam2.1/sam2.1_hiera_b+.yaml",
    ),
    "sam2.1_hiera_large": ModelSpec(
        id="sam2.1_hiera_large",
        display_name="SAM 2.1 Hiera Large",
        provider="meta",
        task="segmentation",
        version="2.1",
        license="Apache-2.0",
        recommended_vram_gb=12,
        size_hint="224M params",
        source="https://github.com/facebookresearch/sam2",
        download_url="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt",
        config_name="configs/sam2.1/sam2.1_hiera_l.yaml",
    ),
    "rmbg2.0": ModelSpec(
        id="rmbg2.0",
        display_name="BRIA RMBG 2.0",
        provider="bria",
        task="background_removal",
        version="2.0",
        license="requires-user-review",
        recommended_vram_gb=6,
        size_hint="0.2B params",
        source="https://huggingface.co/briaai/RMBG-2.0",
    ),
}


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_dir(cache_dir: Path, model_id: str) -> Path:
    child = model_id.replace(":", "_")
    if Path(child).name != child:
        raise ValueError(f"Invalid model id: {model_id}")
    return cache_dir / child


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _required_artifact(cache_dir: Path, spec: ModelSpec) -> Path | None:
    if spec.download_url:
        return model_dir(cache_dir, spec.id) / f"{spec.id}.pt"
    return None


def model_status(cache_dir: Path, model_id: str) -> ModelStatus:
    spec = MODEL_REGISTRY.get(model_id)
    if not spec:
        return "broken"
    path = model_dir(cache_dir, model_id)
    if not path.exists():
        return "not_installed"
    marker = path / "model.uim.json"
    if not marker.exists():
        return "broken"
    artifact = _required_artifact(cache_dir, spec)
    if artifact and not artifact.exists():
        return "broken"
    return "installed"


def install_marker(cache_dir: Path, spec: ModelSpec) -> Path:
    path = model_dir(cache_dir, spec.id)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / "model.uim.json"
    write_json(marker, asdict(spec))
    return marker


def load_models_lock(path: Path) -> list[LockedModel]:
    if not path.exists():
        return []
    data = read_json(path)
    return [LockedModel(**item) for item in data.get("models", [])]


def write_models_lock(path: Path, models: list[LockedModel]) -> None:
    write_json(
        path,
        {
            "schema": "uim.models_lock.v1",
            "models": [asdict(model) for model in models],
        },
    )


def missing_locked_models(cache_dir: Path, models: list[LockedModel]) -> list[LockedModel]:
    return [model for model in models if model_status(cache_dir, model.id) != "installed"]


def lock_model(lock_path: Path, model_id: str) -> LockedModel:
    spec = MODEL_REGISTRY[model_id]
    models = load_models_lock(lock_path)
    locked = LockedModel(
        id=spec.id,
        version=spec.version,
        source=spec.source,
        license=spec.license,
        checksum=spec.checksum,
    )
    models = [model for model in models if model.id != model_id]
    models.append(locked)
    write_models_lock(lock_path, models)
    return locked


def delete_model(cache_dir: Path, model_id: str) -> bool:
    if model_id not in MODEL_REGISTRY:
        raise KeyError(f"Unknown model: {model_id}")
    cache = cache_dir.resolve()
    path = model_dir(cache, model_id).resolve()
    if not _is_relative_to(path, cache):
        raise ValueError(f"Model path escapes cache directory: {model_id}")
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True
