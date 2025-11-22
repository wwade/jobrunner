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
from typing import List, Optional

from jobrunner.domain import Job, JobStatus

from .interface import JobRepository, Metadata

LOG = logging.getLogger(__name__)

# Schema version for this implementation
SCHEMA_VERSION = "2"


class SqliteJobRepository(JobRepository):
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

    def _init_schema(self):
        """Create database schema if it doesn't exist."""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Main jobs table
        cursor.execute("""
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
                all_deps_json TEXT,
                logfile TEXT,
                auto_job INTEGER DEFAULT 0,
                mail_job INTEGER DEFAULT 0,
                isolate INTEGER DEFAULT 0,
                persist_key TEXT,
                persist_key_generated TEXT
            )
        """)

        # Indices for fast queries
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status "
            "ON jobs(status)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_workspace "
            "ON jobs(workspace)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_create_time "
            "ON jobs(create_time)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_stop_time "
            "ON jobs(stop_time)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_workspace "
            "ON jobs(status, workspace)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_create "
            "ON jobs(status, create_time)")

        # Metadata table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Initialize metadata if not present
        cursor.execute("SELECT COUNT(*) FROM metadata WHERE key = 'schema_version'")
        if cursor.fetchone()[0] == 0:
            self._init_metadata(cursor)

        conn.commit()

    def _init_metadata(self, cursor):
        """Initialize metadata with default values."""
        cursor.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION))
        cursor.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("last_key", ""))
        cursor.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("last_job", ""))
        cursor.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("checkpoint", ""))
        cursor.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("recent_keys", "[]"))
        cursor.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("current_index", "0"))

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
            json.dumps(list(job.all_deps)) if job.all_deps else "[]",
            job.logfile,
            int(job.auto_job),
            int(job.mail_job),
            int(job.isolate),
            job.persist_key,
            job.persist_key_generated,
        )

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Convert database row to Job object."""
        return Job(
            key=row["key"],
            uidx=row["uidx"],
            prog=row["prog"],
            args=json.loads(row["args_json"]) if row["args_json"] else None,
            cmd=json.loads(row["cmd_json"]) if row["cmd_json"] else None,
            reminder=row["reminder"],
            pwd=row["pwd"],
            create_time=datetime.fromisoformat(row["create_time"])
            if row["create_time"] else None,
            start_time=datetime.fromisoformat(row["start_time"])
            if row["start_time"] else None,
            stop_time=datetime.fromisoformat(row["stop_time"])
            if row["stop_time"] else None,
            status=JobStatus(row["status"]),
            rc=row["rc"],
            pid=row["pid"],
            blocked=bool(row["blocked"]),
            workspace=row["workspace"],
            project=row["project"],
            host=row["host"],
            user=row["user"],
            env=json.loads(row["env_json"]) if row["env_json"] else {},
            depends_on=json.loads(row["depends_on_json"])
            if row["depends_on_json"] else [],
            all_deps=set(json.loads(row["all_deps_json"]))
            if row["all_deps_json"] else set(),
            logfile=row["logfile"],
            auto_job=bool(row["auto_job"]),
            mail_job=bool(row["mail_job"]),
            isolate=bool(row["isolate"]),
            persist_key=row["persist_key"],
            persist_key_generated=row["persist_key_generated"],
        )

    def save(self, job: Job) -> None:
        """Save or update a job."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO jobs (
                key, uidx, prog, args_json, cmd_json, reminder, pwd,
                create_time, start_time, stop_time, status, rc, pid, blocked,
                workspace, project, host, user, env_json, depends_on_json,
                all_deps_json, logfile, auto_job, mail_job, isolate,
                persist_key, persist_key_generated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?)
        """, self._job_to_row(job))

        conn.commit()

        # Update recent keys if this is a new job or status changed to completed
        if job.status == JobStatus.COMPLETED and not job.auto_job:
            self._add_to_recent(job.key)

    def get(self, key: str) -> Optional[Job]:
        """Get a job by key."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM jobs WHERE key = ?", (key,))
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_job(row)

    def delete(self, key: str) -> None:
        """Delete a job by key."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM jobs WHERE key = ?", (key,))
        conn.commit()

        # Remove from recent keys
        self._remove_from_recent(key)

    def exists(self, key: str) -> bool:
        """Check if a job exists."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM jobs WHERE key = ? LIMIT 1", (key,))
        return cursor.fetchone() is not None

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

        cursor.execute(query, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def find_active(self, workspace: Optional[str] = None) -> List[Job]:
        """Get all non-completed jobs."""
        conn = self._get_conn()
        cursor = conn.cursor()

        query = "SELECT * FROM jobs WHERE status != ?"
        params = [JobStatus.COMPLETED.value]

        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)

        query += " ORDER BY create_time"

        cursor.execute(query, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def find_completed(
        self,
        workspace: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """Get completed jobs."""
        conn = self._get_conn()
        cursor = conn.cursor()

        query = "SELECT * FROM jobs WHERE status = ?"
        params = [JobStatus.COMPLETED.value]

        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)

        query += " ORDER BY stop_time DESC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

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

        cursor.execute(sql, params)
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def get_metadata(self) -> Metadata:
        """Get repository metadata."""
        conn = self._get_conn()
        cursor = conn.cursor()

        def get_meta(key: str, default: str = "") -> str:
            cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
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

    def update_metadata(self, metadata: Metadata) -> None:
        """Update repository metadata."""
        conn = self._get_conn()
        cursor = conn.cursor()

        def set_meta(key: str, value: str):
            cursor.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value))

        set_meta("schema_version", metadata.schema_version)
        set_meta("last_key", metadata.last_key)
        set_meta("last_job", metadata.last_job)
        set_meta("checkpoint",
                 metadata.checkpoint.isoformat() if metadata.checkpoint else "")
        set_meta("recent_keys", json.dumps(metadata.recent_keys))

        conn.commit()

    def next_uidx(self) -> int:
        """Get next unique index and increment counter."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM metadata WHERE key = 'current_index'")
        row = cursor.fetchone()
        current = int(row[0]) if row else 0

        cursor.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("current_index", str(current + 1)))

        conn.commit()
        return current

    def count(self, status: Optional[JobStatus] = None) -> int:
        """Count jobs."""
        conn = self._get_conn()
        cursor = conn.cursor()

        if status is None:
            cursor.execute("SELECT COUNT(*) FROM jobs")
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?",
                (status.value,))

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

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
