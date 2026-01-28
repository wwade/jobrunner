"""
Converters between Job (new domain model) and JobInfo (old domain model).

These functions enable the adapter pattern to bridge the old and new
architectures during the migration period.
"""

from __future__ import annotations

# pylint: disable=protected-access
from typing import Any, Callable, TypeVar

from jobrunner.domain import Job, JobStatus
from jobrunner.info import JobInfo

T = TypeVar("T")


def _typed_value(
    value: Any,
    expected_type: type[T],
    default: T | Callable[[], T] | None = None,
) -> T | None:
    """Return value if it matches expected type, otherwise return default.

    Args:
        value: The value to check
        expected_type: Expected type to check against
        default: Default value or callable that returns default

    Returns:
        value if isinstance(value, expected_type), else default
    """
    if isinstance(value, expected_type):
        return value
    return default() if callable(default) else default


def _attr_or_default(
    obj: Any,
    attr: str,
    default: T | Callable[[], T] | None = None,
    copy: bool = False,
) -> T | None:
    """Get attribute value or return default.

    Args:
        obj: Object to get attribute from
        attr: Attribute name
        default: Default value or callable that returns default
        copy: If True and attribute exists, call .copy() on it

    Returns:
        Attribute value (optionally copied) or default
    """
    if hasattr(obj, attr):
        value = getattr(obj, attr)
        return value.copy() if copy else value
    return default() if callable(default) else default


def job_to_jobinfo(job: Job, parent=None) -> JobInfo:
    """
    Convert a Job (new architecture) to JobInfo (old architecture).

    Args:
        job: The Job to convert
        parent: Optional parent JobsBase instance for the JobInfo

    Returns:
        Equivalent JobInfo instance
    """
    # Create JobInfo with uidx and key
    jobinfo = JobInfo(job.uidx, job.key)

    # Copy command information
    jobinfo.prog = job.prog
    jobinfo.args = job.args
    jobinfo._cmd = job.cmd
    jobinfo.reminder = job.reminder
    jobinfo.pwd = job.pwd

    # Copy timing
    jobinfo._create = job.create_time
    jobinfo._start = job.start_time
    jobinfo._stop = job.stop_time

    # Copy status - convert JobStatus enum to stopped/active state
    jobinfo._rc = job.rc
    jobinfo.pid = job.pid
    jobinfo._blocked = job.blocked

    # Copy context
    jobinfo._workspace = job.workspace
    jobinfo._proj = job.project
    jobinfo._host = job.host
    jobinfo._user = job.user
    jobinfo._env = job.env.copy() if job.env else {}

    # Copy dependencies
    jobinfo._depends = job.depends_on if job.depends_on else None
    jobinfo._alldeps = job.all_deps.copy() if job.all_deps else set()

    # Copy metadata
    jobinfo.logfile = job.logfile
    jobinfo._autoJob = job.auto_job
    jobinfo._mailJob = job.mail_job
    jobinfo._isolate = job.isolate

    # Copy persist key information
    jobinfo._persistKey = job.persist_key
    jobinfo._persistKeyGenerated = job.persist_key_generated

    # Set parent if provided
    if parent is not None:
        jobinfo._parent = parent

    return jobinfo


def jobinfo_to_job(jobinfo: JobInfo) -> Job:
    """
    Convert a JobInfo (old architecture) to Job (new architecture).

    Args:
        jobinfo: The JobInfo to convert

    Returns:
        Equivalent Job instance
    """
    # Determine status from JobInfo state
    status = _determine_job_status(jobinfo)

    return Job(
        # Identity
        key=jobinfo._key or "",
        uidx=jobinfo._uidx,
        # Command information
        prog=jobinfo.prog,
        args=jobinfo.args,
        cmd=jobinfo._cmd,
        reminder=jobinfo.reminder,
        pwd=jobinfo.pwd,
        # Timing
        create_time=jobinfo._create,
        start_time=jobinfo._start,
        stop_time=jobinfo._stop,
        # Status
        status=status,
        rc=jobinfo._rc,
        pid=jobinfo.pid,
        blocked=_attr_or_default(jobinfo, "_blocked", False),
        # Context
        workspace=_typed_value(jobinfo._workspace, str),
        project=_typed_value(jobinfo._proj, str),
        host=jobinfo._host,
        user=jobinfo._user,
        env=jobinfo._env.copy() if jobinfo._env else {},
        # Dependencies
        depends_on=jobinfo._depends if jobinfo._depends else [],
        all_deps=_attr_or_default(jobinfo, "_alldeps", set, copy=True),
        # Metadata
        logfile=jobinfo.logfile,
        auto_job=_attr_or_default(jobinfo, "_autoJob", False),
        mail_job=_attr_or_default(jobinfo, "_mailJob", False),
        isolate=_attr_or_default(jobinfo, "_isolate", False),
        # Backward compatibility
        persist_key=jobinfo._persistKey,
        persist_key_generated=jobinfo._persistKeyGenerated,
    )


def _determine_job_status(jobinfo: JobInfo) -> JobStatus:
    """Determine JobStatus from JobInfo state."""
    if jobinfo._stop is not None:
        return JobStatus.COMPLETED
    elif hasattr(jobinfo, "_blocked") and jobinfo._blocked:
        return JobStatus.BLOCKED
    elif jobinfo._start is not None:
        return JobStatus.RUNNING
    else:
        return JobStatus.PENDING
