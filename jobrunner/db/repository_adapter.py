"""
Adapter that implements JobsBase using the new repository architecture.

This adapter allows existing code to continue using the JobsBase interface
while internally using the new SqliteJobRepository and JobService.
"""

# pylint: disable=protected-access
# pylint: disable=too-many-return-statements

from __future__ import annotations

import json
import os
import posixpath
import tempfile
from typing import Optional

from jobrunner.adapters.job_converter import job_to_jobinfo, jobinfo_to_job
from jobrunner.config import Config
from jobrunner.domain import Job, JobStatus
from jobrunner.info import JobInfo
from jobrunner.repository import SqliteJobRepository
from jobrunner.service import service
from jobrunner.utils import dateTimeFromJson, dateTimeToJson, workspaceIdentity

from . import (
    DatabaseBase,
    JobsBase,
    NoMatchingJobError,
    ValuesCache,
    getLogParentDir,
)


class FakeDatabase(DatabaseBase):
    """
    Fake database that delegates to the repository for a specific status.

    This provides the old-style dict interface for active/inactive databases
    while using the new repository underneath.
    """

    def __init__(self, parent, config, instanceId, status_filter: JobStatus):
        """
        Initialize fake database.

        Args:
            parent: Parent RepositoryAdapter instance
            config: Configuration object
            instanceId: Unique instance ID
            status_filter: JobStatus to filter by (or None for all statuses)
        """
        super().__init__(parent, config, instanceId)
        self._status_filter = status_filter
        self.ident = "active" if status_filter != JobStatus.COMPLETED else "inactive"
        self._db_dict = {}  # Used for special keys like metadata

    @property
    def db(self):
        """Return self to provide dict-like interface."""
        return self

    def keys(self):
        """Return all job keys matching the status filter."""
        repo: SqliteJobRepository = self._parent._repo

        # Use efficient get_keys() that only fetches key column
        if self._status_filter == JobStatus.COMPLETED:
            return repo.get_keys(status=JobStatus.COMPLETED)
        else:
            return repo.get_keys(exclude_completed=True)

    def __contains__(self, key):
        """Check if key exists in this database."""
        if key in self._db_dict:
            return True

        repo: SqliteJobRepository = self._parent._repo
        job = repo.get(key)
        if job is None:
            return False
        if self._status_filter == JobStatus.COMPLETED:
            return job.status == JobStatus.COMPLETED
        else:
            return job.status != JobStatus.COMPLETED

    def __getitem__(self, key):
        # pylint: disable=too-many-branches
        """Get item by key."""
        if key in self._db_dict:
            return self._db_dict[key]

        # Handle special metadata keys
        if key in self.special:
            metadata = self._parent._repo.get_metadata()
            if key == self.SV:
                return metadata.schema_version
            elif key == self.LASTKEY:
                return metadata.last_key
            elif key == self.LASTJOB:
                return metadata.last_job
            elif key == self.CHECKPOINT:
                return json.dumps(dateTimeToJson(metadata.checkpoint))
            elif key == self.RECENT:
                return json.dumps(metadata.recent_keys)
            elif key == self.ITEMCOUNT:
                repo: SqliteJobRepository = self._parent._repo
                if self._status_filter == JobStatus.COMPLETED:
                    count = repo.count(JobStatus.COMPLETED)
                else:
                    count = repo.count() - repo.count(JobStatus.COMPLETED)
                return str(count)
            else:
                return ""

        repo: SqliteJobRepository = self._parent._repo
        job = repo.get(key)
        if job is None:
            raise KeyError(key)

        jobinfo = job_to_jobinfo(job, parent=self._parent)
        return jobinfo

    def __setitem__(self, key, value):
        """Set item by key."""
        # Handle special metadata keys
        if key in self.special:
            self._db_dict[key] = value
            # Update metadata in repository
            if key in (
                self.SV,
                self.LASTKEY,
                self.LASTJOB,
                self.CHECKPOINT,
                self.RECENT,
            ):
                self._update_metadata_from_dict()
            return

        # Handle JobInfo objects
        if isinstance(value, JobInfo):
            job = jobinfo_to_job(value)
            self._parent._repo.save(job)
        else:
            self._db_dict[key] = value

    def __delitem__(self, key):
        """Delete item by key."""
        if key in self._db_dict:
            del self._db_dict[key]
        else:
            self._parent._repo.delete(key)

    def _update_metadata_from_dict(self):
        """Update repository metadata from dict values."""
        metadata = self._parent._repo.get_metadata()

        if self.SV in self._db_dict:
            metadata.schema_version = self._db_dict[self.SV]
        if self.LASTKEY in self._db_dict:
            metadata.last_key = self._db_dict[self.LASTKEY]
        if self.LASTJOB in self._db_dict:
            metadata.last_job = self._db_dict[self.LASTJOB]
        if self.CHECKPOINT in self._db_dict:
            metadata.checkpoint = dateTimeFromJson(
                json.loads(self._db_dict[self.CHECKPOINT])
            )
        if self.RECENT in self._db_dict:
            metadata.recent_keys = json.loads(self._db_dict[self.RECENT])

        self._parent._repo.update_metadata(metadata)

    @property
    def recent(self):
        """Get recent keys list."""
        metadata = self._parent._repo.get_metadata()
        return metadata.recent_keys

    def __len__(self):
        """Return number of jobs in this database + special keys."""
        # The countInactive method expects len(db) to include special keys
        # because it subtracts them: len(db) - (len(special) - 1)
        # We return job_count + (special_count - 1) to match old behavior
        job_count = len(self.keys())
        special_count = len(self.special)
        return job_count + (special_count - 1)

    def values(self, cache: Optional[ValuesCache] = None):
        """
        Return all JobInfo objects (bulk fetch to avoid N+1 queries).

        Args:
            cache: Optional ValuesCache for caching results within a single
                   operation. If provided and has cached values, returns cached
                   result. Otherwise queries repository and stores result in cache.
        """
        # Use provided cache if available
        if cache is not None and cache.values is not None:
            return cache.values

        repo: SqliteJobRepository = self._parent._repo
        if self._status_filter == JobStatus.COMPLETED:
            # Use for_listing=True to optimize performance by skipping
            # expensive JSON parsing of args_json, env_json, depends_on_json
            jobs = repo.find_completed(for_listing=True)
        else:
            jobs = repo.find_active()

        result = [job_to_jobinfo(job, parent=self._parent) for job in jobs]

        # Store in cache if provided
        if cache is not None:
            cache.values = result

        return result


