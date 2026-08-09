from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from .protocol import WorkerRequest, WorkerResponse, WorkerTerminal, validate_response


@dataclass(frozen=True)
class WorkerSandboxPolicy:
    allowed_environment_keys: frozenset[str] = frozenset({"PATH", "PYTHONUTF8", "TMP", "TEMP"})
    allowed_network_endpoints: tuple[str, ...] = ()

    def sanitize_environment(self, inherited: Mapping[str, str]) -> dict[str, str]:
        return {
            key: inherited[key]
            for key in sorted(self.allowed_environment_keys)
            if key in inherited
        }


def run_worker(
    handler: Callable[[WorkerRequest], Iterable[WorkerResponse]], request: WorkerRequest
) -> tuple[WorkerResponse, ...]:
    """Isolation boundary: failures become data and never escape into the backend."""

    responses: list[WorkerResponse] = []
    try:
        for response in handler(request):
            responses.append(validate_response(response))
    except MemoryError:
        responses.append(WorkerTerminal("FAILED", "WORKER_OOM", "worker memory limit exceeded"))
    except Exception:
        responses.append(WorkerTerminal("FAILED", "WORKER_INTERNAL", "worker failed"))
    terminal_positions = [
        index for index, response in enumerate(responses) if isinstance(response, WorkerTerminal)
    ]
    if not terminal_positions:
        responses.append(WorkerTerminal("FAILED", "WORKER_PROTOCOL", "worker omitted terminal response"))
    elif terminal_positions != [len(responses) - 1]:
        return (WorkerTerminal("FAILED", "WORKER_PROTOCOL", "invalid terminal response order"),)
    return tuple(responses)
