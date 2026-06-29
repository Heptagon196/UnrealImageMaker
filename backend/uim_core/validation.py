from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .manifest import AssetManifest, validate_manifest


@dataclass(slots=True)
class ValidationIssue:
    code: str
    severity: str
    message: str


def validate_asset_manifest(manifest: AssetManifest) -> list[ValidationIssue]:
    issues = [
        ValidationIssue(code="manifest", severity="error", message=message)
        for message in validate_manifest(manifest)
    ]
    if "unreal" not in manifest.targets:
        issues.append(
            ValidationIssue(
                code="missing_unreal_target",
                severity="warning",
                message="未配置 Unreal 导出目标。",
            )
        )
    return issues


def validate_file_exists(root: Path, manifest: AssetManifest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for file in manifest.files:
        if not (root / file.path).exists():
            issues.append(
                ValidationIssue(
                    code="missing_file",
                    severity="error",
                    message=f"文件不存在：{file.path}",
                )
            )
    return issues


def validate_frame_consistency(manifest: AssetManifest) -> list[ValidationIssue]:
    if not manifest.frames:
        return []
    first = manifest.frames[0]
    issues: list[ValidationIssue] = []
    for frame in manifest.frames[1:]:
        if frame.width != first.width or frame.height != first.height:
            issues.append(
                ValidationIssue(
                    code="frame_size_mismatch",
                    severity="warning",
                    message=f"帧 {frame.name} 尺寸和首帧不一致。",
                )
            )
    return issues
