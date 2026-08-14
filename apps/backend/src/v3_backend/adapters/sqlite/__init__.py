"""SQLite Control Catalog adapter."""

from .connection import SQLiteConfig, connect_catalog
from .artifact_publication import SQLiteArtifactPublicationPort
from .repositories import SQLiteRepositoryRegistry
from .task_persistence import SQLiteTaskPersistence, SQLiteTaskUnitOfWork
from .unit_of_work import PublishCallbacks, SQLiteUnitOfWork
from .systemic_a1 import SQLiteA1CanonicalOwnerRepository

__all__ = [
    "PublishCallbacks",
    "SQLiteConfig",
    "SQLiteArtifactPublicationPort",
    "SQLiteRepositoryRegistry",
    "SQLiteTaskPersistence",
    "SQLiteTaskUnitOfWork",
    "SQLiteUnitOfWork",
    "SQLiteA1CanonicalOwnerRepository",
    "connect_catalog",
]
