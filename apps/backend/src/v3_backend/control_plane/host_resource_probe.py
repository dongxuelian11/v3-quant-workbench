"""Parent-owned host resource observations used for runtime admission.

The probe deliberately reports host facts only.  It does not decide whether a
lease is admitted and it does not trust worker-provided RSS or scratch values.
The resource governor turns a snapshot into a bounded, content-addressed
grant; tests may inject ``StaticHostResourceProbe`` without changing the
production path.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class HostResourceProbeError(RuntimeError):
    """The parent could not obtain a trustworthy host resource snapshot."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class HostResourceSnapshot:
    logical_cpu_count: int
    total_physical_memory_bytes: int
    available_physical_memory_bytes: int
    scratch_free_bytes: int
    sampled_at: str
    source: str = "system"

    def __post_init__(self) -> None:
        for name in (
            "logical_cpu_count",
            "total_physical_memory_bytes",
            "available_physical_memory_bytes",
            "scratch_free_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
        if self.logical_cpu_count < 1:
            raise ValueError("logical_cpu_count must be positive")
        for name in (
            "total_physical_memory_bytes",
            "available_physical_memory_bytes",
            "scratch_free_bytes",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.available_physical_memory_bytes > self.total_physical_memory_bytes:
            raise ValueError("available physical memory cannot exceed total memory")
        if not isinstance(self.sampled_at, str) or not self.sampled_at:
            raise ValueError("sampled_at is required")
        try:
            sampled = datetime.fromisoformat(
                self.sampled_at[:-1] + "+00:00"
                if self.sampled_at.endswith("Z")
                else self.sampled_at
            )
        except ValueError as error:
            raise ValueError("sampled_at must be RFC3339") from error
        if sampled.tzinfo is None or sampled.utcoffset() is None:
            raise ValueError("sampled_at must be timezone-aware")
        if not isinstance(self.source, str) or not 1 <= len(self.source) <= 128:
            raise ValueError("source must be a bounded non-empty string")

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_cpu_count": self.logical_cpu_count,
            "total_physical_memory_bytes": self.total_physical_memory_bytes,
            "available_physical_memory_bytes": self.available_physical_memory_bytes,
            "scratch_free_bytes": self.scratch_free_bytes,
            "sampled_at": self.sampled_at,
            "source": self.source,
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class HostResourceProbe(Protocol):
    def sample(self) -> HostResourceSnapshot: ...


class StaticHostResourceProbe:
    """Deterministic probe adapter for unit/fault tests."""

    def __init__(self, snapshot: HostResourceSnapshot) -> None:
        self.snapshot = snapshot

    def sample(self) -> HostResourceSnapshot:
        return self.snapshot


class SystemHostResourceProbe:
    """Read host memory/CPU and the scratch volume from the parent process."""

    def __init__(self, scratch_root: str | Path | None = None) -> None:
        # Keep the lexical root so sample() can reject a symlink/reparse point
        # instead of resolving it away before the parent-side quota check.
        self.scratch_root = Path(scratch_root or Path.cwd()).absolute()

    @staticmethod
    def _is_reparse(stat_result: os.stat_result) -> bool:
        return stat.S_ISLNK(stat_result.st_mode) or bool(
            getattr(stat_result, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )

    @staticmethod
    def _windows_memory() -> tuple[int, int]:
        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            error = ctypes.get_last_error()
            raise HostResourceProbeError(f"GlobalMemoryStatusEx failed: {error}")
        return int(status.ullTotalPhys), int(status.ullAvailPhys)

    @staticmethod
    def _portable_memory() -> tuple[int, int]:
        if hasattr(os, "sysconf"):
            try:
                page_size = int(os.sysconf("SC_PAGE_SIZE"))
                total_pages = int(os.sysconf("SC_PHYS_PAGES"))
                available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
                return page_size * total_pages, page_size * available_pages
            except (OSError, ValueError):
                pass
        if sys.platform.startswith("linux"):
            values: dict[str, int] = {}
            try:
                for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                    key, _, raw = line.partition(":")
                    if key in {"MemTotal", "MemAvailable"}:
                        values[key] = int(raw.strip().split()[0]) * 1024
            except (OSError, ValueError):
                pass
            if values.get("MemTotal") and values.get("MemAvailable") is not None:
                return values["MemTotal"], values["MemAvailable"]
        raise HostResourceProbeError("portable physical memory API is unavailable")

    def sample(self) -> HostResourceSnapshot:
        try:
            try:
                root_stat = self.scratch_root.lstat()
            except OSError as error:
                raise HostResourceProbeError(
                    "scratch root cannot be inspected"
                ) from error
            if self._is_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
                raise HostResourceProbeError(
                    "scratch root is not a real directory"
                )
            if sys.platform == "win32":
                total, available = self._windows_memory()
            else:
                total, available = self._portable_memory()
            cpu_count = os.cpu_count() or 0
            if cpu_count < 1:
                raise HostResourceProbeError("logical CPU count is unavailable")
            scratch_free = int(shutil.disk_usage(self.scratch_root).free)
        except HostResourceProbeError:
            raise
        except (OSError, ValueError) as error:
            raise HostResourceProbeError(f"host resource probe failed: {error}") from error
        return HostResourceSnapshot(
            logical_cpu_count=cpu_count,
            total_physical_memory_bytes=total,
            available_physical_memory_bytes=available,
            scratch_free_bytes=scratch_free,
            sampled_at=_utc_now(),
            source="system-windows" if sys.platform == "win32" else "system-portable",
        )


__all__ = [
    "HostResourceProbe",
    "HostResourceProbeError",
    "HostResourceSnapshot",
    "StaticHostResourceProbe",
    "SystemHostResourceProbe",
]
