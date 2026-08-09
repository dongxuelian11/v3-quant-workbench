from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from types import TracebackType


class TransactionMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    WRITE_CONTROL = "WRITE_CONTROL"
    PUBLISH = "PUBLISH"


class UnitOfWork(ABC):
    mode: TransactionMode

    @property
    @abstractmethod
    def active(self) -> bool: ...

    @abstractmethod
    def begin(self, mode: TransactionMode | None = None) -> "UnitOfWork": ...

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    @abstractmethod
    def __enter__(self) -> "UnitOfWork": ...

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool: ...
