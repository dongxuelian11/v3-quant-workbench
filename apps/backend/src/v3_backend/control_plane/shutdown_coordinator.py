from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ShutdownState(StrEnum):
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class ActiveWork:
    attempt_id: str
    resumable: bool


class ShutdownHooks(Protocol):
    def active_work(self) -> tuple[ActiveWork, ...]: ...
    def request_checkpoint(self, attempt_id: str) -> None: ...
    def request_cancel(self, attempt_id: str) -> None: ...
    def await_grace(self, seconds: int) -> None: ...
    def terminate_remaining(self) -> None: ...
    def expire_leases(self) -> None: ...
    def flush_events(self) -> None: ...
    def close_catalog(self) -> None: ...


class ShutdownCoordinator:
    def __init__(self, hooks: ShutdownHooks) -> None:
        self.hooks = hooks
        self.state = ShutdownState.RUNNING

    def accepts_new_commands(self) -> bool:
        return self.state is ShutdownState.RUNNING

    def shutdown(self, grace_seconds: int = 10) -> None:
        if self.state is not ShutdownState.RUNNING:
            return
        self.state = ShutdownState.DRAINING
        for work in self.hooks.active_work():
            if work.resumable:
                self.hooks.request_checkpoint(work.attempt_id)
            else:
                self.hooks.request_cancel(work.attempt_id)
        self.hooks.await_grace(grace_seconds)
        self.hooks.terminate_remaining()
        self.hooks.expire_leases()
        self.hooks.flush_events()
        self.hooks.close_catalog()
        self.state = ShutdownState.STOPPED
