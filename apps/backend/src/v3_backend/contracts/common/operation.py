
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Type

from .dto import ClosedDto


class OperationKind(str, Enum):
    COMMAND = "COMMAND"
    ASYNC_COMMAND = "ASYNC_COMMAND"
    QUERY = "QUERY"


@dataclass(frozen=True)
class OperationContract:
    operation_id: str
    service: str
    version: str
    kind: OperationKind
    request_type: Type[ClosedDto]
    response_type: Type[ClosedDto]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.operation_id.startswith(f"{self.service}.v1."):
            raise ValueError(f"operation ID is outside service namespace: {self.operation_id}")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def validate_request(self, value: Mapping[str, Any]) -> ClosedDto:
        return self.request_type.from_mapping(value)

    def validate_response(self, value: Mapping[str, Any]) -> ClosedDto:
        return self.response_type.from_mapping(value)


@dataclass(frozen=True)
class ServiceContract:
    contract_id: str
    service: str
    api_version: str
    operations: tuple[OperationContract, ...]

    def __post_init__(self) -> None:
        operation_ids = [item.operation_id for item in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError(f"duplicate operation ID in {self.service}")
        if any(item.service != self.service for item in self.operations):
            raise ValueError(f"operation assigned to wrong service: {self.service}")

    @property
    def by_operation_id(self) -> Mapping[str, OperationContract]:
        return MappingProxyType({item.operation_id: item for item in self.operations})
