"""Canonical local runtime transport.

This package owns process transport and supervision semantics only. Business
operations are supplied as explicit, frozen operation bindings by the ASL
composition layer.
"""

from .composition_root import RuntimePorts, RuntimeSession, build_runtime
from .framed_stdio import MAX_FRAME_BYTES, FrameDecoder, ProtocolViolation, encode_frame
from .request_router import RequestRouter

__all__ = [
    "MAX_FRAME_BYTES",
    "FrameDecoder",
    "ProtocolViolation",
    "RequestRouter",
    "RuntimePorts",
    "RuntimeSession",
    "build_runtime",
    "encode_frame",
]
