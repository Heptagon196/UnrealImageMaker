from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import shutil
from uuid import uuid4

from .json_io import read_json, write_json

ASSET_INDEX_SCHEMA = "uim.asset_index.v1"
ASSET_INDEX_FILE = "asset.index.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def asset_id_from_name(name: str) -> str:
    value = "_".join(name.strip().lower().split())
    return "".join(char for char in value if char.isalnum() or char in {"_", "-"}) or str(uuid4())


def versioned_filename(role: str, suffix: str = ".png") -> str:
    clean_role = asset_id_from_name(role)
    return f"{clean_role}_{_stamp()}_{uuid4().hex[:6]}{suffix}"


@dataclass(slots=True)
class AssetImageVersion:
    id: str
    role: str
    label: str
    path: str
    created_at: str = field(default_factory=_now)
    order: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "role": self.role,
            "label": self.label,
            "path": self.path,
            "createdAt": self.created_at,
            "order": self.order,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AssetImageVersion":
        return cls(
            id=str(data.get("id") or uuid4()),
            role=str(data.get("role") or "image"),
            label=str(data.get("label") or data.get("path") or "image"),
            path=str(data.get("path") or ""),
            created_at=str(data.get("createdAt") or data.get("created_at") or _now()),
            order=int(data.get("order") or 0),
        )


@dataclass(slots=True)
class AssetIndex:
    asset_id: str
    display_name: str
    kind: str = ""
    settings: dict[str, object] = field(default_factory=dict)
    versions: list[AssetImageVersion] = field(default_factory=list)
    schema: str = ASSET_INDEX_SCHEMA

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "schema": self.schema,
            "assetId": self.asset_id,
            "displayName": self.display_name,
            "versions": [version.to_dict() for version in sorted_versions(self.versions)],
        }
        if self.kind:
            data["kind"] = self.kind
        if self.settings:
            data["settings"] = self.settings
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object], fallback_asset_id: str, fallback_display_name: str) -> "AssetIndex":
        versions = data.get("versions") if isinstance(data.get("versions"), list) else []
        return cls(
            schema=str(data.get("schema") or ASSET_INDEX_SCHEMA),
            asset_id=str(data.get("assetId") or data.get("asset_id") or fallback_asset_id),
            display_name=str(data.get("displayName") or data.get("display_name") or fallback_display_name),
            kind=str(data.get("kind") or data.get("assetKind") or data.get("asset_kind") or ""),
            settings=dict(data.get("settings")) if isinstance(data.get("settings"), dict) else {},
            versions=[AssetImageVersion.from_dict(item) for item in versions if isinstance(item, dict)],
        )


def sorted_versions(versions: list[AssetImageVersion]) -> list[AssetImageVersion]:
    return sorted(versions, key=lambda item: (item.order, item.created_at), reverse=False)


def asset_root(project_root: Path, asset_id: str) -> Path:
    return project_root / "assets" / asset_id


def asset_index_path(project_root: Path, asset_id: str) -> Path:
    return asset_root(project_root, asset_id) / ASSET_INDEX_FILE


