from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from dataclasses import fields, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from .helpers import PROJECT_ID, MutableClock, make_supervisor, run_identity
except ImportError:
    from helpers import PROJECT_ID, MutableClock, make_supervisor, run_identity  # type: ignore[no-redef]

from v3_backend.control_plane.lease_manager import InMemoryLeasePersistence, LeaseManager, LeaseState
from v3_backend.control_plane.persistence import ConcurrentStateChange
from v3_backend.control_plane.resource_governor import (
    FakeResourceSampler,
    HardwareProfile,
    MAX_RESOURCE_EVENTS,
    OperationProfile,
    PressureLevel,
    RuntimeResourcePolicy,
    ResourceGovernor,
    ResourceRejected,
    ResourceSample,
    DEFAULT_RESOURCE_POLICY_PATH,
)
from v3_backend.control_plane.host_resource_probe import (
    HostResourceProbeError,
    HostResourceSnapshot,
    StaticHostResourceProbe,
    SystemHostResourceProbe,
)
from v3_backend.control_plane.windows_job_object import (
    JobObjectEnforcementError,
    WindowsJobObjectController,
)
from v3_backend.control_plane.shutdown_coordinator import ActiveWork, ShutdownCoordinator, ShutdownState
from v3_backend.control_plane.worker_supervisor import (
    MAX_PROPOSALS_PER_ATTEMPT,
    WorkerSupervisor,
)
from v3_backend.domain.tasks.entities import AttemptState, TaskState
from v3_backend.workers.entrypoint import WorkerSandboxPolicy, run_worker
from v3_backend.workers.protocol import (
    CheckpointProposal,
    Progress,
    StagedOutputProposal,
    WorkerAcknowledge,
    WorkerCancel,
    WorkerCheckpointRequest,
    WorkerHeartbeat,
    WorkerHello,
    WorkerPause,
    WorkerProgressAck,
    WorkerResourcePressure,
    WorkerRequest,
    WorkerTerminal,
    decode_command,
    decode_response,
    encode_command,
    encode_response,
    MAX_BOUNDED_JSON_BYTES,
    validate_command,
    validate_response,
)


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.cancelled = False
        self.checkpoint_requested = False
        self.domain_opened = False
        self.ack_sent = False

    def terminate(self) -> None:
        self.terminated = True

    def cancel(self) -> None:
        self.cancelled = True

    def request_checkpoint(self) -> None:
        self.checkpoint_requested = True

    def send_ack(self) -> None:
        self.ack_sent = True
        self.domain_opened = True

    def is_alive(self) -> bool:
        return not self.terminated


class DelayedExitProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.exit_confirmed = False

    def is_alive(self) -> bool:
        return not self.exit_confirmed

    def confirm_exit(self) -> None:
        self.exit_confirmed = True


class FakeFactory:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []

    def spawn(self, request: WorkerRequest) -> FakeProcess:
        process = FakeProcess()
        self.processes.append(process)
        return process


class DelayedExitFactory(FakeFactory):
    def spawn(self, request: WorkerRequest) -> DelayedExitProcess:
        process = DelayedExitProcess()
        self.processes.append(process)
        return process


class FailingFactory:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def spawn(self, request: WorkerRequest) -> FakeProcess:
        raise self.error


class FailingJobController:
    def assign(self, process: FakeProcess, grant: object) -> None:
        raise RuntimeError("RESOURCE_ENFORCEMENT_NOT_AVAILABLE: synthetic Job assignment failure")


class ExpiryRacePersistence(InMemoryLeasePersistence):
    def __init__(self, winner: LeaseState) -> None:
        super().__init__()
        self.winner = winner
        self.injected = False

    def save(self, lease):
        if lease.state == LeaseState.EXPIRED and not self.injected:
            self.injected = True
            if self.winner == LeaseState.RENEWED:
                current = copy.deepcopy(self.items[lease.lease_id])
                current.state = LeaseState.RENEWED
                current.expires_at += timedelta(seconds=30)
                current.last_heartbeat_sequence += 1
                super().save(current)
            else:
                super().save(lease)
            raise ConcurrentStateChange("concurrent lease winner")
        super().save(lease)


def request_for(attempt_id: str, run_id: str) -> WorkerRequest:
    return WorkerRequest(
        attempt_id=attempt_id,
        run_id=run_id,
        operation_id="ModelService.v1.train",
        canonical_input={"bounded": "input"},
        input_hash="a" * 64,
        read_tickets=("read-ticket",),
        staging_namespace="attempt/staging",
        resource_lease_token="opaque-token",
        cancellation_channel="cancel-token",
        checkpoint_policy="SUPPORTED",
    )


class WorkerAndResourceTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "native Job Objects require Windows")
    def test_native_windows_job_object_assigns_queries_samples_and_releases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-native-job-object-") as directory:
            scratch_root = Path(directory)
            (scratch_root / "payload.bin").write_bytes(b"native")
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            controller = WindowsJobObjectController()
            grant = SimpleNamespace(
                memory_hard_limit_bytes=256 * 1024 * 1024,
                job_cpu_rate_per_10000=10_000,
            )
            try:
                controller.assign(process, grant)
                observed = controller.query(process)
                self.assertEqual(observed.process_id, process.pid)
                self.assertEqual(observed.memory_limit_bytes, grant.memory_hard_limit_bytes)
                self.assertEqual(observed.cpu_rate_per_10000, grant.job_cpu_rate_per_10000)
                self.assertTrue(observed.kill_on_close)
                self.assertTrue(observed.hard_cpu_cap)
                memory_bytes, scratch_bytes = controller.sample(process, scratch_root)
                self.assertGreaterEqual(memory_bytes, 0)
                self.assertEqual(scratch_bytes, len(b"native"))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                controller.release(process)
            with self.assertRaisesRegex(
                JobObjectEnforcementError, "Job Object assignment is missing"
            ):
                controller.query(process)

    def test_windows_job_object_normalizes_ctypes_handle_values(self) -> None:
        controller = WindowsJobObjectController()

        self.assertEqual(controller._handle_value(ctypes.c_void_p(123)), 123)
        for invalid in (ctypes.c_void_p(0), None, False, -1):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    JobObjectEnforcementError, "Job Object handle is invalid"
                ):
                    controller._handle_value(invalid)

    def test_system_probe_rejects_reparse_scratch_root_before_disk_usage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-resource-probe-") as directory:
            probe = SystemHostResourceProbe(directory)
            probe.scratch_root = SimpleNamespace(
                lstat=lambda: SimpleNamespace(
                    st_mode=stat.S_IFLNK,
                    st_file_attributes=0,
                )
            )
            with self.assertRaisesRegex(
                HostResourceProbeError, "scratch root is not a real directory"
            ):
                probe.sample()

    def make_worker_system(self, sampler: FakeResourceSampler | None = None):
        clock = MutableClock()
        tasks, persistence, publisher, identities, _ = make_supervisor(clock)
        leases_port = InMemoryLeasePersistence()
        leases = LeaseManager(leases_port, clock)
        governor = ResourceGovernor(sampler or FakeResourceSampler())
        factory = FakeFactory()
        workers = WorkerSupervisor(governor, leases, tasks, identities, factory)
        return clock, tasks, persistence, leases_port, governor, factory, workers

    def test_spawn_error_classification_never_promotes_unknown_failure_to_retryable(self) -> None:
        for error, expected in (
            (OSError("temporary process creation failure"), "TRANSIENT_IO"),
            (RuntimeError("unknown process factory defect"), "INTERNAL_ERROR"),
        ):
            with self.subTest(error=type(error).__name__):
                clock = MutableClock()
                tasks, persistence, _, identities, _ = make_supervisor(clock)
                leases = LeaseManager(InMemoryLeasePersistence(), clock)
                governor = ResourceGovernor(FakeResourceSampler())
                workers = WorkerSupervisor(
                    governor,
                    leases,
                    tasks,
                    identities,
                    FailingFactory(error),
                )
                _, run, attempt = tasks.accept(
                    PROJECT_ID,
                    "ModelService.v1.train",
                    run_identity(),
                )
                with self.assertRaises(type(error)):
                    workers.dispatch(
                        request_for(attempt.attempt_id, run.run_id),
                        OperationProfile("ModelService.v1.train", "CPU"),
                    )
                failed = persistence.attempts[attempt.attempt_id]
                self.assertEqual(failed.state, AttemptState.FAILED)
                self.assertEqual(failed.terminal_error_category, expected)

    def test_job_assignment_failure_is_terminal_before_ack_or_domain_open(self) -> None:
        clock = MutableClock()
        tasks, persistence, _, identities, _ = make_supervisor(clock)
        leases = LeaseManager(InMemoryLeasePersistence(), clock)
        governor = ResourceGovernor(FakeResourceSampler())
        factory = FakeFactory()
        workers = WorkerSupervisor(
            governor,
            leases,
            tasks,
            identities,
            factory,
            job_controller=FailingJobController(),
        )
        task, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("ModelService.v1.train", "CPU"),
        )

        with self.assertRaisesRegex(RuntimeError, "RESOURCE_ENFORCEMENT_NOT_AVAILABLE"):
            workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")

        process = factory.processes[0]
        self.assertFalse(process.ack_sent)
        self.assertFalse(process.domain_opened)
        self.assertTrue(process.terminated)
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.FAILED)
        self.assertEqual(
            persistence.attempts[attempt.attempt_id].terminal_error_category,
            "RESOURCE_ENFORCEMENT_NOT_AVAILABLE",
        )
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.FAILED)

    def test_product_terminal_failure_waits_for_confirmed_child_exit(self) -> None:
        clock = MutableClock()
        tasks, persistence, _, identities, _ = make_supervisor(clock)
        leases = LeaseManager(InMemoryLeasePersistence(), clock)
        governor = ResourceGovernor(FakeResourceSampler())
        factory = DelayedExitFactory()
        workers = WorkerSupervisor(
            governor,
            leases,
            tasks,
            identities,
            factory,
            job_controller=FailingJobController(),
            product_terminal_owner=True,
        )
        task, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("ModelService.v1.train", "CPU"),
        )

        with self.assertRaisesRegex(RuntimeError, "RESOURCE_ENFORCEMENT_NOT_AVAILABLE"):
            workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")

        process = factory.processes[0]
        self.assertTrue(process.terminated)
        self.assertTrue(process.is_alive())
        self.assertNotEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.FAILED)
        self.assertNotEqual(persistence.tasks[task.task_id].state, TaskState.FAILED)
        self.assertIn(lease.lease_id, workers.workers)
        self.assertIn(lease.lease_id, governor.active)

        process.confirm_exit()
        workers.observe_externally_finalized(lease.lease_id)

        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.FAILED)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.FAILED)
        self.assertNotIn(lease.lease_id, workers.workers)
        self.assertNotIn(lease.lease_id, governor.active)

    def test_pre_start_abort_fences_admitted_worker_and_closes_aggregate(self) -> None:
        _, tasks, persistence, leases_port, governor, factory, workers = self.make_worker_system()
        task, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("ModelService.v1.train", "CPU"),
        )

        workers.abort_before_start(lease.lease_id, "worker handle transfer failed")

        self.assertTrue(factory.processes[0].terminated)
        self.assertNotIn(lease.lease_id, workers.workers)
        self.assertNotIn(lease.lease_id, governor.active)
        self.assertEqual(leases_port.items[lease.lease_id].state, LeaseState.REVOKED)
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.FAILED)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.FAILED)

    def test_ack_aggregate_failure_fences_child_and_releases_resource_accounting(self) -> None:
        _, tasks, persistence, leases_port, governor, factory, workers = self.make_worker_system()
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("ModelService.v1.train", "CPU"),
        )

        with patch.object(
            tasks,
            "mark_task_started_for_attempt",
            side_effect=RuntimeError("aggregate write lost") ,
        ):
            with self.assertRaisesRegex(RuntimeError, "aggregate write lost"):
                workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")

        self.assertTrue(factory.processes[0].terminated)
        self.assertNotIn(lease.lease_id, workers.workers)
        self.assertNotIn(lease.lease_id, governor.active)
        self.assertEqual(leases_port.items[lease.lease_id].state, LeaseState.REVOKED)
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.FAILED)
        self.assertEqual(persistence.tasks[attempt.task_id].state, TaskState.FAILED)

    def test_ack_after_execution_deadline_fails_before_domain_start(self) -> None:
        _, tasks, persistence, leases_port, governor, factory, workers = self.make_worker_system()
        task, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        request = replace(
            request_for(attempt.attempt_id, run.run_id),
            deadline_at="2000-01-01T00:00:00Z",
        )
        lease = workers.dispatch(request, OperationProfile("ModelService.v1.train", "CPU"))

        with self.assertRaisesRegex(RuntimeError, "after execution deadline"):
            workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")

        self.assertTrue(factory.processes[0].terminated)
        self.assertNotIn(lease.lease_id, workers.workers)
        self.assertNotIn(lease.lease_id, governor.active)
        self.assertEqual(leases_port.items[lease.lease_id].state, LeaseState.REVOKED)
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.FAILED)
        self.assertEqual(
            persistence.attempts[attempt.attempt_id].terminal_error_category,
            "DEADLINE_EXCEEDED_PRE_COMMIT",
        )
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.FAILED)

    def test_ack_cancel_race_cancels_attempt_without_reopening_task(self) -> None:
        _, tasks, persistence, leases_port, governor, factory, workers = self.make_worker_system()
        task, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("ModelService.v1.train", "CPU"),
        )
        tasks.request_cancel(task.task_id, lambda _: None)

        with self.assertRaises(ValueError):
            workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")

        self.assertTrue(factory.processes[0].terminated)
        self.assertNotIn(lease.lease_id, workers.workers)
        self.assertNotIn(lease.lease_id, governor.active)
        self.assertEqual(leases_port.items[lease.lease_id].state, LeaseState.REVOKED)
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.CANCELLED)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.CANCEL_REQUESTED)

    def test_expiry_cas_race_does_not_fence_renewed_lease(self) -> None:
        clock = MutableClock()
        persistence = ExpiryRacePersistence(LeaseState.RENEWED)
        leases = LeaseManager(persistence, clock)
        governor = ResourceGovernor(FakeResourceSampler())
        lease_id = "lea_" + "7" * 26
        attempt_id = "att_" + "7" * 26
        grant = governor.admit(lease_id, OperationProfile("op", "CPU", heartbeat_interval_seconds=5))
        lease = leases.grant(lease_id, attempt_id, grant, lease_token="opaque-token")
        clock.now = lease.expires_at

        self.assertEqual(leases.expire_due(), ())
        self.assertEqual(persistence.items[lease_id].state, LeaseState.RENEWED)

    def test_expiry_cas_race_keeps_durable_expiry_observable(self) -> None:
        clock = MutableClock()
        persistence = ExpiryRacePersistence(LeaseState.EXPIRED)
        leases = LeaseManager(persistence, clock)
        governor = ResourceGovernor(FakeResourceSampler())
        lease_id = "lea_" + "8" * 26
        attempt_id = "att_" + "8" * 26
        grant = governor.admit(lease_id, OperationProfile("op", "CPU", heartbeat_interval_seconds=5))
        lease = leases.grant(lease_id, attempt_id, grant, lease_token="opaque-token")
        clock.now = lease.expires_at

        expired = leases.expire_due()
        self.assertEqual(tuple(item.lease_id for item in expired), (lease_id,))
        self.assertEqual(persistence.items[lease_id].state, LeaseState.EXPIRED)

    def test_conservative_default_admits_only_one_worker(self) -> None:
        _, tasks, _, _, _, _, workers = self.make_worker_system()
        _, run1, attempt1 = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        _, run2, attempt2 = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        profile = OperationProfile("ModelService.v1.train", "CPU")
        workers.dispatch(request_for(attempt1.attempt_id, run1.run_id), profile)
        with self.assertRaises(ResourceRejected):
            workers.dispatch(request_for(attempt2.attempt_id, run2.run_id), profile)

    def test_real_host_capacity_does_not_drop_the_last_available_worker(self) -> None:
        gib = 1 << 30
        probe = StaticHostResourceProbe(
            HostResourceSnapshot(
                logical_cpu_count=5,
                total_physical_memory_bytes=16 * gib,
                available_physical_memory_bytes=8 * gib,
                scratch_free_bytes=15 * gib,
                sampled_at="2026-08-27T00:00:00Z",
            )
        )
        governor = ResourceGovernor(host_probe=probe, scratch_root=".")
        profile = OperationProfile("op", "CPU", preset="CONSERVATIVE")

        grants = [governor.admit(f"lease-{index}", profile) for index in range(4)]

        self.assertEqual(len(grants), 4)
        self.assertEqual(len(governor.active), 4)
        with self.assertRaises(ResourceRejected):
            governor.admit("lease-4", profile)

    def test_real_host_pressure_cap_is_not_overridden_by_capacity_recalculation(self) -> None:
        gib = 1 << 30
        probe = StaticHostResourceProbe(
            HostResourceSnapshot(
                logical_cpu_count=5,
                total_physical_memory_bytes=16 * gib,
                available_physical_memory_bytes=3 * gib,
                scratch_free_bytes=15 * gib,
                sampled_at="2026-08-27T00:00:00Z",
            )
        )
        governor = ResourceGovernor(host_probe=probe, scratch_root=".")
        profile = OperationProfile("op", "CPU", preset="CONSERVATIVE")

        governor.admit("lease-0", profile)

        self.assertEqual(governor.concurrency_limit, 1)
        with self.assertRaises(ResourceRejected):
            governor.admit("lease-1", profile)

    def test_pressure_ladder_reduces_concurrency_then_pauses_admission(self) -> None:
        sampler = FakeResourceSampler(ResourceSample(PressureLevel.PRESSURED, reason="memory pressure"))
        governor = ResourceGovernor(
            sampler,
            HardwareProfile("admitted", True, 8, 8 << 30, max_concurrency=4),
        )
        governor.observe_pressure("CPU")
        self.assertEqual(governor.concurrency_limit, 3)
        self.assertEqual(
            [event["action"] for event in governor.resource_events[:2]],
            ["REDUCE_FUTURE_CONCURRENCY", "REQUEST_SPILL_OR_CHECKPOINT"],
        )
        sampler.current = ResourceSample(PressureLevel.CRITICAL, reason="critical")
        governor.observe_pressure("CPU")
        self.assertIn("CPU", governor.paused_classes)
        with self.assertRaises(ResourceRejected):
            governor.admit("lea_" + "9" * 26, OperationProfile("op", "CPU"))

    def test_heartbeat_expiry_marks_attempt_lost_and_terminates_only_worker(self) -> None:
        clock, tasks, persistence, leases_port, _, factory, workers = self.make_worker_system()
        task, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("ModelService.v1.train", "CPU", heartbeat_interval_seconds=5),
        )
        workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")
        clock.now += timedelta(seconds=16)
        self.assertEqual(workers.reap_expired(), (attempt.attempt_id,))
        self.assertTrue(factory.processes[0].terminated)
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.LOST)
        self.assertNotEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.RUNNING)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.RUNNING)
        self.assertEqual(leases_port.items[lease.lease_id].state, LeaseState.EXPIRED)

    def test_heartbeat_is_monotonic_and_persisted_before_renewal_is_observed(self) -> None:
        clock, tasks, _, leases_port, _, _, workers = self.make_worker_system()
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("op", "CPU", heartbeat_interval_seconds=5),
        )
        workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")
        original_expiry = lease.expires_at
        clock.now += timedelta(seconds=4)
        workers.heartbeat(lease.lease_id, 1, 1024, 1024)
        renewed = leases_port.items[lease.lease_id]
        self.assertEqual(renewed.state, LeaseState.RENEWED)
        self.assertGreater(renewed.expires_at, original_expiry)
        self.assertEqual(renewed.last_heartbeat_sequence, 1)
        with self.assertRaises(ValueError):
            workers.heartbeat(lease.lease_id, 1, 1024, 1024)

    def test_simulated_worker_oom_isolated_from_supervisor_and_backend(self) -> None:
        _, tasks, persistence, _, governor, factory, workers = self.make_worker_system()
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(request_for(attempt.attempt_id, run.run_id), OperationProfile("op", "CPU"))
        workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")
        workers.handle(lease.lease_id, WorkerTerminal("FAILED", "WORKER_OOM", "bounded"))
        self.assertTrue(factory.processes[0].terminated)
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.FAILED)
        self.assertEqual(persistence.attempts[attempt.attempt_id].terminal_error_category, "WORKER_OOM")
        self.assertNotIn(lease.lease_id, governor.active)
        # Main process remains usable and can durably accept subsequent work.
        next_task, _, _ = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        self.assertIn(next_task.task_id, persistence.tasks)

    def test_staged_output_never_directly_publishes_or_completes_task(self) -> None:
        _, tasks, persistence, _, _, _, workers = self.make_worker_system()
        task, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(request_for(attempt.attempt_id, run.run_id), OperationProfile("op", "CPU"))
        workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")
        proposal = StagedOutputProposal(
            "model.safe", "MODEL_BYTES", "application/octet-stream", 12, "b" * 64
        )
        workers.handle(lease.lease_id, proposal)
        self.assertEqual(workers.staged_outputs[attempt.attempt_id], [proposal])
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.RUNNING)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.RUNNING)
        workers.handle(lease.lease_id, WorkerTerminal("SUCCEEDED"))
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.SUCCEEDED)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.RUNNING)
        self.assertNotIn(attempt.attempt_id, workers.staged_outputs)
        self.assertNotIn(attempt.attempt_id, workers.checkpoint_proposals)

    def test_proposal_count_is_bounded_and_overflow_fails_closed(self) -> None:
        _, tasks, persistence, _, _, factory, workers = self.make_worker_system()
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id), OperationProfile("op", "CPU")
        )
        workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")
        proposal = StagedOutputProposal(
            "model.safe", "MODEL_BYTES", "application/octet-stream", 12, "b" * 64
        )

        for _ in range(MAX_PROPOSALS_PER_ATTEMPT):
            workers.handle(lease.lease_id, proposal)
        self.assertEqual(
            len(workers.staged_outputs[attempt.attempt_id]), MAX_PROPOSALS_PER_ATTEMPT
        )

        workers.handle(lease.lease_id, proposal)

        self.assertTrue(factory.processes[0].terminated)
        self.assertEqual(
            persistence.attempts[attempt.attempt_id].terminal_error_category,
            "STAGED_OUTPUT_PROPOSALS_EXCEEDED",
        )
        self.assertNotIn(attempt.attempt_id, workers.staged_outputs)
        self.assertNotIn(attempt.attempt_id, workers.checkpoint_proposals)

    def test_checkpoint_proposal_count_is_bounded_and_cleared_on_lost_worker(self) -> None:
        _, tasks, persistence, _, _, factory, workers = self.make_worker_system()
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(
                attempt.attempt_id,
                run.run_id,
            ),
            OperationProfile("op", "CPU", heartbeat_interval_seconds=5),
        )
        workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")
        proposal = CheckpointProposal(
            "checkpoint.bin", "a" * 64, "b" * 64, {"format": "v1"}
        )

        for _ in range(MAX_PROPOSALS_PER_ATTEMPT):
            workers.handle(lease.lease_id, proposal)
        self.assertEqual(
            len(workers.checkpoint_proposals[attempt.attempt_id]),
            MAX_PROPOSALS_PER_ATTEMPT,
        )

        workers.handle(lease.lease_id, proposal)

        self.assertTrue(factory.processes[0].terminated)
        self.assertEqual(
            persistence.attempts[attempt.attempt_id].terminal_error_category,
            "CHECKPOINT_PROPOSALS_EXCEEDED",
        )
        self.assertNotIn(attempt.attempt_id, workers.staged_outputs)
        self.assertNotIn(attempt.attempt_id, workers.checkpoint_proposals)

    def test_resource_event_log_keeps_only_the_newest_bounded_window(self) -> None:
        governor = ResourceGovernor(FakeResourceSampler())

        for sequence in range(MAX_RESOURCE_EVENTS + 7):
            governor.record_event({"action": "TEST", "sequence": sequence})

        self.assertEqual(len(governor.resource_events), MAX_RESOURCE_EVENTS)
        self.assertEqual(governor.resource_events[0]["sequence"], 7)
        self.assertEqual(
            governor.resource_events[-1]["sequence"], MAX_RESOURCE_EVENTS + 6
        )

    def test_invalid_worker_message_is_isolated_as_schema_failure(self) -> None:
        _, tasks, persistence, _, _, factory, workers = self.make_worker_system()
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(request_for(attempt.attempt_id, run.run_id), OperationProfile("op", "CPU"))
        workers.acknowledge(lease.lease_id, "1.0.0", "opaque-token")
        workers.handle(lease.lease_id, {"artifact_id": "worker-forged"})
        self.assertTrue(factory.processes[0].terminated)
        failed = persistence.attempts[attempt.attempt_id]
        self.assertEqual(failed.state, AttemptState.FAILED)
        self.assertEqual(failed.terminal_error_category, "SCHEMA_MISMATCH")

    def test_startup_reconciliation_marks_unmatched_lease_lost(self) -> None:
        _, tasks, persistence, _, _, _, workers = self.make_worker_system()
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        workers.dispatch(request_for(attempt.attempt_id, run.run_id), OperationProfile("op", "CPU"))
        workers.workers.clear()  # models a fresh backend with no re-handshaken child
        self.assertEqual(workers.reconcile_startup(), (attempt.attempt_id,))
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.LOST)

    def test_product_owner_reconciles_lost_lease_without_in_memory_worker(self) -> None:
        clock = MutableClock()
        tasks, persistence, _, identities, _ = make_supervisor(clock)
        leases_port = InMemoryLeasePersistence()
        leases = LeaseManager(leases_port, clock)
        governor = ResourceGovernor(FakeResourceSampler())
        factory = FakeFactory()
        workers = WorkerSupervisor(
            governor,
            leases,
            tasks,
            identities,
            factory,
            product_terminal_owner=True,
        )
        _, run, attempt = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        lease = workers.dispatch(
            request_for(attempt.attempt_id, run.run_id),
            OperationProfile("op", "CPU"),
        )

        # A product-owner generation can restart after losing its in-memory
        # worker map. With no OS process handle remaining, reconciliation must
        # close the durable lease instead of leaving a pending tombstone.
        workers.workers.clear()

        self.assertEqual(workers.reconcile_startup(), (attempt.attempt_id,))
        self.assertEqual(persistence.attempts[attempt.attempt_id].state, AttemptState.LOST)
        self.assertEqual(leases_port.items[lease.lease_id].state, LeaseState.REVOKED)
        self.assertNotIn(lease.lease_id, governor.active)
        self.assertNotIn(lease.lease_id, workers._pending_terminations)

    def test_worker_returns_only_staged_proposals_and_cannot_publish_identity_or_truth(self) -> None:
        request_fields = {field.name for field in fields(WorkerRequest)}
        proposal_fields = {field.name for field in fields(StagedOutputProposal)}
        forbidden = {"task_id", "project_id", "artifact_id", "truth_state", "registry", "catalog", "publish"}
        self.assertTrue(forbidden.isdisjoint(request_fields))
        self.assertTrue(forbidden.isdisjoint(proposal_fields))
        proposal = StagedOutputProposal("output.bin", "MODEL_BYTES", "application/octet-stream", 12, "b" * 64)
        self.assertFalse(hasattr(proposal, "artifact_id"))
        with self.assertRaises(ValueError):
            WorkerRequest(
                **{
                    **request_for("att_" + "2" * 26, "run_" + "2" * 26).__dict__,
                    "canonical_input": {"nested": {"artifact_id": "worker-owned"}},
                }
            )

    def test_worker_entrypoint_converts_memory_error_to_terminal_data(self) -> None:
        request = request_for("att_" + "1" * 26, "run_" + "1" * 26)

        def oom_handler(_: WorkerRequest):
            raise MemoryError
            yield  # pragma: no cover

        result = run_worker(oom_handler, request)
        self.assertEqual(result, (WorkerTerminal("FAILED", "WORKER_OOM", "worker memory limit exceeded"),))

    def test_protocol_rejects_noncanonical_deadlines_and_non_integer_telemetry(self) -> None:
        request = request_for("att_" + "3" * 26, "run_" + "3" * 26)
        with self.assertRaises(ValueError):
            WorkerRequest(**{**request.__dict__, "input_hash": None})
        with self.assertRaises(ValueError):
            WorkerRequest(**{**request.__dict__, "canonical_input": {"nested": {1: "invalid"}}})
        with self.assertRaises(ValueError):
            WorkerRequest(**{**request.__dict__, "canonical_input": {"nested": ("tuple",)}})
        with self.assertRaises(ValueError):
            WorkerRequest(**{**request.__dict__, "deadline_at": "2026-08-27T00:00:00+00:00"})
        with self.assertRaises(ValueError):
            validate_command(WorkerCheckpointRequest("stall", None))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            validate_response(WorkerHeartbeat(True, 0, 0))
        with self.assertRaises(ValueError):
            validate_response(Progress(1, 1, {"rows": 1.0}))
        with self.assertRaises(ValueError):
            validate_response(WorkerTerminal([], None, None))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            validate_response(WorkerTerminal("SUCCEEDED", "SHOULD_NOT_BE_PRESENT", None))
        with self.assertRaises(ValueError):
            validate_response(WorkerTerminal("CANCELLED", None, "SHOULD_NOT_BE_PRESENT"))
        governor = ResourceGovernor(FakeResourceSampler())
        grant = governor.admit("lea_" + "4" * 26, OperationProfile("op", "CPU"))
        with self.assertRaises(ValueError):
            replace(
                grant,
                resolved_resource_json='{"a": 1}',
                resolved_resource_hash=hashlib.sha256(b'{"a": 1}').hexdigest(),
            )

    def test_worker_transport_is_strict_bounded_json_and_preserves_v1_empty_progress(self) -> None:
        commands = (
            WorkerAcknowledge("1.0.0", "opaque-token"),
            WorkerCancel("user requested"),
            WorkerCheckpointRequest("before shutdown", "2030-01-01T00:00:00.123456789Z"),
            WorkerPause("host pressure"),
            WorkerProgressAck(3),
            WorkerResourcePressure("MEMORY", 8, 16, 32),
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decode_command(encode_command(command)), command)

        responses = (
            WorkerHello("1.0.0", "opaque-token"),
            WorkerHeartbeat(1, 10, 20),
            Progress(0, 0, {}, "EMPTY", "items"),
            CheckpointProposal("checkpoint.bin", "a" * 64, "b" * 64, {"format": "v1"}),
            StagedOutputProposal("output.bin", "MODEL_BYTES", "application/octet-stream", 4, "c" * 64),
            WorkerTerminal("FAILED", "WORKER_ERROR", "safe"),
        )
        for response in responses:
            with self.subTest(response=response):
                self.assertEqual(decode_response(encode_response(response)), response)

        with self.assertRaises(ValueError):
            decode_response(
                b'{"kind":"WorkerHello","protocol_version":"1.0.0",'
                b'"protocol_version":"1.0.0","resource_lease_token":"opaque-token"}'
            )
        with self.assertRaises(ValueError):
            decode_response(
                b'{"kind":"WorkerHello","protocol_version":"1.0.0",'
                b'"resource_lease_token":"opaque-token","__class__":"pickle.loads"}'
            )
        with self.assertRaises(ValueError):
            decode_response(b'{"kind":"WorkerHeartbeat","sequence":NaN,"rss_bytes":0,"scratch_bytes":0}')
        with self.assertRaises(ValueError):
            decode_response(b"{" + b'"kind":"WorkerHeartbeat",' + b'"sequence":1,' + b'"rss_bytes":0,' + b'"scratch_bytes":"' + b"x" * MAX_BOUNDED_JSON_BYTES + b'"}')

    def test_runtime_resource_policy_rejects_nonfinite_and_schema_drift(self) -> None:
        raw = json.loads(DEFAULT_RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))
        for value in ("NaN", "Infinity", "0", "1.1"):
            altered = copy.deepcopy(raw)
            altered["soft_pressure_ratio"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                RuntimeResourcePolicy.from_mapping(altered)
        altered = copy.deepcopy(raw)
        altered["unexpected"] = True
        with self.assertRaises(ValueError):
            RuntimeResourcePolicy.from_mapping(altered)
        altered = copy.deepcopy(raw)
        altered["presets"] = {1: altered["presets"]["CONSERVATIVE"], **altered["presets"]}
        with self.assertRaises(ValueError):
            RuntimeResourcePolicy.from_mapping(altered)

    def test_worker_sandbox_strips_credentials_and_network_is_deny_by_default(self) -> None:
        policy = WorkerSandboxPolicy()
        sanitized = policy.sanitize_environment(
            {"PATH": "fixed", "TEMP": "scratch", "AWS_SECRET_ACCESS_KEY": "secret"}
        )
        self.assertEqual(sanitized, {"PATH": "fixed", "TEMP": "scratch"})
        self.assertEqual(policy.allowed_network_endpoints, ())

    def test_shutdown_checkpoint_cancel_and_flush_order(self) -> None:
        class Hooks:
            def __init__(self) -> None:
                self.trace: list[str] = []

            def active_work(self):
                return (ActiveWork("att_resumable", True), ActiveWork("att_plain", False))

            def request_checkpoint(self, attempt_id): self.trace.append("checkpoint:" + attempt_id)
            def request_cancel(self, attempt_id): self.trace.append("cancel:" + attempt_id)
            def await_grace(self, seconds): self.trace.append("grace")
            def terminate_remaining(self): self.trace.append("terminate")
            def expire_leases(self): self.trace.append("expire")
            def flush_events(self): self.trace.append("flush")
            def close_catalog(self): self.trace.append("close")

        hooks = Hooks()
        coordinator = ShutdownCoordinator(hooks)
        coordinator.shutdown(3)
        self.assertEqual(coordinator.state, ShutdownState.STOPPED)
        self.assertEqual(
            hooks.trace,
            ["checkpoint:att_resumable", "cancel:att_plain", "grace", "terminate", "expire", "flush", "close"],
        )
        self.assertFalse(coordinator.accepts_new_commands())


if __name__ == "__main__":
    unittest.main()
