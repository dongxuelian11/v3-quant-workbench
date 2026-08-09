from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .model import ProviderCapability, ProviderDescriptor, RawCaptureEnvelope


@dataclass(frozen=True)
class RawCaptureSubmission:
    envelope: RawCaptureEnvelope
    source_metadata: Mapping[str, Any]


class ProviderAdapterPort(Protocol):
    """A provider adapter may describe capabilities and return raw captures only."""

    def descriptor(self) -> ProviderDescriptor: ...
    def capabilities(self) -> tuple[ProviderCapability, ...]: ...
    def capture(self, request: Mapping[str, Any]) -> RawCaptureSubmission: ...


class RawCaptureSink(Protocol):
    def submit_raw_capture(self, submission: RawCaptureSubmission) -> str: ...


def ingest_from_provider(
    adapter: ProviderAdapterPort,
    sink: RawCaptureSink,
    request: Mapping[str, Any],
) -> str:
    submission = adapter.capture(request)
    if not isinstance(submission, RawCaptureSubmission):
        raise TypeError("provider connector must submit RawCaptureSubmission")
    return sink.submit_raw_capture(submission)
