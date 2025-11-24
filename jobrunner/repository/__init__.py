"""
Repository layer for job persistence.

This package contains the repository pattern implementation for
storing and retrieving jobs from persistent storage.
"""

from .interface import JobRepository, Metadata
from .sqlite_repository import SqliteJobRepository

__all__ = ["JobRepository", "Metadata", "SqliteJobRepository"]