def project_relative_path(project_root: Path, image_path: Path | str) -> str:
    root = project_root.resolve()
    candidate = Path(image_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    resolved.relative_to(root)
    return resolved.relative_to(root).as_posix()


def load_asset_index(project_root: Path, asset_id: str, display_name: str | None = None) -> AssetIndex:
    path = asset_index_path(project_root, asset_id)
    fallback_name = display_name or asset_id
    if not path.exists():
        return AssetIndex(asset_id=asset_id, display_name=fallback_name)
    return AssetIndex.from_dict(read_json(path), asset_id, fallback_name)


def save_asset_index(project_root: Path, index: AssetIndex) -> None:
    path = asset_index_path(project_root, index.asset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted_versions(index.versions)
    for order, version in enumerate(ordered):
        version.order = order
    index.versions = ordered
    write_json(path, index.to_dict())


def register_asset_version(
    project_root: Path,
    asset_name: str,
    image_path: Path | str,
    role: str,
    label: str | None = None,
    asset_id: str | None = None,
    kind: str | None = None,
) -> AssetIndex:
    resolved_asset_id = asset_id or asset_id_from_name(asset_name)
    rel_path = project_relative_path(project_root, image_path)
    index = load_asset_index(project_root, resolved_asset_id, asset_name)
    index.display_name = asset_name or index.display_name
    if kind:
        index.kind = kind
    remaining = [version for version in index.versions if version.path != rel_path]
    version = AssetImageVersion(
        id=f"{asset_id_from_name(role)}_{uuid4().hex[:8]}",
        role=role,
        label=label or role,
        path=rel_path,
        order=0,
    )
    index.versions = [version, *remaining]
    save_asset_index(project_root, index)
    return index


def reorder_asset_versions(project_root: Path, asset_id: str, version_ids: list[str]) -> AssetIndex:
    index = load_asset_index(project_root, asset_id)
    by_id = {version.id: version for version in index.versions}
    ordered = [by_id[version_id] for version_id in version_ids if version_id in by_id]
    ordered.extend(version for version in index.versions if version.id not in version_ids)
    index.versions = ordered
    save_asset_index(project_root, index)
    return index


def delete_asset_version(project_root: Path, asset_id: str, version_id: str) -> AssetIndex:
    index = load_asset_index(project_root, asset_id)
    removed = [version for version in index.versions if version.id == version_id]
    index.versions = [version for version in index.versions if version.id != version_id]
    for version in removed:
        target = (project_root / version.path).resolve()
        try:
            target.relative_to(project_root.resolve())
        except ValueError:
            continue
        if target.exists() and target.is_file():
            target.unlink()
    save_asset_index(project_root, index)
    return index


def delete_asset(project_root: Path, asset_id: str) -> None:
    root = project_root.resolve()
    target = asset_root(root, asset_id).resolve()
    target.relative_to(root / "assets")
    if target.exists() and target.is_dir():
        shutil.rmtree(target)


def primary_version(index: AssetIndex) -> AssetImageVersion | None:
    return next((version for version in sorted_versions(index.versions) if version.path), None)


def asset_index_to_record(project_root: Path, index: AssetIndex, manifest: dict[str, object] | None = None) -> dict[str, object]:
    primary = primary_version(index)
    current_manifest = dict(manifest or {})
    if primary and current_manifest.get("assetType") == "texture":
        files = current_manifest.get("files") if isinstance(current_manifest.get("files"), list) else []
        current_manifest["files"] = [{"role": primary.role, "path": primary.path}, *files[1:]]
    return {
        "id": index.asset_id,
        "name": index.display_name,
        "kind": index.kind,
        "type": str(current_manifest.get("assetType") or "asset"),
        "path": primary.path if primary else "",
        "manifest": current_manifest,
        "settings": index.settings,
        "versions": [version.to_dict() for version in sorted_versions(index.versions)],
    }


def sync_texture_manifest_primary(project_root: Path, asset_id: str) -> None:
    manifest_path = asset_root(project_root, asset_id) / "manifests" / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = read_json(manifest_path)
    if manifest.get("assetType") != "texture":
        return
    index = load_asset_index(project_root, asset_id, str(manifest.get("displayName") or asset_id))
    primary = primary_version(index)
    if not primary:
        return
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    manifest["files"] = [{"role": primary.role, "path": primary.path}, *files[1:]]
    write_json(manifest_path, manifest)


def sync_asset_and_record(project_root: Path, index: AssetIndex, manifest: dict[str, object] | None = None) -> dict[str, object]:
    sync_texture_manifest_primary(project_root, index.asset_id)
    if manifest is None:
        manifest_path = asset_root(project_root, index.asset_id) / "manifests" / "manifest.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {}
    return asset_index_to_record(project_root, index, manifest)
