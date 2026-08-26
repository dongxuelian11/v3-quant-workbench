from __future__ import annotations

import sqlite3
import sys
from typing import Protocol

from v3_backend.repositories.unit_of_work import TransactionMode, UnitOfWork


class PublishCallbacks(Protocol):
    def verify_staged(self) -> None: ...
    def publish_staged(self) -> None: ...
    def compensate_unreferenced_staging(self) -> None: ...
    def notify_committed(self) -> None: ...


class SQLiteUnitOfWork(UnitOfWork):
    def __init__(
        self,
        connection: sqlite3.Connection,
        mode: TransactionMode = TransactionMode.WRITE_CONTROL,
        *,
        publish_callbacks: PublishCallbacks | None = None,
    ) -> None:
        if mode is TransactionMode.PUBLISH and publish_callbacks is None:
            raise ValueError("PUBLISH mode requires publish_callbacks")
        if mode is not TransactionMode.PUBLISH and publish_callbacks is not None:
            raise ValueError("publish_callbacks are valid only in PUBLISH mode")
        self.connection = connection
        self.mode = mode
        self.publish_callbacks = publish_callbacks
        self._active = False
        self._published_staged = False

    @property
    def active(self) -> bool:
        return self._active

    def begin(self, mode: TransactionMode | None = None) -> "SQLiteUnitOfWork":
        if self._active:
            raise RuntimeError("unit of work is already active")
        if mode is not None and mode is not self.mode:
            raise ValueError("transaction mode is fixed when the unit of work is constructed")
        if self.mode is TransactionMode.PUBLISH:
            assert self.publish_callbacks is not None
            self.publish_callbacks.verify_staged()
            self._published_staged = True
            try:
                self.publish_callbacks.publish_staged()
            except Exception as error:
                self._compensate(error)
                raise
        sql = "BEGIN" if self.mode is TransactionMode.READ_ONLY else "BEGIN IMMEDIATE"
        try:
            self.connection.execute(sql)
        except Exception as error:
            self._compensate(error)
            raise
        self._active = True
        return self

    def _compensate(self, primary_error: BaseException | None = None) -> None:
        if self._published_staged and self.publish_callbacks is not None:
            try:
                self.publish_callbacks.compensate_unreferenced_staging()
            except Exception as compensation_error:
                if primary_error is None:
                    raise
                primary_error.add_note(
                    "Artifact publication compensation failed: "
                    f"{type(compensation_error).__name__}: {compensation_error}"
                )
            finally:
                self._published_staged = False

    def commit(self) -> None:
        if not self._active:
            raise RuntimeError("unit of work is not active")
        try:
            self.connection.commit()
        except Exception as error:
            try:
                self.connection.rollback()
            except Exception as rollback_error:
                error.add_note(
                    "Catalog rollback after commit failure also failed: "
                    f"{type(rollback_error).__name__}: {rollback_error}"
                )
            self._compensate(error)
            self._active = False
            raise
        self._active = False
        if self.mode is TransactionMode.PUBLISH:
            assert self.publish_callbacks is not None
            self._published_staged = False
            self.publish_callbacks.notify_committed()

    def rollback(self, primary_error: BaseException | None = None) -> None:
        if not self._active:
            return
        if primary_error is None:
            # Most callers use a ``finally`` block rather than passing the
            # active exception explicitly.  Preserve that exception too, so
            # a diagnostic-compensation failure cannot replace the operation
            # failure merely because cleanup was entered from ``finally``.
            current_error = sys.exc_info()[1]
            if current_error is not None:
                primary_error = current_error
        rollback_error: Exception | None = None
        try:
            self.connection.rollback()
        except Exception as error:
            rollback_error = error
        finally:
            self._active = False
        compensation_error: Exception | None = None
        try:
            self._compensate()
        except Exception as error:
            compensation_error = error
        if primary_error is not None:
            if rollback_error is not None:
                primary_error.add_note(
                    "Catalog rollback failed: "
                    f"{type(rollback_error).__name__}: {rollback_error}"
                )
            if compensation_error is not None:
                primary_error.add_note(
                    "Artifact publication compensation failed: "
                    f"{type(compensation_error).__name__}: {compensation_error}"
                )
            return
        if rollback_error is not None:
            if compensation_error is not None:
                rollback_error.add_note(
                    "Artifact publication compensation also failed: "
                    f"{type(compensation_error).__name__}: {compensation_error}"
                )
            raise rollback_error
        if compensation_error is not None:
            raise compensation_error

    def __enter__(self) -> "SQLiteUnitOfWork":
        return self.begin()

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback(exc)
        return False
