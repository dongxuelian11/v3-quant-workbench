from __future__ import annotations

import unittest
from dataclasses import fields
from datetime import timedelta

try:
    from .helpers import PROJECT_ID, MutableClock, make_supervisor, run_identity
except ImportError:
    from helpers import PROJECT_ID, MutableClock, make_supervisor, run_identity  # type: ignore[no-redef]

from v3_backend.control_plane.lease_manager import InMemoryLeasePersistence, LeaseManager, LeaseState
from v3_backend.control_plane.resource_governor import (
    FakeResourceSampler,
    HardwareProfile,
    OperationProfile,
    PressureLevel,
    ResourceGovernor,
    ResourceRejected,
    ResourceSample,
)
from v3_backend.control_plane.shutdown_coordinator import ActiveWork, ShutdownCoordinator, ShutdownState
from v3_backend.control_plane.worker_supervisor import WorkerSupervisor
from v3_backend.domain.tasks.entities import AttemptState, TaskState
from v3_backend.workers.entrypoint import WorkerSandboxPolicy, run_worker
from v3_backend.workers.protocol import (
    StagedOutputProposal,
    WorkerRequest,
    WorkerTerminal,
)


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.cancelled = False
        self.checkpoint_requested = False

    def terminate(self) -> None:
        self.terminated = True

    def cancel(self) -> None:
        self.cancelled = True

    def request_checkpoint(self) -> None:
        self.checkpoint_requested = True

    def is_alive(self) -> bool:
        return not self.terminated


class FakeFactory:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []

    def spawn(self, request: WorkerRequest) -> FakeProcess:
        process = FakeProcess()
        self.processes.append(process)
        return process


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
    def make_worker_system(self, sampler: FakeResourceSampler | None = None):
        clock = MutableClock()
        tasks, persistence, publisher, identities, _ = make_supervisor(clock)
        leases_port = InMemoryLeasePersistence()
        leases = LeaseManager(leases_port, clock)
        governor = ResourceGovernor(sampler or FakeResourceSampler())
        factory = FakeFactory()
        workers = WorkerSupervisor(governor, leases, tasks, identities, factory)
        return clock, tasks, persistence, leases_port, governor, factory, workers

    def test_conservative_default_admits_only_one_worker(self) -> None:
        _, tasks, _, _, _, _, workers = self.make_worker_system()
        _, run1, attempt1 = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        _, run2, attempt2 = tasks.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        profile = OperationProfile("ModelService.v1.train", "CPU")
        workers.dispatch(request_for(attempt1.attempt_id, run1.run_id), profile)
        with self.assertRaises(ResourceRejected):
            workers.dispatch(request_for(attempt2.attempt_id, run2.run_id), profile)

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
