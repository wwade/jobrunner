"""
Business logic for job lifecycle management.

This module contains the JobService class which handles all business
logic for creating, starting, stopping, and querying jobs.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import md5
import logging
import os
import posixpath
import tempfile
from typing import List, Optional, Tuple

from jobrunner.config import Config
from jobrunner.domain import Job, JobStatus
from jobrunner.repository import JobRepository
from jobrunner.utils import (
    FileLock,
    keyEscape,
    utcNow,
    workspaceIdentity,
    workspaceProject,
)

LOG = logging.getLogger(__name__)


class LockContextManager:
    """Context manager wrapper for FileLock."""

    def __init__(self, lock: FileLock):
        self.lock = lock

    def __enter__(self):
        self.lock.lock()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _ = (exc_type, exc_val, exc_tb)
        self.lock.unlock()
        return False


def get_log_parent_dir(filename: str) -> str:
    """Get parent directory for log file based on hash."""
    return md5(filename.encode()).hexdigest()[:2]


class JobService:
    """
    Service for job lifecycle management.

    This class contains all business logic for jobs, including:
    - Creating new jobs
    - Starting/stopping jobs
    - Managing dependencies
    - Querying jobs
    - Matching jobs by key/pattern
    """

    def __init__(
        self, repo: JobRepository, config: Config, lock: Optional[FileLock] = None
    ):
        """
        Initialize service.

        Args:
            repo: Job repository for persistence
            config: Application configuration
            lock: Optional file lock (will create one if not provided)
        """
        self.repo = repo
        self.config = config
        self._file_lock = lock or FileLock(config.lockFile)
        self._lock = LockContextManager(self._file_lock)

    # pylint: disable-next=too-many-locals
    def create_job(
        self,
        cmd: Optional[List[str]],
        reminder: Optional[str] = None,
        isolate: bool = False,
        auto_job: bool = False,
        key: Optional[str] = None,
    ) -> Tuple[Job, int]:
        """
        Create a new job.

        Args:
            cmd: Command to run (None if reminder)
            reminder: Reminder text (None if command)
            isolate: Whether to isolate the job
            auto_job: Whether this is an automatic job
            key: Optional explicit key (will generate if not provided)

        Returns:
            Tuple of (job, logfile_fd)

        Raises:
            ValueError: If key already exists in active jobs
        """
        with self._lock:
            # Check for key conflict
            if key and self.repo.exists(key):
                existing = self.repo.get(key)
                if existing and existing.is_active():
                    raise ValueError(f"Active key conflict for key {key!r}")

            # Generate unique index
            uidx = self.repo.next_uidx()

            # Generate key if not provided
            if not key:
                key_source = cmd[0] if cmd else reminder
                assert key_source is not None
                key = f"{utcNow().strftime('%s')}{uidx}_{keyEscape(key_source)}"

            # Create job
            job = Job(
                key=key,
                uidx=uidx,
                prog=cmd[0] if cmd else None,
                args=cmd[1:] if cmd and len(cmd) > 1 else None,
                cmd=cmd if cmd else ["(reminder)"],
                reminder=reminder,
                pwd=os.getcwd(),
                create_time=utcNow(),
                status=JobStatus.PENDING,
                isolate=isolate,
                auto_job=auto_job,
                pid=os.getpid(),
                host=os.getenv("HOSTNAME"),
                user=os.getenv("USER"),
                env=dict(os.environ),
            )

            # Resolve workspace and project
            job.workspace = workspaceIdentity()
            job.project = workspaceProject()

            # Create logfile
            logfile_name = "___" + job.key + ".log"
            dir_name = get_log_parent_dir(logfile_name)
            log_dir = posixpath.join(self.config.logDir, dir_name)
            os.makedirs(log_dir, exist_ok=True)
            (fd, log_file_path) = tempfile.mkstemp(suffix=logfile_name, dir=log_dir)
            job.logfile = log_file_path

            # Set persist key
            job.persist_key_generated = key

            # Save job
            self.repo.save(job)

            # Update metadata
            if not auto_job:
                metadata = self.repo.get_metadata()
                metadata.last_job = key
                self.repo.update_metadata(metadata)

            LOG.info("Created job %s: %s", key, job.cmd_str())

            return job, fd

    def start_job(self, key: str, pid: int) -> Job:
        """
        Mark a job as started.

        Args:
            key: Job key
            pid: Process ID

        Returns:
            Updated job

        Raises:
            ValueError: If job not found
        """
        with self._lock:
            job = self.repo.get(key)
            if not job:
                raise ValueError(f"Job {key} not found")

            job.status = JobStatus.RUNNING
            job.start_time = utcNow()
            job.pid = pid

            self.repo.save(job)

            # Update last key metadata
            metadata = self.repo.get_metadata()
            metadata.last_key = key
            self.repo.update_metadata(metadata)

            LOG.info("Started job %s (pid %d)", key, pid)

            return job

    def complete_job(self, key: str, rc: int) -> Job:
        """
        Mark a job as completed.

        Args:
            key: Job key
            rc: Exit code

        Returns:
            Updated job

        Raises:
            ValueError: If job not found
        """
        with self._lock:
            job = self.repo.get(key)
            if not job:
                raise ValueError(f"Job {key} not found")

            job.status = JobStatus.COMPLETED
            job.stop_time = utcNow()
            job.rc = rc
            job.pid = None

            self.repo.save(job)

            LOG.info("Completed job %s with rc=%d", key, rc)

            return job

    def block_job(self, key: str) -> Job:
        """
        Mark a job as blocked.

        Args:
            key: Job key

        Returns:
            Updated job

        Raises:
            ValueError: If job not found
        """
        with self._lock:
            job = self.repo.get(key)
            if not job:
                raise ValueError(f"Job {key} not found")

            job.blocked = True
            job.status = JobStatus.BLOCKED

            self.repo.save(job)

            LOG.info("Blocked job %s", key)

            return job

    def unblock_job(self, key: str) -> Job:
        """
        Mark a job as unblocked.

        Args:
            key: Job key

        Returns:
            Updated job

        Raises:
            ValueError: If job not found
        """
        with self._lock:
            job = self.repo.get(key)
            if not job:
                raise ValueError(f"Job {key} not found")

            job.blocked = False
            if job.status == JobStatus.BLOCKED:
                job.status = JobStatus.PENDING

            self.repo.save(job)

            LOG.info("Unblocked job %s", key)

            return job

    def set_dependencies(self, key: str, depends_on: List[str]) -> Job:
        """
        Set job dependencies.

        Args:
            key: Job key
            depends_on: List of job keys this job depends on

        Returns:
            Updated job

        Raises:
            ValueError: If job not found
        """
        with self._lock:
            job = self.repo.get(key)
            if not job:
                raise ValueError(f"Job {key} not found")

            job.depends_on = depends_on
            # all_deps is kept in sync with depends_on (not stored separately in DB)
            job.all_deps = set(depends_on)

            self.repo.save(job)

            LOG.info("Set dependencies for job %s: %s", key, depends_on)

            return job

    def update_pid(self, key: str, pid: int) -> Job:
        """
        Update job PID.

        Args:
            key: Job key
            pid: Process ID

        Returns:
            Updated job

        Raises:
            ValueError: If job not found
        """
        with self._lock:
            job = self.repo.get(key)
            if not job:
                raise ValueError(f"Job {key} not found")

            job.pid = pid

            self.repo.save(job)

            LOG.debug("Updated PID for job %s to %d", key, pid)

            return job

    def get_job(self, key: str) -> Optional[Job]:
        """
        Get a job by key.

        Args:
            key: Job key

        Returns:
            Job if found, None otherwise
        """
        return self.repo.get(key)

    def get_active_jobs(
        self,
        workspace: Optional[str] = None,
        skip_reminders: bool = False,
    ) -> List[Job]:
        """
        Get all active (non-completed) jobs.

        Args:
            workspace: Filter by workspace (None = all workspaces)
            skip_reminders: If True, exclude reminder jobs

        Returns:
            List of active jobs, sorted by create time
        """
        jobs = self.repo.find_active(workspace=workspace)

        if skip_reminders:
            jobs = [j for j in jobs if j.reminder is None]

        return jobs

    def get_completed_jobs(
        self,
        workspace: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """
        Get completed jobs.

        Args:
            workspace: Filter by workspace (None = all workspaces)
            limit: Maximum number of results

        Returns:
            List of completed jobs, sorted by stop time descending
        """
        return self.repo.find_completed(workspace=workspace, limit=limit)

    def get_recent_jobs(
        self,
        workspace: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """
        Get recent jobs (completed, sorted by stop time).

        Args:
            workspace: Filter by workspace
            limit: Maximum number of results

        Returns:
            List of recent jobs
        """
        return self.get_completed_jobs(workspace=workspace, limit=limit)

    # pylint: disable-next=too-many-branches
    def find_job_by_pattern(
        self,
        pattern: Optional[str],
        workspace_filter: bool = False,
        skip_reminders: bool = False,
    ) -> Job:
        """
        Find a job by key or command pattern.

        Args:
            pattern: Search pattern (key, command substring, or None for most recent)
            workspace_filter: If True, filter to current workspace
            skip_reminders: If True, skip reminder jobs

        Returns:
            Matching job

        Raises:
            ValueError: If no matching job found or database is empty
        """
        current_ws = workspaceIdentity() if workspace_filter else None

        # Handle special patterns
        if pattern == ".":
            # Get last job from metadata
            metadata = self.repo.get_metadata()
            if metadata.last_job:
                return self.find_job_by_pattern(
                    metadata.last_job, workspace_filter, skip_reminders
                )

        if pattern is None:
            # Get most recent job
            active = self.get_active_jobs(workspace=current_ws)
            if skip_reminders:
                active = [j for j in active if j.reminder is None]

            if active:
                return active[-1]

            # Try completed
            completed = self.get_completed_jobs(workspace=current_ws, limit=1)
            if skip_reminders and completed:
                completed = [j for j in completed if j.reminder is None]

            if completed:
                return completed[0]

            raise ValueError("Job database is empty")

        # Try exact match first
        job = self.repo.get(pattern)
        if job:
            return job

        # Search in active jobs by command string
        active_jobs = self.get_active_jobs(workspace=current_ws)

        for job in active_jobs:
            if job.mail_job:
                continue
            if skip_reminders and job.reminder:
                continue

            if pattern in job.cmd_str():
                return job

        # Search in recent completed jobs
        metadata = self.repo.get_metadata()
        for key in metadata.recent_keys:
            job = self.repo.get(key)
            if not job:
                continue

            if job.mail_job:
                continue
            if skip_reminders and job.reminder:
                continue
            if workspace_filter and current_ws and job.workspace != current_ws:
                continue

            # Check command match or key prefix match
            if pattern in job.cmd_str() or key.startswith(pattern):
                return job

        raise ValueError(f"No job for key {pattern!r}")

    def delete_job(self, key: str) -> None:
        """
        Delete a job.

        Args:
            key: Job key
        """
        with self._lock:
            self.repo.delete(key)
            LOG.info("Deleted job %s", key)

    def prune_jobs(self, keep_count: int = 5000) -> int:
        """
        Prune old completed jobs.

        Args:
            keep_count: Number of most recent completed jobs to keep

        Returns:
            Number of jobs deleted
        """
        with self._lock:
            completed = self.repo.find_completed()

            # Sort oldest first
            completed.sort(key=lambda j: j.stop_time or j.create_time or 0)

            if len(completed) <= keep_count:
                return 0

            # Delete oldest jobs
            to_delete = completed[:-keep_count]

            for job in to_delete:
                # Remove logfile if it exists
                if job.logfile and os.path.exists(job.logfile):
                    try:
                        os.unlink(job.logfile)
                        LOG.debug("Removed logfile %s", job.logfile)
                    except OSError as e:
                        LOG.warning(
                            "Failed to remove logfile %s: %s", job.logfile, e
                        )

                # Delete job
                self.repo.delete(job.key)

            LOG.info("Pruned %d jobs", len(to_delete))
            return len(to_delete)

    def set_checkpoint(self, timestamp: Optional[datetime] = None) -> None:
        """
        Set checkpoint timestamp.

        Args:
            timestamp: Timestamp to set (None = now)
        """
        with self._lock:
            metadata = self.repo.get_metadata()
            metadata.checkpoint = timestamp or utcNow()
            self.repo.update_metadata(metadata)
            LOG.info("Set checkpoint to %s", metadata.checkpoint)

    def get_jobs_since_checkpoint(
        self,
        workspace: Optional[str] = None,
    ) -> List[Job]:
        """
        Get jobs created since checkpoint.

        Args:
            workspace: Filter by workspace

        Returns:
            List of jobs created after checkpoint
        """
        metadata = self.repo.get_metadata()
        if not metadata.checkpoint:
            # No checkpoint set, return empty list
            return []

        return self.repo.find_all(
            workspace=workspace,
            since=metadata.checkpoint,
        )

    def count_active(self) -> int:
        """Count active jobs."""
        return self.repo.count() - self.repo.count(JobStatus.COMPLETED)

    def count_completed(self) -> int:
        """Count completed jobs."""
        return self.repo.count(JobStatus.COMPLETED)

    def is_locked(self) -> bool:
        """Check if service is locked."""
        return self._file_lock.isLocked()

    def close(self) -> None:
        """Close service and release resources."""
        self.repo.close()