class RepositoryAdapter(JobsBase):
    """
    JobsBase adapter that uses the new SqliteJobRepository.

    This adapter allows existing code to work without changes by implementing
    the JobsBase interface while delegating to the new architecture.
    """

    def __init__(self, config: Config, plugins):
        """Initialize adapter with repository."""
        super().__init__(config, plugins)

        # Create repository
        db_path = os.path.join(config.dbDir, "jobs.db")
        self._repo = SqliteJobRepository(db_path)

        # Create fake active/inactive databases
        # Override properties to prevent parent class assertions from failing
        self.active = FakeDatabase(
            self, config, self._instanceId, None
        )  # None = non-completed
        self.inactive = FakeDatabase(
            self, config, self._instanceId, JobStatus.COMPLETED
        )

    def countInactive(self):
        """Count inactive (completed) jobs."""
        return self._repo.count(JobStatus.COMPLETED)

    def isLocked(self):
        """Check if database is locked."""
        return self._lock.isLocked()

    def lock(self):
        """Lock the database."""
        super().lock()
        self._lock.lock()

    def unlock(self):
        """Unlock the database."""
        super().unlock()
        self._lock.unlock()

    def new(self, cmd, isolate, autoJob=False, key=None, reminder=None):
        """
        Create a new job.

        Returns:
            Tuple of (JobInfo, file_descriptor) for the log file
        """
        if key and self._repo.exists(key):
            raise Exception("Active key conflict for key %r" % key)

        # Create JobInfo using service registry
        uidx = self._repo.next_uidx()
        job_info = service().db.jobInfo(uidx, key)
        job_info.isolate = isolate
        job_info.setCmd(cmd, reminder)
        job_info.pid = os.getpid()
        job_info.autoJob = autoJob

        # Create log file
        logfile = "___" + job_info.key + ".log"
        dirName = getLogParentDir(logfile)
        logDir = posixpath.join(self.config.logDir, dirName)
        os.makedirs(logDir, exist_ok=True)
        (fd, logFileName) = tempfile.mkstemp(suffix=logfile, dir=logDir)
        job_info.logfile = logFileName
        job_info.parent = self

        # Update last job metadata
        if not autoJob:
            metadata = self._repo.get_metadata()
            metadata.last_job = job_info.key
            self._repo.update_metadata(metadata)

        return job_info, fd

    def get(self, key: str) -> Job | None:
        return self._repo.get(key)

    def findJobsMatching(self, keyword, thisWs, skipReminders=False, useCp=False):
        """
        Find all jobs matching the given keyword.

        Similar to getJobMatch but returns all matching jobs instead of just one.
        Uses efficient SQL query via the repository.
        """
        # Determine workspace filter
        workspace = workspaceIdentity() if thisWs else None

        # Determine checkpoint filter
        since = None
        if useCp:
            metadata = self._repo.get_metadata()
            since = metadata.checkpoint

        # Query repository
        jobs = self._repo.find_matching(
            keyword=keyword,
            workspace=workspace,
            skip_reminders=skipReminders,
            since=since,
        )

        # Convert to JobInfo objects
        return [job_to_jobinfo(job, parent=self) for job in jobs]

    def getJobMatch(self, key, thisWs, skipReminders=False):
        """
        Get a job by key or pattern.

        This overrides the parent class implementation to use efficient
        SQL queries instead of loading all jobs when key is None.
        Also handles exact key matches efficiently to avoid duplicate queries.

        Args:
            key: Job key, pattern, ".", or None for most recent job
            thisWs: If True, filter by current workspace
            skipReminders: If True, exclude reminder jobs

        Returns:
            JobInfo object for the matching job

        Raises:
            NoMatchingJobError: If no job matches the criteria
        """
        # Handle "." alias - get last job from metadata
        if key == ".":
            metadata = self._repo.get_metadata()
            lastJob = metadata.last_job
            if lastJob:
                return self.getJobMatch(lastJob, thisWs, skipReminders)

        # Fast path for exact key match - query database once
        if key is not None and key != ".":
            job = self._repo.get(key)
            if job is not None:
                # Found exact match - verify it passes filters
                if skipReminders and job.reminder:
                    pass  # Fall through to search logic
                else:
                    return job_to_jobinfo(job, parent=self)

        # Fast path for key is None: use optimized find_latest
        if key is None:
            workspace = workspaceIdentity() if thisWs else None

            # Try to find most recent non-completed, non-reminder job
            job = self._repo.find_latest(
                exclude_completed=True,
                workspace=workspace,
                skip_reminders=skipReminders,
                skip_mail_jobs=True,
            )
            if job:
                return job_to_jobinfo(job, parent=self)

            # Try completed jobs with same filters
            job = self._repo.find_latest(
                exclude_completed=False,
                workspace=workspace,
                skip_reminders=skipReminders,
                skip_mail_jobs=True,
            )
            if job and job.status == JobStatus.COMPLETED:
                return job_to_jobinfo(job, parent=self)

            # Try completed jobs without reminder filter
            job = self._repo.find_latest(
                exclude_completed=False,
                workspace=workspace,
                skip_reminders=False,
                skip_mail_jobs=True,
            )
            if job and job.status == JobStatus.COMPLETED:
                return job_to_jobinfo(job, parent=self)

            raise NoMatchingJobError("Job database is empty")

        # Fall back to parent implementation for other cases (key matching, etc.)
        return super().getJobMatch(key, thisWs, skipReminders)

    def getDbSorted(
        self,
        db: DatabaseBase,
        _limit: int | None = None,
        useCp: bool = False,
        filterWs: bool = False,
        cache: Optional[ValuesCache] = None,
    ) -> list[JobInfo]:
        """
        Get sorted list of jobs from database with optional filters.

        This overrides the parent class implementation to use efficient
        SQL queries with indexed WHERE clauses instead of loading all
        jobs and filtering in Python.

        Note: Parent class uses @staticmethod but we override as instance
        method to access self._repo.

        Args:
            db: Database to query (active or inactive)
            _limit: Optional limit on number of results
            useCp: If True, filter by checkpoint time
            filterWs: If True, filter by current workspace
            cache: Optional ValuesCache for caching db.values() within operation

        Returns:
            List of JobInfo objects sorted by creation time
        """
        # Determine workspace filter
        workspace = None
        if filterWs:
            workspace = workspaceIdentity()

        # Determine checkpoint filter
        since = None
        if useCp:
            metadata = self._repo.get_metadata()
            since = metadata.checkpoint

        # Optimize: if no filters, use db.values() with cache to avoid
        # duplicate repository calls within the same operation
        if not workspace and not since and not _limit:
            # Use cached values() - this avoids duplicate queries when listDb
            # calls both getDbSorted() and db.values() for dependency tree
            job_infos = list(db.values(cache=cache))
        elif db.ident == "active":
            if since:
                # Use find_all when checkpoint filter is needed
                jobs = self._repo.find_all(
                    status=None, workspace=workspace, since=since, limit=_limit
                )
                # Exclude completed jobs
                jobs = [job for job in jobs if job.status != JobStatus.COMPLETED]
            else:
                # Use find_active for better performance (filters at SQL level)
                jobs = self._repo.find_active(workspace=workspace)
                # Apply limit if needed
                if _limit and len(jobs) > _limit:
                    jobs = jobs[:_limit]
            # Convert to JobInfo objects
            job_infos = [job_to_jobinfo(job, parent=self) for job in jobs]
        else:
            if since:
                # Use find_all when checkpoint filter is needed
                jobs = self._repo.find_all(
                    status=JobStatus.COMPLETED,
                    workspace=workspace,
                    since=since,
                    limit=_limit,
                )
            else:
                # Use find_completed for better performance
                # for_listing=True optimizes for display by skipping expensive
                # JSON parsing of args_json, env_json, depends_on_json
                jobs = self._repo.find_completed(
                    workspace=workspace, limit=_limit, for_listing=True
                )
            # Convert to JobInfo objects
            job_infos = [job_to_jobinfo(job, parent=self) for job in jobs]

        # Already sorted by create_time in SQL query for active jobs
        # For completed jobs, sorted by stop_time DESC, so re-sort by create_time
        # to match parent behavior (parent does jobList.sort(reverse=False))
        job_infos.sort(reverse=False)

        return job_infos

    def add_sequence_step(
        self,
        name: str,
        job_key: str,
        dependencies: list[tuple[int, str]],
    ) -> int:
        return self._repo.add_sequence_step(name, job_key, dependencies)

    def is_sequence(self, name: str) -> bool:
        """Check if a sequence with the given name exists."""
        return self._repo.is_sequence(name)

    def list_sequences(self) -> list[str]:
        """
        List all saved sequences.

        Returns:
            List of sequence names
        """
        return self._repo.list_sequences()

    def delete_sequence(self, name: str) -> None:
        self._repo.delete_sequence(name)

    def get_sequence_steps(self, name: str):
        """
        Get all steps in a sequence with their dependencies.

        Args:
            name: Sequence name

        Returns:
            List of (step_number, job_key, dependencies) tuples
        """
        return self._repo.get_sequence_steps(name)
