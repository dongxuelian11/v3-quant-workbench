"""Runtime consumer for the generated V3 exact-build identity manifest."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


BUILD_MANIFEST_SCHEMA_VERSION = "v3.build-manifest/1.0.0"
BUILD_MANIFEST_FILENAME = "build_manifest.generated.json"
_ID_PREFIX = "bmanifest_sha256_"


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _stable_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": raw.get("schema_version"),
        "git_commit_sha": raw.get("git_commit_sha"),
        "git_tree_sha": raw.get("git_tree_sha"),
        "dirty_state": raw.get("dirty_state"),
        "package_identity": raw.get("package_identity"),
        "package_lock_sha256": raw.get("package_lock_sha256"),
        "backend_dependency_authority": raw.get("backend_dependency_authority"),
        "contract_schema_migration_levels": raw.get("contract_schema_migration_levels"),
    }


def _unavailable(reason: str) -> "BuildManifest":
    return BuildManifest(
        schema_version=BUILD_MANIFEST_SCHEMA_VERSION,
        build_manifest_id=None,
        git_commit_sha=None,
        git_tree_sha=None,
        dirty_state="UNKNOWN",
        package_identity={},
        package_lock_sha256=None,
        backend_dependency_authority={},
        contract_schema_migration_levels={},
        generated_at=None,
        unavailable_reason=reason,
    )


@dataclass(frozen=True, slots=True)
class BuildManifest:
    schema_version: str
    build_manifest_id: str | None
    git_commit_sha: str | None
    git_tree_sha: str | None
    dirty_state: str
    package_identity: Mapping[str, Any]
    package_lock_sha256: str | None
    backend_dependency_authority: Mapping[str, Any]
    contract_schema_migration_levels: Mapping[str, Any]
    generated_at: str | None
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.build_manifest_id is not None and self.dirty_state in {"CLEAN", "DIRTY"}

    @property
    def code_version(self) -> str:
        if self.build_manifest_id is None:
            return "UNAVAILABLE:BUILD_MANIFEST_MISSING"
        return f"build:{self.build_manifest_id}:{self.dirty_state}"

    def stable_payload(self) -> dict[str, Any]:
        return _stable_payload(self.to_wire(include_generated_at=False))

    def to_wire(self, *, include_generated_at: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "build_manifest_id": self.build_manifest_id,
            "git_commit_sha": self.git_commit_sha,
            "git_tree_sha": self.git_tree_sha,
            "dirty_state": self.dirty_state,
            "package_identity": dict(self.package_identity),
            "package_lock_sha256": self.package_lock_sha256,
            "backend_dependency_authority": dict(self.backend_dependency_authority),
            "contract_schema_migration_levels": dict(self.contract_schema_migration_levels),
        }
        if include_generated_at:
            value["generated_at"] = self.generated_at
        if self.unavailable_reason is not None:
            value["unavailable_reason"] = self.unavailable_reason
        return value

    def health_wire(self) -> dict[str, Any]:
        # Health crosses the Desktop bridge, whose safety gate rejects raw
        # filesystem/storage paths. Keep the exact identity fields and the
        # authority digests, but project path-bearing file inventories to
        # bounded hash-only summaries. The full generated manifest remains a
        # bundled runtime input; it is not a reason to leak host paths.
        wire = self.to_wire()
        wire.pop("unavailable_reason", None)
        dependency = dict(self.backend_dependency_authority)
        dependency_files = dependency.get("files")
        dependency_hashes = [
            str(item["sha256"])
            for item in dependency_files
            if isinstance(item, Mapping) and isinstance(item.get("sha256"), str)
        ] if isinstance(dependency_files, list) else []
        wire["backend_dependency_authority"] = {
            "authority_sha256": dependency.get("authority_sha256"),
            "file_count": len(dependency_hashes),
            "file_sha256s": dependency_hashes,
        }
        migrations = dict(self.contract_schema_migration_levels)
        wire["contract_schema_migration_levels"] = {
            key: migrations[key]
            for key in (
                "asl_api_version",
                "local_transport_protocol",
                "schema_compatibility",
                "migration_application_version",
                "migration_set_sha256",
            )
            if key in migrations
        }
        return {
            "build_manifest_id": self.build_manifest_id,
            "build_identity_state": self.dirty_state if self.available else "UNAVAILABLE",
            "build_manifest": wire,
        }


def _manifest_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).resolve()
    configured = os.environ.get("V3_BUILD_MANIFEST_PATH")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).with_name(BUILD_MANIFEST_FILENAME)


def load_build_manifest(path: str | Path | None = None) -> BuildManifest:
    manifest_path = _manifest_path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _unavailable(f"manifest_unavailable:{manifest_path}")
    if not isinstance(raw, dict):
        return _unavailable("manifest_not_object")
    stable = _stable_payload(raw)
    if stable["schema_version"] != BUILD_MANIFEST_SCHEMA_VERSION:
        return _unavailable("manifest_schema_version_invalid")
    manifest_id = raw.get("build_manifest_id")
    if not isinstance(manifest_id, str) or not manifest_id.startswith(_ID_PREFIX):
        return _unavailable("manifest_id_invalid")
    expected_id = _ID_PREFIX + hashlib.sha256(_canonical_bytes(stable)).hexdigest()
    if manifest_id != expected_id:
        return _unavailable("manifest_id_mismatch")
    dirty_state = raw.get("dirty_state")
    if dirty_state not in {"CLEAN", "DIRTY"}:
        return _unavailable("manifest_dirty_state_invalid")
    return BuildManifest(
        schema_version=str(raw["schema_version"]),
        build_manifest_id=manifest_id,
        git_commit_sha=raw.get("git_commit_sha") if isinstance(raw.get("git_commit_sha"), str) else None,
        git_tree_sha=raw.get("git_tree_sha") if isinstance(raw.get("git_tree_sha"), str) else None,
        dirty_state=str(dirty_state),
        package_identity=raw.get("package_identity") if isinstance(raw.get("package_identity"), dict) else {},
        package_lock_sha256=raw.get("package_lock_sha256") if isinstance(raw.get("package_lock_sha256"), str) else None,
        backend_dependency_authority=(
            raw.get("backend_dependency_authority")
            if isinstance(raw.get("backend_dependency_authority"), dict)
            else {}
        ),
        contract_schema_migration_levels=(
            raw.get("contract_schema_migration_levels")
            if isinstance(raw.get("contract_schema_migration_levels"), dict)
            else {}
        ),
        generated_at=raw.get("generated_at") if isinstance(raw.get("generated_at"), str) else None,
    )


BUILD_MANIFEST = load_build_manifest()
BUILD_MANIFEST_ID = BUILD_MANIFEST.build_manifest_id
PRODUCT_CODE_VERSION = BUILD_MANIFEST.code_version


__all__ = [
    "BUILD_MANIFEST",
    "BUILD_MANIFEST_FILENAME",
    "BUILD_MANIFEST_ID",
    "BUILD_MANIFEST_SCHEMA_VERSION",
    "BuildManifest",
    "PRODUCT_CODE_VERSION",
    "load_build_manifest",
]
