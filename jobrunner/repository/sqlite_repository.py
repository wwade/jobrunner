"""
SQLite implementation of the job repository.

This module provides a concrete implementation of JobRepository using
SQLite with a proper relational schema and indices for performance.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
import sqlite3
from typing import List, Optional, Tuple

from jobrunner import timing
from jobrunner.domain import Job, JobStatus

from .interface import JobRepository, Metadata

LOG = logging.getLogger(__name__)

# Schema version for this implementation
SCHEMA_VERSION = "3"


class SqliteJobRepository(JobRepository):  # pylint: disable=too-many-public-methods
    """
    SQLite-based job repository with relational schema.

    This implementation uses a single table with a status column instead
    of separate active/inactive tables. It includes proper indices for
    efficient querying.
    """

    def __init__(self, db_path: str):
        """
        Initialize repository.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._debug_sql = LOG.isEnabledFor(logging.DEBUG)
        self._ensure_db_dir()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    def _ensure_db_dir(self):
        """Create database directory if it doesn't exist."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection, creating if needed."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _execute(self, cursor, query: str, params=None):
        if self._debug_sql:
            LOG.debug("query=%r params=%r", query.strip(), params)

        with timing.timed_section("sql.execute"):
            return cursor.execute(query, params) if params else cursor.execute(query)

    def _init_schema(self):
        """Create database schema if it doesn't exist."""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Fast path: Check if schema already exists with correct version
        # This avoids running all the CREATE statements on every startup
        try:
            self._execute(
                cursor, "SELECT value FROM metadata WHERE key = 'schema_version'"
            )
            row = cursor.fetchone()
            if row and row[0] == SCHEMA_VERSION:
                # Schema exists and is current version, skip initialization
                return
        except sqlite3.OperationalError:
            # metadata table doesn't exist yet, need full initialization
            pass

        # Slow path: Create schema (only runs on first use or version upgrade)
        # Main jobs table
        self._execute(
            cursor,
            """
            CREATE TABLE IF NOT EXISTS jobs (
                key TEXT PRIMARY KEY,
                uidx INTEGER NOT NULL,
                prog TEXT,
                args_json TEXT,
                cmd_json TEXT,
                reminder TEXT,
                pwd TEXT,
                create_time TEXT NOT NULL,
                start_time TEXT,
                stop_time TEXT,
                status TEXT NOT NULL,
                rc INTEGER,
                pid INTEGER,
                blocked INTEGER DEFAULT 0,
                workspace TEXT,
                project TEXT,
                host TEXT,
                user TEXT,
                env_json TEXT,
                depends_on_json TEXT,
                logfile TEXT,
                auto_job INTEGER DEFAULT 0,
                mail_job INTEGER DEFAULT 0,
                isolate INTEGER DEFAULT 0,
                persist_key TEXT,
                persist_key_generated TEXT
            )
        """,
        )

        # Indices for fast queries
        self._execute(
            cursor, "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)"
        )
        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_jobs_workspace ON jobs(workspace)",
        )
        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_jobs_create_time ON jobs(create_time)",
        )
        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_jobs_stop_time ON jobs(stop_time)",
        )
        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_workspace "
            "ON jobs(status, workspace)",
        )
        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_create "
            "ON jobs(status, create_time)",
        )
        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_stop "
            "ON jobs(status, stop_time)",
        )

        # Metadata table
        self._execute(
            cursor,
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """,
        )

        # Sequence tables for recording and replaying job sequences
        self._execute(
            cursor,
            """
            CREATE TABLE IF NOT EXISTS sequence_steps (
                name TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                job_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (name, step_number)
            )
        """,
        )

        self._execute(
            cursor,
            """
            CREATE TABLE IF NOT EXISTS sequence_dependencies (
                name TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                dependency_step INTEGER NOT NULL,
                dependency_type TEXT NOT NULL,
                PRIMARY KEY (name, step_number, dependency_step),
                FOREIGN KEY (name, step_number)
                    REFERENCES sequence_steps(name, step_number)
            )
        """,
        )

        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_sequence_steps_name "
            "ON sequence_steps(name)",
        )

        self._execute(
            cursor,
            "CREATE INDEX IF NOT EXISTS idx_sequence_steps_name_step "
            "ON sequence_steps(name, step_number)",
        )

        # Initialize metadata if not present
        self._execute(
            cursor, "SELECT COUNT(*) FROM metadata WHERE key = 'schema_version'"
        )
        if cursor.fetchone()[0] == 0:
            self._init_metadata(cursor)

        conn.commit()

    def _init_metadata(self, cursor):
        """Initialize metadata with default values."""
        self._execute(
            cursor,
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        self._execute(
            cursor,
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("last_key", ""),
        )
        self._execute(
            cursor,
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("last_job", ""),
        )
        self._execute(
            cursor,
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("checkpoint", ""),
        )
        self._execute(
            cursor,
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("recent_keys", "[]"),
        )
        self._execute(
            cursor,
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("current_index", "0"),
        )

    def _job_to_row(self, job: Job) -> tuple:
        """Convert Job to database row tuple."""
        return (
            job.key,
            job.uidx,
            job.prog,
            json.dumps(job.args) if job.args else None,
            json.dumps(job.cmd) if job.cmd else None,
            job.reminder,
            job.pwd,
            job.create_time.isoformat() if job.create_time else None,
            job.start_time.isoformat() if job.start_time else None,
            job.stop_time.isoformat() if job.stop_time else None,
            job.status.value,
            job.rc,
            job.pid,
            int(job.blocked),
            job.workspace,
            job.project,
            job.host,
            job.user,
            json.dumps(job.env) if job.env else "{}",
            json.dumps(job.depends_on) if job.depends_on else "[]",
            job.logfile,
            int(job.auto_job),
            int(job.mail_job),
            int(job.isolate),
            job.persist_key,
            job.persist_key_generated,
        )

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Convert database row to Job object."""
        # Parse depends_on and derive all_deps from it
        depends_on = (
            json.loads(row["depends_on_json"]) if row["depends_on_json"] else []
        )
        all_deps = set(depends_on) if depends_on else set()

        return Job(
            key=row["key"],
            uidx=row["uidx"],
            prog=row["prog"],
            args=json.loads(row["args_json"]) if row["args_json"] else None,
            cmd=json.loads(row["cmd_json"]) if row["cmd_json"] else None,
            reminder=row["reminder"],
            pwd=row["pwd"],
            create_time=(
                datetime.fromisoformat(row["create_time"])
                if row["create_time"]
                else None
            ),
            start_time=(
                datetime.fromisoformat(row["start_time"])
                if row["start_time"]
                else None
            ),
            stop_time=(
                datetime.fromisoformat(row["stop_time"])
                if row["stop_time"]
                else None
            ),
            status=JobStatus(row["status"]),
            rc=row["rc"],
            pid=row["pid"],
            blocked=bool(row["blocked"]),
            workspace=row["workspace"],
            project=row["project"],
            host=row["host"],
            user=row["user"],
            env=json.loads(row["env_json"]) if row["env_json"] else {},
            depends_on=depends_on,
            all_deps=all_deps,
            logfile=row["logfile"],
            auto_job=bool(row["auto_job"]),
            mail_job=bool(row["mail_job"]),
            isolate=bool(row["isolate"]),
            persist_key=row["persist_key"],
            persist_key_generated=row["persist_key_generated"],
        )

    def _row_to_job_minimal(self, row: sqlite3.Row) -> Job:
        """
        Convert database row to minimal Job object for listing.

        This skips expensive JSON parsing for fields not needed when displaying
        jobs (args_json, env_json, depends_on_json) and sets other unused
        fields to default values.

        Used by find_completed(for_listing=True) to optimize job -L performance.
        """
        return Job(
            key=row["key"],
            uidx=row["uidx"],
            prog=None,  # Not needed for listing
            args=None,  # Not needed (cmd is sufficient)
            cmd=json.loads(row["cmd_json"]) if row["cmd_json"] else None,
            reminder=row["reminder"],
            pwd=None,  # Not needed for listing
            create_time=(
                datetime.fromisoformat(row["create_time"])
                if row["create_time"]
                else None
            ),
            start_time=(
                datetime.fromisoformat(row["start_time"])
                if row["start_time"]
                else None
            ),
            stop_time=(
                datetime.fromisoformat(row["stop_time"])
                if row["stop_time"]
                else None
            ),
            status=JobStatus(row["status"]),
            rc=row["rc"],
            pid=None,  # Not needed for listing
            blocked=False,  # Not needed for listing
            workspace=None,  # Not needed for listing
            project=None,  # Not needed for listing
            host=None,  # Not needed for listing
            user=None,  # Not needed for listing
            env={},  # Skip expensive JSON parse
            depends_on=[],  # Skip expensive JSON parse
            all_deps=set(),  # Skip expensive JSON parse
            logfile=None,  # Not needed for listing
            auto_job=False,  # Not needed for listing
            mail_job=False,  # Not needed for listing
            isolate=False,  # Not needed for listing
            persist_key=None,  # Not needed for listing
            persist_key_generated=None,  # Not needed for listing
        )

    @timing.timed_function
    def save(self, job: Job) -> None:
        """Save or update a job."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(
            cursor,
            """
            INSERT OR REPLACE INTO jobs (
                key, uidx, prog, args_json, cmd_json, reminder, pwd,
                create_time, start_time, stop_time, status, rc, pid, blocked,
                workspace, project, host, user, env_json, depends_on_json,
                logfile, auto_job, mail_job, isolate,
                persist_key, persist_key_generated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?)
        """,
            self._job_to_row(job),
        )

        conn.commit()

        # Update recent keys if this is a new job or status changed to completed
        if job.status == JobStatus.COMPLETED and not job.auto_job:
            self._add_to_recent(job.key)

    @timing.timed_function
    def get(self, key: str) -> Optional[Job]:
        """Get a job by key."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(cursor, "SELECT * FROM jobs WHERE key = ?", (key,))
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_job(row)

    @timing.timed_function
    def get_many(self, keys: List[str]) -> dict[str, Job]:
        """Bulk fetch multiple jobs by keys in a single query."""
        if not keys:
            return {}
        conn = self._get_conn()
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(keys))
        query = f"SELECT * FROM jobs WHERE key IN ({placeholders})"
        self._execute(cursor, query, keys)
        return {row[0]: self._row_to_job(row) for row in cursor.fetchall()}

    @timing.timed_function
    def delete(self, key: str) -> None:
        """Delete a job by key."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(cursor, "DELETE FROM jobs WHERE key = ?", (key,))
        conn.commit()

        # Remove from recent keys
        self._remove_from_recent(key)

    @timing.timed_function
    def exists(self, key: str) -> bool:
        """Check if a job exists."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(cursor, "SELECT 1 FROM jobs WHERE key = ? LIMIT 1", (key,))
        return cursor.fetchone() is not None

    @timing.timed_function
    def find_all(
        self,
        status: Optional[JobStatus] = None,
        workspace: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """Find jobs matching criteria."""
        conn = self._get_conn()
        cursor = conn.cursor()

        query = "SELECT * FROM jobs WHERE 1=1"
        params = []

        if status is not None:
            query += " AND status = ?"
            params.append(status.value)

        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)

        if since is not None:
            query += " AND create_time >= ?"
            params.append(since.isoformat())

        query += " ORDER BY create_time"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        self._execute(cursor, query, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

    @timing.timed_function
    def find_active(self, workspace: Optional[str] = None) -> List[Job]:
        """Get all non-completed jobs."""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Use IN instead of != for better index usage
        query = "SELECT * FROM jobs WHERE status IN (?, ?, ?)"
        params = [
            JobStatus.PENDING.value,
            JobStatus.BLOCKED.value,
            JobStatus.RUNNING.value,
        ]

        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)

        query += " ORDER BY create_time"

        self._execute(cursor, query, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

    @timing.timed_function
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
        conn = self._get_conn()
        cursor = conn.cursor()

        # When listing, only select columns needed for display to avoid
        # expensive JSON parsing of args_json, env_json, depends_on_json
        if for_listing:
            query = """
                SELECT key, uidx, create_time, start_time, stop_time,
                       status, rc, cmd_json, reminder
                FROM jobs WHERE status = ?
            """
        else:
            query = "SELECT * FROM jobs WHERE status = ?"

        params = [JobStatus.COMPLETED.value]

        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)

        query += " ORDER BY stop_time DESC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        self._execute(cursor, query, params)

        # Use minimal conversion when listing to skip expensive JSON parsing
        if for_listing:
            return [self._row_to_job_minimal(row) for row in cursor.fetchall()]
        return [self._row_to_job(row) for row in cursor.fetchall()]

    @timing.timed_function
    def find_latest(
        self,
        exclude_completed: bool = False,
        workspace: Optional[str] = None,
        skip_reminders: bool = False,
        skip_mail_jobs: bool = False,
    ) -> Optional[Job]:
        """
        Find the most recent job matching criteria.

        This is optimized to use SQL LIMIT 1 instead of loading all jobs.

        Args:
            exclude_completed: If True, only search non-completed jobs
            workspace: Optional workspace filter
            skip_reminders: If True, exclude reminder jobs
            skip_mail_jobs: If True, exclude mail jobs

        Returns:
            Most recent Job matching criteria, or None if no matches
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        query = "SELECT * FROM jobs WHERE 1=1"
        params = []

        if exclude_completed:
            # Use IN instead of != for better index usage
            query += " AND status IN (?, ?, ?)"
            params.extend(
                [
                    JobStatus.PENDING.value,
                    JobStatus.BLOCKED.value,
                    JobStatus.RUNNING.value,
                ]
            )

        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)

        if skip_reminders:
            query += " AND (reminder IS NULL OR reminder = '')"

        if skip_mail_jobs:
            query += " AND mail_job = 0"

        query += " ORDER BY create_time DESC LIMIT 1"

        self._execute(cursor, query, params)
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_job(row)

    @timing.timed_function
    def get_keys(
        self,
        status: Optional[JobStatus] = None,
        exclude_completed: bool = False,
    ) -> List[str]:
        """Get job keys efficiently without loading full job objects."""
        conn = self._get_conn()
        cursor = conn.cursor()
        query = "SELECT key FROM jobs WHERE 1=1"
        params = []
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        elif exclude_completed:
            # Use IN instead of != for better index usage
            query += " AND status IN (?, ?, ?)"
            params.extend(
                [
                    JobStatus.PENDING.value,
                    JobStatus.BLOCKED.value,
                    JobStatus.RUNNING.value,
                ]
            )
        query += " ORDER BY create_time"
        self._execute(cursor, query, params)
        return [row[0] for row in cursor.fetchall()]

    @timing.timed_function
    def search_by_command(
        self,
        query: str,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """Search jobs by command string."""
        conn = self._get_conn()
        cursor = conn.cursor()

        sql = "SELECT * FROM jobs WHERE cmd_json LIKE ? ORDER BY create_time DESC"
        params = [f"%{query}%"]

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        self._execute(cursor, sql, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

    @timing.timed_function
    def find_matching(
        self,
        keyword: str,
        workspace: Optional[str] = None,
        skip_reminders: bool = False,
        since: Optional[datetime] = None,
    ) -> List[Job]:
        """
        Find all jobs matching the given keyword.

        Searches for jobs where the keyword appears in:
        - The command string (cmd_json)
        - The job key

        Args:
            keyword: Search term to match
            workspace: Optional workspace filter
            skip_reminders: If True, exclude reminder jobs
            since: Optional checkpoint datetime to filter jobs created after

        Returns:
            List of matching Job objects, with inactive jobs first
            (oldest to newest), then active jobs (oldest to newest)
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Build SQL query
        sql = """
            SELECT * FROM jobs
            WHERE (cmd_json LIKE ? OR key LIKE ?)
            AND mail_job = 0
        """
        params = [f"%{keyword}%", f"{keyword}%"]

        if workspace is not None:
            sql += " AND workspace = ?"
            params.append(workspace)

        if skip_reminders:
            sql += " AND (reminder IS NULL OR reminder = '')"

        if since is not None:
            sql += " AND create_time >= ?"
            params.append(since.isoformat())

        # Order by: completed jobs first (by stop_time), then active jobs
        # (by create_time), both oldest to newest
        sql += """
            ORDER BY
                CASE WHEN status = 'completed'
                    THEN 0 ELSE 1 END,
                CASE WHEN status = 'completed'
                    THEN stop_time ELSE create_time END ASC
        """

        self._execute(cursor, sql, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

    @timing.timed_function
    def get_metadata(self) -> Metadata:
        """Get repository metadata."""
        conn = self._get_conn()
        cursor = conn.cursor()

        def get_meta(key: str, default: str = "") -> str:
            self._execute(cursor, "SELECT value FROM metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

        schema_version = get_meta("schema_version", SCHEMA_VERSION)
        last_key = get_meta("last_key", "")
        last_job = get_meta("last_job", "")
        checkpoint_str = get_meta("checkpoint", "")
        recent_json = get_meta("recent_keys", "[]")

        checkpoint = None
        if checkpoint_str:
            try:
                checkpoint = datetime.fromisoformat(checkpoint_str)
            except (ValueError, AttributeError):
                pass

        recent_keys = json.loads(recent_json) if recent_json else []

        return Metadata(
            schema_version=schema_version,
            last_key=last_key,
            last_job=last_job,
            checkpoint=checkpoint,
            recent_keys=recent_keys,
        )

    @timing.timed_function
    def update_metadata(self, metadata: Metadata) -> None:
        """Update repository metadata."""
        conn = self._get_conn()
        cursor = conn.cursor()

        def set_meta(key: str, value: str):
            self._execute(
                cursor,
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )

        set_meta("schema_version", metadata.schema_version)
        set_meta("last_key", metadata.last_key)
        set_meta("last_job", metadata.last_job)
        set_meta(
            "checkpoint",
            metadata.checkpoint.isoformat() if metadata.checkpoint else "",
        )
        set_meta("recent_keys", json.dumps(metadata.recent_keys))

        conn.commit()

    @timing.timed_function
    def next_uidx(self) -> int:
        """Get next unique index and increment counter."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(
            cursor, "SELECT value FROM metadata WHERE key = 'current_index'"
        )
        row = cursor.fetchone()
        current = int(row[0]) if row else 0

        self._execute(
            cursor,
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("current_index", str(current + 1)),
        )

        conn.commit()
        return current

    @timing.timed_function
    def count(self, status: Optional[JobStatus] = None) -> int:
        """Count jobs."""
        conn = self._get_conn()
        cursor = conn.cursor()

        if status is None:
            self._execute(cursor, "SELECT COUNT(*) FROM jobs")
        else:
            self._execute(
                cursor, "SELECT COUNT(*) FROM jobs WHERE status = ?", (status.value,)
            )

        row = cursor.fetchone()
        return row[0] if row else 0

    def _add_to_recent(self, key: str) -> None:
        """Add key to recent list."""
        metadata = self.get_metadata()
        recent = metadata.recent_keys

        # Remove if already present
        if key in recent:
            recent.remove(key)

        # Add to front
        recent.insert(0, key)

        # Trim to 100 items
        if len(recent) > 100:
            recent = recent[:100]

        metadata.recent_keys = recent
        self.update_metadata(metadata)

    def _remove_from_recent(self, key: str) -> None:
        """Remove key from recent list."""
        metadata = self.get_metadata()
        if key in metadata.recent_keys:
            metadata.recent_keys.remove(key)
            self.update_metadata(metadata)

    @timing.timed_function
    def is_sequence(self, name: str) -> bool:
        """Check if a name refers to a sequence."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(
            cursor, "SELECT 1 FROM sequence_steps WHERE name = ? LIMIT 1", (name,)
        )
        return cursor.fetchone() is not None

    @timing.timed_function
    def add_sequence_step(
        self,
        name: str,
        job_key: str,
        dependencies: List[Tuple[int, str]],
    ) -> int:
        """
        Add a step to a sequence.

        Args:
            name: Sequence name
            job_key: Key of the job for this step
            dependencies: List of (step_number, dep_type) tuples where
                         dep_type is 'success' or 'completion'

        Returns:
            The step number assigned to this step
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get next step number for this sequence
        self._execute(
            cursor,
            "SELECT MAX(step_number) FROM sequence_steps WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        next_step = 0 if row[0] is None else row[0] + 1

        # Insert step
        created_at = datetime.now().isoformat()
        self._execute(
            cursor,
            "INSERT INTO sequence_steps "
            "(name, step_number, job_key, created_at) "
            "VALUES (?, ?, ?, ?)",
            (name, next_step, job_key, created_at),
        )

        # Insert dependencies
        for dep_step, dep_type in dependencies:
            self._execute(
                cursor,
                "INSERT INTO sequence_dependencies "
                "(name, step_number, dependency_step, "
                "dependency_type) "
                "VALUES (?, ?, ?, ?)",
                (name, next_step, dep_step, dep_type),
            )

        conn.commit()
        return next_step

    @timing.timed_function
    def get_sequence_steps(
        self, name: str
    ) -> List[Tuple[int, str, List[Tuple[int, str]]]]:
        """
        Get all steps in a sequence with their dependencies.

        Args:
            name: Sequence name

        Returns:
            List of (step_number, job_key, dependencies) tuples where
            dependencies is a list of (dependency_step, dependency_type)
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get all steps
        self._execute(
            cursor,
            "SELECT step_number, job_key "
            "FROM sequence_steps WHERE name = ? "
            "ORDER BY step_number",
            (name,),
        )
        steps = cursor.fetchall()

        result = []
        for step_num, job_key in steps:
            # Get dependencies for this step
            self._execute(
                cursor,
                "SELECT dependency_step, dependency_type "
                "FROM sequence_dependencies "
                "WHERE name = ? AND step_number = ?",
                (name, step_num),
            )
            deps = [(row[0], row[1]) for row in cursor.fetchall()]
            result.append((step_num, job_key, deps))

        return result

    @timing.timed_function
    def list_sequences(self) -> List[str]:
        """List all sequence names."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(
            cursor, "SELECT DISTINCT name FROM sequence_steps ORDER BY name"
        )
        return [row[0] for row in cursor.fetchall()]

    @timing.timed_function
    def delete_sequence(self, name: str) -> None:
        """Delete a sequence and all its steps."""
        conn = self._get_conn()
        cursor = conn.cursor()

        self._execute(
            cursor, "DELETE FROM sequence_dependencies WHERE name = ?", (name,)
        )
        self._execute(cursor, "DELETE FROM sequence_steps WHERE name = ?", (name,))

        conn.commit()

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
