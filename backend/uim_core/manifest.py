from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .constants import MANIFEST_SCHEMA
from .json_io import write_json

AssetType = Literal["texture", "spritesheet", "animation", "ui_kit", "nine_slice"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class AssetFile:
    role: str
    path: str
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    checksum: str | None = None


@dataclass(slots=True)
class SpriteFrame:
    name: str
    x: int
    y: int
    width: int
    height: int
    pivot: tuple[float, float] = (0.5, 0.5)
    source_rect: dict[str, int] | None = None
    trim_rect: dict[str, int] | None = None


@dataclass(slots=True)
class AnimationSequence:
    name: str
    frame_names: list[str]
    fps: float = 12.0
    loop: bool = True


@dataclass(slots=True)
class NineSlice:
    left: int
    top: int
    right: int
    bottom: int


@dataclass(slots=True)
class UIState:
    name: str
    file: str
    width: int | None = None
    height: int | None = None


@dataclass(slots=True)
class AssetManifest:
    asset_type: AssetType
    asset_id: str
    display_name: str
    style_profile: str
    files: list[AssetFile] = field(default_factory=list)
    frames: list[SpriteFrame] = field(default_factory=list)
    animations: list[AnimationSequence] = field(default_factory=list)
    ui_states: list[UIState] = field(default_factory=list)
    nine_slice: NineSlice | None = None
    processing: dict[str, Any] = field(default_factory=dict)
    targets: dict[str, Any] = field(default_factory=dict)
    schema: str = MANIFEST_SCHEMA
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["assetType"] = data.pop("asset_type")
        data["id"] = data.pop("asset_id")
        data["displayName"] = data.pop("display_name")
        data["styleProfile"] = data.pop("style_profile")
        data["createdAt"] = data.pop("created_at")
        data["updatedAt"] = data.pop("updated_at")
        if data.get("nine_slice") is None:
            data.pop("nine_slice")
        else:
            data["nineSlice"] = data.pop("nine_slice")
        data["uiStates"] = data.pop("ui_states")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetManifest":
        return cls(
            asset_type=data["assetType"],
            asset_id=data["id"],
            display_name=data["displayName"],
            style_profile=data["styleProfile"],
            files=[AssetFile(**item) for item in data.get("files", [])],
            frames=[
                SpriteFrame(
                    name=item["name"],
                    x=int(item["x"]),
                    y=int(item["y"]),
                    width=int(item.get("width", item.get("w", 0))),
                    height=int(item.get("height", item.get("h", 0))),
                    pivot=tuple(item.get("pivot", (0.5, 0.5))),
                    source_rect=item.get("source_rect") or item.get("sourceRect"),
                    trim_rect=item.get("trim_rect") or item.get("trimRect"),
                )
                for item in data.get("frames", [])
            ],
            animations=[AnimationSequence(**item) for item in data.get("animations", [])],
            ui_states=[UIState(**item) for item in data.get("uiStates", data.get("ui_states", []))],
            nine_slice=NineSlice(**data["nineSlice"]) if data.get("nineSlice") else None,
            processing=dict(data.get("processing", {})),
            targets=dict(data.get("targets", {})),
            schema=str(data.get("schema", MANIFEST_SCHEMA)),
            created_at=str(data.get("createdAt", _now())),
            updated_at=str(data.get("updatedAt", _now())),
        )


def write_manifest(path: Path, manifest: AssetManifest) -> None:
    write_json(path, manifest.to_dict())


def validate_manifest(manifest: AssetManifest) -> list[str]:
    errors: list[str] = []
    if manifest.schema != MANIFEST_SCHEMA:
        errors.append(f"Unsupported manifest schema: {manifest.schema}")
    if not manifest.asset_id:
        errors.append("Manifest id is required")
    if not manifest.display_name:
        errors.append("Manifest displayName is required")
    if not manifest.files:
        errors.append("Manifest must include at least one file")
    if manifest.asset_type == "spritesheet" and not manifest.frames:
        errors.append("SpriteSheetManifest must include frames")
    if manifest.asset_type == "animation" and not manifest.animations:
        errors.append("AnimationManifest must include animations")
    if manifest.asset_type == "nine_slice" and manifest.nine_slice is None:
        errors.append("NineSliceManifest must include nineSlice")
    if manifest.asset_type == "ui_kit" and not manifest.ui_states and not manifest.processing.get("uiConcept"):
        errors.append("UIKitManifest must include uiStates or uiConcept")
    return errors


def texture_manifest(asset_id: str, display_name: str, style_profile: str, image_path: str) -> AssetManifest:
    return AssetManifest(
        asset_type="texture",
        asset_id=asset_id,
        display_name=display_name,
        style_profile=style_profile,
        files=[AssetFile(role="final", path=image_path)],
    )
