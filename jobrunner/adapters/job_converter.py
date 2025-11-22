"""
Converters between Job (new domain model) and JobInfo (old domain model).

These functions enable the adapter pattern to bridge the old and new
architectures during the migration period.
"""

# pylint: disable=protected-access

from jobrunner.domain import Job, JobStatus
from jobrunner.info import JobInfo


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
        blocked=jobinfo._blocked if hasattr(jobinfo, "_blocked") else False,
        # Context
        workspace=jobinfo._workspace if isinstance(
            jobinfo._workspace,
            str) else None,
        project=jobinfo._proj if isinstance(
            jobinfo._proj,
            str) else None,
        host=jobinfo._host,
        user=jobinfo._user,
        env=jobinfo._env.copy() if jobinfo._env else {},
        # Dependencies
        depends_on=jobinfo._depends if jobinfo._depends else [],
        all_deps=jobinfo._alldeps.copy() if hasattr(
            jobinfo,
            "_alldeps") else set(),
        # Metadata
        logfile=jobinfo.logfile,
        auto_job=jobinfo._autoJob if hasattr(jobinfo, "_autoJob") else False,
        mail_job=jobinfo._mailJob if hasattr(jobinfo, "_mailJob") else False,
        isolate=jobinfo._isolate if hasattr(jobinfo, "_isolate") else False,
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
