"""
Repository interface for job persistence.

This module defines the abstract interface that all repository
implementations must follow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from jobrunner.domain import Job, JobStatus


@dataclass
class Metadata:
    """Database metadata."""

    schema_version: str
    last_key: str = ""
    last_job: str = ""
    checkpoint: Optional[datetime] = None
    recent_keys: List[str] = None

    def __post_init__(self):
        if self.recent_keys is None:
            self.recent_keys = []


class JobRepository(ABC):
    """
    Abstract repository for job persistence.

    This interface defines all operations for storing and retrieving jobs.
    Implementations handle the actual database interaction.
    """

    @abstractmethod
    def save(self, job: Job) -> None:
        """
        Save or update a job.

        Args:
            job: The job to save
        """

    @abstractmethod
    def get(self, key: str) -> Optional[Job]:
        """
        Get a job by key.

        Args:
            key: The job key

        Returns:
            The job if found, None otherwise
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Delete a job by key.

        Args:
            key: The job key
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if a job exists.

        Args:
            key: The job key

        Returns:
            True if job exists, False otherwise
        """

    @abstractmethod
    def find_all(
        self,
        status: Optional[JobStatus] = None,
        workspace: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """
        Find jobs matching criteria.

        Args:
            status: Filter by status (None = all statuses)
            workspace: Filter by workspace (None = all workspaces)
            since: Filter by create_time >= since (None = no time filter)
            limit: Maximum number of results (None = no limit)

        Returns:
            List of matching jobs, sorted by create_time
        """

    @abstractmethod
    def find_active(self, workspace: Optional[str] = None) -> List[Job]:
        """
        Get all non-completed jobs.

        Args:
            workspace: Filter by workspace (None = all workspaces)

        Returns:
            List of active jobs, sorted by create_time
        """

    @abstractmethod
    def find_completed(
        self,
        workspace: Optional[str] = None,
        limit: Optional[int] = None,
        for_listing: bool = False,
    ) -> List[Job]:
        """
        Get completed jobs.

        Args:
            workspace: Filter by workspace (None = all workspaces)
            limit: Maximum number of results (None = no limit)
            for_listing: If True, only fetch fields needed for display
                        (optimized for job -L performance)

        Returns:
            List of completed jobs, sorted by stop_time descending
        """

    @abstractmethod
    def search_by_command(
        self,
        query: str,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """
        Search jobs by command string.

        Args:
            query: Search string to find in command
            limit: Maximum number of results (None = no limit)

        Returns:
            List of matching jobs
        """

    @abstractmethod
    def get_metadata(self) -> Metadata:
        """
        Get repository metadata.

        Returns:
            Metadata object
        """

    @abstractmethod
    def update_metadata(self, metadata: Metadata) -> None:
        """
        Update repository metadata.

        Args:
            metadata: The metadata to save
        """

    @abstractmethod
    def next_uidx(self) -> int:
        """
        Get next unique index and increment counter.

        Returns:
            The next unique index
        """

    @abstractmethod
    def count(self, status: Optional[JobStatus] = None) -> int:
        """
        Count jobs.

        Args:
            status: Filter by status (None = count all jobs)

        Returns:
            Number of matching jobs
        """

    @abstractmethod
    def is_sequence(self, name: str) -> bool:
        """
        Check if a sequence exists.

        Args:
            name: The sequence name

        Returns:
            True if sequence exists, False otherwise
        """

    @abstractmethod
    def list_sequences(self) -> list[str]:
        """
        List all sequence names.

        Returns:
            Sorted list of sequence names
        """

    @abstractmethod
    def delete_sequence(self, name: str) -> None:
        """
        Delete a sequence and all its steps.

        Args:
            name: The sequence name to delete
        """

    @abstractmethod
    def close(self) -> None:
        """Close repository and release resources."""
