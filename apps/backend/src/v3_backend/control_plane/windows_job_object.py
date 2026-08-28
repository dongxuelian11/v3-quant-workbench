"""Windows Job Object hard-enforcement adapter for supervised workers."""

from __future__ import annotations

import ctypes
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RESOURCE_ENFORCEMENT_NOT_AVAILABLE = "RESOURCE_ENFORCEMENT_NOT_AVAILABLE"


class JobObjectEnforcementError(RuntimeError):
    """Job Object configuration or read-back failed."""


@dataclass(frozen=True)
class JobObjectQuery:
    process_id: int
    memory_limit_bytes: int
    cpu_rate_per_10000: int
    kill_on_close: bool
    hard_cpu_cap: bool


class WindowsJobObjectController:
    """Create one verified Job Object per Attempt.

    The adapter is intentionally Windows-only.  Calling it on another host is
    a hard failure, never a request to continue with soft sampling.
    """

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION = 15
    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
    _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self) -> None:
        self._jobs: dict[int, int] = {}
        self._queries: dict[int, JobObjectQuery] = {}

    @staticmethod
    def _process_id(process: Any) -> int:
        candidate = getattr(process, "pid", None)
        if candidate is None:
            candidate = getattr(getattr(process, "process", None), "pid", None)
        if not isinstance(candidate, int) or candidate <= 0:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: worker PID is unavailable"
            )
        return candidate

    @staticmethod
    def _handle_value(handle: object) -> int:
        """Normalize a ctypes handle without relying on ``int(c_void_p)``."""
        value = getattr(handle, "value", handle)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: Job Object handle is invalid"
            )
        return value

    @staticmethod
    def _load_kernel32() -> Any:
        if sys.platform != "win32":
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: Windows Job Objects are unavailable"
            )
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        kernel32.QueryInformationJobObject.restype = ctypes.c_int
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        return kernel32

    @staticmethod
    def _structures() -> tuple[type[ctypes.Structure], type[ctypes.Structure], type[ctypes.Structure]]:
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class CpuRateControlInformation(ctypes.Structure):
            _fields_ = [
                ("ControlFlags", ctypes.c_uint32),
                ("CpuRate", ctypes.c_uint32),
            ]

        return ExtendedLimitInformation, CpuRateControlInformation, BasicLimitInformation

    @staticmethod
    def _last_error(prefix: str) -> JobObjectEnforcementError:
        error = ctypes.get_last_error()
        return JobObjectEnforcementError(f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: {prefix} ({error})")

    def assign(self, process: Any, grant: Any) -> None:
        process_key = id(process)
        if process_key in self._jobs:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: process already assigned"
            )
        pid = self._process_id(process)
        memory_limit = getattr(grant, "memory_hard_limit_bytes", None)
        cpu_rate = getattr(grant, "job_cpu_rate_per_10000", None)
        if not isinstance(memory_limit, int) or memory_limit <= 0:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: invalid memory hard limit"
            )
        if not isinstance(cpu_rate, int) or not 1 <= cpu_rate <= 10000:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: invalid CPU hard cap"
            )

        kernel32 = self._load_kernel32()
        ExtendedLimitInformation, CpuRateControlInformation, _ = self._structures()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise self._last_error("CreateJobObjectW failed")
        process_handle = None
        try:
            limits = ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = (
                self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | self._JOB_OBJECT_LIMIT_JOB_MEMORY
            )
            limits.JobMemoryLimit = memory_limit
            if not kernel32.SetInformationJobObject(
                job,
                self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise self._last_error("SetInformationJobObject extended limits failed")

            cpu = CpuRateControlInformation()
            cpu.ControlFlags = (
                self._JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
                | self._JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            )
            cpu.CpuRate = cpu_rate
            if not kernel32.SetInformationJobObject(
                job,
                self._JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
                ctypes.byref(cpu),
                ctypes.sizeof(cpu),
            ):
                raise self._last_error("SetInformationJobObject CPU limits failed")

            process_handle = kernel32.OpenProcess(
                self._PROCESS_SET_QUOTA
                | self._PROCESS_TERMINATE
                | self._PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                pid,
            )
            if not process_handle:
                raise self._last_error("OpenProcess failed")
            if not kernel32.AssignProcessToJobObject(job, process_handle):
                raise self._last_error("AssignProcessToJobObject failed")

            observed_limits = ExtendedLimitInformation()
            returned = ctypes.c_uint32()
            if not kernel32.QueryInformationJobObject(
                job,
                self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(observed_limits),
                ctypes.sizeof(observed_limits),
                ctypes.byref(returned),
            ):
                raise self._last_error("QueryInformationJobObject extended limits failed")
            observed_cpu = CpuRateControlInformation()
            if not kernel32.QueryInformationJobObject(
                job,
                self._JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
                ctypes.byref(observed_cpu),
                ctypes.sizeof(observed_cpu),
                ctypes.byref(returned),
            ):
                raise self._last_error("QueryInformationJobObject CPU limits failed")
            observed_flags = observed_limits.BasicLimitInformation.LimitFlags
            if (
                observed_limits.JobMemoryLimit != memory_limit
                or not (observed_flags & self._JOB_OBJECT_LIMIT_JOB_MEMORY)
                or not (observed_flags & self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
                or observed_cpu.CpuRate != cpu_rate
                or not (
                    observed_cpu.ControlFlags
                    & self._JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
                )
                or not (
                    observed_cpu.ControlFlags
                    & self._JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
                )
            ):
                raise JobObjectEnforcementError(
                    f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: Job Object query mismatch"
                )
            job_value = self._handle_value(job)
            self._jobs[process_key] = job_value
            self._queries[process_key] = JobObjectQuery(
                process_id=pid,
                memory_limit_bytes=memory_limit,
                cpu_rate_per_10000=cpu_rate,
                kill_on_close=True,
                hard_cpu_cap=True,
            )
        except Exception:
            kernel32.CloseHandle(job)
            raise
        finally:
            if process_handle:
                kernel32.CloseHandle(process_handle)

    def query(self, process: Any) -> JobObjectQuery:
        query = self._queries.get(id(process))
        if query is None:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: Job Object assignment is missing"
            )
        return query

    @staticmethod
    def _is_reparse(stat_result: os.stat_result) -> bool:
        return stat.S_ISLNK(stat_result.st_mode) or bool(
            getattr(stat_result, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )

    @staticmethod
    def _directory_size(root: str | os.PathLike[str] | None) -> int:
        if root is None:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: dedicated scratch root is missing"
            )
        root_path = Path(root)
        try:
            root_stat = root_path.lstat()
        except OSError as error:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch root cannot be inspected"
            ) from error
        if WindowsJobObjectController._is_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch root is not a real directory"
            )
        total = 0
        pending = [root_path]
        while pending:
            current = pending.pop()
            try:
                entries = tuple(current.iterdir())
            except OSError as error:
                raise JobObjectEnforcementError(
                    f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch directory cannot be read"
                ) from error
            for entry in entries:
                try:
                    entry_stat = entry.lstat()
                except OSError as error:
                    raise JobObjectEnforcementError(
                        f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch entry cannot be inspected"
                    ) from error
                if WindowsJobObjectController._is_reparse(entry_stat):
                    raise JobObjectEnforcementError(
                        f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch reparse entry is not admitted"
                    )
                if stat.S_ISDIR(entry_stat.st_mode):
                    pending.append(entry)
                elif stat.S_ISREG(entry_stat.st_mode):
                    total += int(entry_stat.st_size)
                else:
                    raise JobObjectEnforcementError(
                        f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: scratch entry type is not admitted"
                    )
        return total

    def sample(
        self, process: Any, scratch_root: str | os.PathLike[str] | None = None
    ) -> tuple[int, int]:
        """Return parent/controller observations, never worker self-report.

        Job Object memory uses the kernel's peak job usage.  Scratch usage is
        measured by the parent over the dedicated attempt directory.
        """

        process_key = id(process)
        job = self._jobs.get(process_key)
        if job is None:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: Job Object assignment is missing"
            )
        kernel32 = self._load_kernel32()
        ExtendedLimitInformation, _, _ = self._structures()
        observed = ExtendedLimitInformation()
        returned = ctypes.c_uint32()
        if not kernel32.QueryInformationJobObject(
            job,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(observed),
            ctypes.sizeof(observed),
            ctypes.byref(returned),
        ):
            raise self._last_error("QueryInformationJobObject sample failed")
        return int(observed.PeakJobMemoryUsed), self._directory_size(scratch_root)

    def release(self, process: Any) -> None:
        process_key = id(process)
        job = self._jobs.pop(process_key, None)
        self._queries.pop(process_key, None)
        if job is not None and sys.platform == "win32":
            kernel32 = self._load_kernel32()
            kernel32.CloseHandle(job)


