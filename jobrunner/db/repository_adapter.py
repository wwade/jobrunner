"""
Adapter that implements JobsBase using the new repository architecture.

This adapter allows existing code to continue using the JobsBase interface
while internally using the new SqliteJobRepository and JobService.
"""

# pylint: disable=protected-access
# pylint: disable=import-outside-toplevel
# pylint: disable=too-many-return-statements

from __future__ import annotations

import json
import os
import posixpath
import tempfile

from jobrunner.adapters.job_converter import job_to_jobinfo, jobinfo_to_job
from jobrunner.config import Config
from jobrunner.domain import JobStatus
from jobrunner.info import JobInfo
from jobrunner.repository import SqliteJobRepository
from jobrunner.service import service
from jobrunner.utils import dateTimeFromJson, dateTimeToJson

from . import DatabaseBase, JobsBase, getLogParentDir


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
        self.ident = (
            "active" if status_filter != JobStatus.COMPLETED else "inactive")
        self._db_dict = {}  # Used for special keys like metadata

    @property
    def db(self):
        """Return self to provide dict-like interface."""
        return self

    def keys(self):
        """Return all job keys matching the status filter."""
        repo: SqliteJobRepository = self._parent._repo
        if self._status_filter == JobStatus.COMPLETED:
            jobs = repo.find_completed()
        else:
            jobs = repo.find_active()
        # Return only job keys, not special metadata keys
        return [job.key for job in jobs]

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
            if key in (self.SV, self.LASTKEY, self.LASTJOB,
                       self.CHECKPOINT, self.RECENT):
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
                json.loads(self._db_dict[self.CHECKPOINT]))
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
            self, config, self._instanceId, None)  # None = non-completed
        self.inactive = FakeDatabase(
            self, config, self._instanceId, JobStatus.COMPLETED)

    @property
    def active(self):
        """Override active property to bypass parent assertion."""
        return self._active

    @active.setter
    def active(self, value):
        """Override active setter."""
        self._active = value

    @property
    def inactive(self):
        """Override inactive property to bypass parent assertion."""
        return self._inactive

    @inactive.setter
    def inactive(self, value):
        """Override inactive setter."""
        self._inactive = value

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

    def findJobsMatching(self, keyword, thisWs, skipReminders=False):
        """
        Find all jobs matching the given keyword.

        Similar to getJobMatch but returns all matching jobs instead of just one.
        Uses efficient SQL query via the repository.
        """
        from jobrunner import utils

        # Determine workspace filter
        workspace = utils.workspaceIdentity() if thisWs else None

        # Query repository
        jobs = self._repo.find_matching(
            keyword=keyword,
            workspace=workspace,
            skip_reminders=skipReminders
        )

        # Convert to JobInfo objects
        return [job_to_jobinfo(job, parent=self) for job in jobs]
