"""
Pure domain model for jobs.

This module contains the Job dataclass which represents a job with no
coupling to the database layer. All persistence logic is handled by
the repository layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from shlex import quote
from typing import Dict, List, Optional

from dateutil.tz import tzutc

from .. import utils


class JobStatus(Enum):
    """Job lifecycle states."""

    PENDING = "pending"  # Created but not started
    BLOCKED = "blocked"  # Waiting on dependencies
    RUNNING = "running"  # Currently executing
    COMPLETED = "completed"  # Finished (any exit code)


@dataclass
class Job:  # pylint: disable=too-many-instance-attributes
    """
    Pure domain model representing a job.

    This class contains only data and simple domain logic. It has no
    knowledge of how jobs are persisted or retrieved from storage.
    """

    # Identity
    key: str
    uidx: int

    # Command information
    prog: Optional[str] = None
    args: Optional[List[str]] = None
    cmd: Optional[List[str]] = None
    reminder: Optional[str] = None
    pwd: Optional[str] = None

    # Timing
    create_time: Optional[datetime] = None
    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None

    # Status
    status: JobStatus = JobStatus.PENDING
    rc: Optional[int] = None
    pid: Optional[int] = None
    blocked: bool = False

    # Context
    workspace: Optional[str] = None
    project: Optional[str] = None
    host: Optional[str] = None
    user: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)

    # Dependencies
    depends_on: List[str] = field(default_factory=list)
    all_deps: set = field(default_factory=set)

    # Metadata
    logfile: Optional[str] = None
    auto_job: bool = False
    mail_job: bool = False
    isolate: bool = False

    # Backward compatibility
    persist_key: Optional[str] = None
    persist_key_generated: Optional[str] = None

    def __post_init__(self):
        """Post-initialization to set defaults."""
        if self.create_time is None:
            self.create_time = datetime.now(tzutc())

        # Ensure all_deps is a set
        if not isinstance(self.all_deps, set):
            self.all_deps = set(self.all_deps) if self.all_deps else set()

        # Set persist_key_generated if not set
        if self.persist_key_generated is None:
            self.persist_key_generated = self.persist_key or self.key

    def is_active(self) -> bool:
        """Return True if job is not completed."""
        return self.status != JobStatus.COMPLETED

    def is_running(self) -> bool:
        """Return True if job is currently running."""
        return self.status == JobStatus.RUNNING

    def is_blocked(self) -> bool:
        """Return True if job is blocked."""
        return self.status == JobStatus.BLOCKED or self.blocked

    def duration_seconds(self) -> Optional[float]:
        """
        Return duration in seconds.

        Returns None if job hasn't started yet.
        """
        if not self.start_time:
            return None
        end = self.stop_time or datetime.now(tzutc())
        return (end - self.start_time).total_seconds()

    def duration_str(self) -> str:
        """
        Return human-readable duration string.

        Returns "Blocked" if job hasn't started.
        """
        if not self.start_time:
            return "Blocked"

        duration = self.duration_seconds()
        if duration is None:
            return "Blocked"

        # Format as HH:MM:SS
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"

    def cmd_str(self) -> str:
        """Return command string for display."""
        if self.reminder is not None:
            return self.reminder

        if not self.cmd:
            return ""

        # Use shlex.quote for each argument
        cmd_parts = [quote(part) for part in self.cmd]
        return " ".join(cmd_parts)

    def state_str(self) -> str:
        """Return human-readable state string."""
        if self.blocked or self.status == JobStatus.BLOCKED:
            return "Blocked"
        elif self.status == JobStatus.COMPLETED:
            # Special statuses from utils
            special_status = {
                utils.STOP_STOP: "Stopped with --stop",
                utils.STOP_DONE: "Completed Reminder",
                utils.STOP_ABORT: "Interrupted",
                utils.STOP_DEPFAIL: "Dependent Job Failed",
            }
            if self.rc in special_status:
                return f"Finished ({special_status[self.rc]})"
            return "Finished"
        elif self.status == JobStatus.RUNNING:
            return "Running"
        elif self.status == JobStatus.PENDING:
            return "Pending"
        else:
            return str(self.status.value)

    def __str__(self) -> str:
        """Return string representation for display."""
        rc_str = ""
        if self.stop_time and self.rc is not None:
            rc_str = f"rc={self.rc:<3d} "

        cmd_str = self.cmd_str()
        if self.reminder is not None:
            cmd_str = f"Reminder: {self.reminder}"

        return f"{self.duration_str()} {rc_str}[{self.key}] {cmd_str}"

    def __lt__(self, other: Job) -> bool:
        """
        Compare jobs for sorting.

        Active jobs (not completed) sorted by:
        1. Create time
        2. Start time
        3. Stop time
        4. Persist key
        5. Command

        Completed jobs sorted by:
        1. Stop time
        2. Start time
        3. Create time
        4. Persist key
        5. Command
        """
        if not isinstance(other, Job):
            return NotImplemented

        def cmp_optional(a, b, default_a=None, default_b=None):
            """Compare optional values."""
            val_a = a if a is not None else default_a
            val_b = b if b is not None else default_b

            if val_a is None and val_b is None:
                return 0
            elif val_a is None:
                return 1
            elif val_b is None:
                return -1
            elif val_a < val_b:
                return -1
            elif val_a > val_b:
                return 1
            else:
                return 0

        # Choose comparison order based on active vs completed
        if self.is_active():
            # Active: create, start, stop
            comparisons = [
                cmp_optional(self.create_time, other.create_time),
                cmp_optional(
                    self.start_time,
                    other.start_time,
                    datetime.now(tzutc()),
                    datetime.now(tzutc()),
                ),
                cmp_optional(self.stop_time, other.stop_time),
            ]
        else:
            # Completed: stop, start, create
            comparisons = [
                cmp_optional(self.stop_time, other.stop_time),
                cmp_optional(self.start_time, other.start_time),
                cmp_optional(self.create_time, other.create_time),
            ]

        for cmp_result in comparisons:
            if cmp_result != 0:
                return cmp_result < 0

        # Tie-breakers
        if self.persist_key_generated != other.persist_key_generated:
            return self.persist_key_generated < other.persist_key_generated

        return self.cmd_str() < other.cmd_str()

    def __eq__(self, other: object) -> bool:
        """Check equality based on key."""
        if not isinstance(other, Job):
            return NotImplemented
        return self.key == other.key

    def __hash__(self) -> int:
        """Hash based on key."""
        return hash(self.key)