class StaticJobObjectController:
    """Injectable hard-enforcement adapter for deterministic non-product tests."""

    def __init__(
        self,
        *,
        fail_message: str | None = None,
        memory_bytes: int = 0,
        scratch_bytes: int = 0,
    ) -> None:
        self.fail_message = fail_message
        self.memory_bytes = memory_bytes
        self.scratch_bytes = scratch_bytes
        self.assigned: list[tuple[int, Any]] = []

    def assign(self, process: Any, grant: Any) -> None:
        if self.fail_message is not None:
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: {self.fail_message}"
            )
        self.assigned.append((id(process), grant))

    def query(self, process: Any) -> JobObjectQuery:
        for process_key, grant in self.assigned:
            if process_key == id(process):
                return JobObjectQuery(
                    process_id=int(getattr(getattr(process, "process", process), "pid", 0)),
                    memory_limit_bytes=int(grant.memory_hard_limit_bytes),
                    cpu_rate_per_10000=int(grant.job_cpu_rate_per_10000 or 1),
                    kill_on_close=True,
                    hard_cpu_cap=True,
                )
        raise JobObjectEnforcementError(
            f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: static assignment is missing"
        )

    def release(self, process: Any) -> None:
        self.assigned = [item for item in self.assigned if item[0] != id(process)]

    def sample(
        self, process: Any, scratch_root: str | os.PathLike[str] | None = None
    ) -> tuple[int, int]:
        if not any(process_key == id(process) for process_key, _ in self.assigned):
            raise JobObjectEnforcementError(
                f"{RESOURCE_ENFORCEMENT_NOT_AVAILABLE}: static assignment is missing"
            )
        return self.memory_bytes, self.scratch_bytes


__all__ = [
    "JobObjectEnforcementError",
    "JobObjectQuery",
    "StaticJobObjectController",
    "WindowsJobObjectController",
]
