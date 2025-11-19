"""
Improved relational database implementation for jobrunner.

This module provides a properly normalized SQLite schema with indices for
efficient querying, while maintaining backward compatibility with the old
key-value store format.

Key improvements:
- Proper relational schema with normalized tables
- Indices on frequently queried columns (workspace, timestamps, status)
- Efficient SQL queries instead of full table scans
- Migration support from old key-value format
- Better query performance for large job databases
"""

from __future__ import annotations

from datetime import datetime
import json
from logging import getLogger
import os
import sqlite3

from . import DatabaseBase, DatabaseMeta, JobsBase, resolveDbFile
from ..info import JobInfo, decodeJobInfo

LOG = getLogger(__name__)

# Schema version for the new relational format
SCHEMA_VERSION = "1"


class RelationalDatabase(DatabaseBase):
    """
    Relational database implementation with proper schema and indices.

    Schema:
    - jobs: Main table with all job attributes as columns
    - job_dependencies: Many-to-many table for job dependencies
    - metadata: Key-value table for database metadata
    """

    schemaVersion = SCHEMA_VERSION

    def __init__(self, parent, config, instanceId, status):
        """
        Initialize database for either 'active' or 'inactive' jobs.

        Args:
            parent: Parent JobsBase instance
            config: Configuration object
            instanceId: Unique instance ID
            status: 'active' or 'inactive'
        """
        super(RelationalDatabase, self).__init__(parent, config, instanceId)
        self._conn = None
        self._status = status
        self._locked = False
        self._dirty = 0
        self.ident = status + "Jobs"

    @property
    def db(self):
        """Compatibility property for old-style dict access."""
        return self

    @property
    def conn(self):
        return self._conn

    @conn.setter
    def conn(self, conn):
        self._conn = conn

    @property
    def dirty(self):
        return self._dirty

    def _setDirty(self):
        self._dirty += 1

    def lock(self):
        assert not self._locked
        self._locked = True
        LOG.debug("[%s] locked", self.ident)

    def unlock(self):
        assert self._locked
        self._locked = False
        LOG.debug("[%s] unlocked", self.ident)

    def _execute(self, query, params=()):
        """Execute a query and return cursor."""
        assert self._conn, "Database not connected"
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return cursor

    def _fetchone(self, query, params=()):
        """Execute query and fetch one result."""
        cursor = self._execute(query, params)
        return cursor.fetchone()

    def _fetchall(self, query, params=()):
        """Execute query and fetch all results."""
        cursor = self._execute(query, params)
        return cursor.fetchall()

    def _job_from_row(self, row: tuple) -> JobInfo | None:
        # pylint: disable=too-many-locals,protected-access
        """Convert database row to JobInfo object."""
        if not row:
            return None

        # Reconstruct JobInfo from row
        # Row columns match the SELECT order in _get_job_query()
        (_job_id, key, persist_key, uidx, prog, args_json, cmd_json,
         reminder, pwd, auto_job, mail_job, isolate, create_time,
         start_time, stop_time, rc, pid, blocked, logfile, host,
         user, workspace, proj, env_json, _status) = row

        # Create JobInfo instance
        job = JobInfo(uidx, key=key)
        job._persistKey = persist_key
        job._persistKeyGenerated = persist_key or key
        job.prog = prog
        job.args = json.loads(args_json) if args_json else None
        job._cmd = json.loads(cmd_json) if cmd_json else None
        job.reminder = reminder
        job.pwd = pwd
        job._autoJob = bool(auto_job)
        job._mailJob = bool(mail_job)
        job._isolate = bool(isolate)
        # Deserialize datetime from ISO 8601 format
        job._create = datetime.fromisoformat(create_time) if create_time else None
        job._start = datetime.fromisoformat(start_time) if start_time else None
        job._stop = datetime.fromisoformat(stop_time) if stop_time else None
        job._rc = rc
        job.pid = pid
        job._blocked = bool(blocked)
        job.logfile = logfile
        job._host = host
        job._user = user
        job._workspace = workspace
        job._proj = proj
        job._env = json.loads(env_json) if env_json else {}
        job.parent = self._parent

        # Load dependencies
        deps = self._fetchall(
            "SELECT depends_on_key FROM job_dependencies WHERE job_key = ?",
            (key,))
        if deps:
            job._depends = [d[0] for d in deps]
            job._alldeps = set(job._depends)
        else:
            job._depends = None
            job._alldeps = set()

        return job

    def _get_job_query(self):
        """Return SELECT query for retrieving jobs."""
        return """
            SELECT id, key, persist_key, uidx, prog, args, cmd, reminder,
                   pwd, auto_job, mail_job, isolate, create_time, start_time,
                   stop_time, rc, pid, blocked, logfile, host, user,
                   workspace, proj, env, status
            FROM jobs
            WHERE status = ?
        """

    def keys(self):
        """Return list of all job keys for this status."""
        rows = self._fetchall(
            "SELECT key FROM jobs WHERE status = ? ORDER BY create_time",
            (self._status,))
        return [r[0] for r in rows]

    def __len__(self):
        """Return count of jobs with this status."""
        row = self._fetchone(
            "SELECT COUNT(*) FROM jobs WHERE status = ?",
            (self._status,))
        return row[0] if row else 0

    def __bool__(self):
        """Always return True for truthiness checks (avoid calling __len__)."""
        return True

    def __contains__(self, key):
        """Check if job key exists."""
        row = self._fetchone(
            "SELECT 1 FROM jobs WHERE key = ? AND status = ? LIMIT 1",
            (key, self._status))
        return row is not None

    def __getitem__(self, key):
        """Get job by key."""
        # Handle special metadata keys
        if key in self.special:
            if key == self.SV:
                return self.schemaVersion
            # Get other metadata
            value = self._get_metadata(key)
            if value is None:
                raise KeyError(key)
            return value

        row = self._fetchone(
            self._get_job_query() + " AND key = ?",
            (self._status, key))
        if not row:
            raise KeyError(key)
        return self._job_from_row(row)

    def __setitem__(self, key, value):
        """Set or update job."""
        # Handle special metadata keys
        if key in self.special:
            if key == self.SV:
                # Ignore schema version sets (handled by setup)
                return
            # Store other metadata
            self._set_metadata(key, value)
            return

        if not isinstance(value, JobInfo):
            raise ValueError("Can only store JobInfo objects")

        job = value

        # Check if job exists
        existing = self._fetchone(
            "SELECT id FROM jobs WHERE key = ?", (key,))

        # Prepare job data
        args_json = json.dumps(job.args) if job.args else None
        cmd_json = json.dumps(job.cmd) if job._cmd else None
        env_json = json.dumps(job.environ) if job.environ else None
        # Store timestamps in ISO 8601 format
        create_time_str = job._create.isoformat() if job._create else None
        start_time_str = job._start.isoformat() if job._start else None
        stop_time_str = job._stop.isoformat() if job._stop else None

        if existing:
            # Update existing job
            self._execute("""
                UPDATE jobs SET
                    persist_key = ?, uidx = ?, prog = ?, args = ?, cmd = ?,
                    reminder = ?, pwd = ?, auto_job = ?, mail_job = ?,
                    isolate = ?, create_time = ?, start_time = ?, stop_time = ?,
                    rc = ?, pid = ?, blocked = ?, logfile = ?, host = ?,
                    user = ?, workspace = ?, proj = ?, env = ?, status = ?
                WHERE key = ?
            """, (
                job._persistKeyGenerated, job._uidx, job.prog, args_json,
                cmd_json, job.reminder, job.pwd, int(job.autoJob or 0),
                int(job.mailJob or 0), int(job.isolate or 0), create_time_str,
                start_time_str, stop_time_str, job._rc, job.pid,
                int(job._blocked or 0), job.logfile, job._host, job._user,
                job.workspace, job.proj, env_json, self._status, key
            ))
        else:
            # Insert new job
            self._execute("""
                INSERT INTO jobs (
                    key, persist_key, uidx, prog, args, cmd, reminder, pwd,
                    auto_job, mail_job, isolate, create_time, start_time,
                    stop_time, rc, pid, blocked, logfile, host, user,
                    workspace, proj, env, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?)
            """, (
                key, job._persistKeyGenerated, job._uidx, job.prog, args_json,
                cmd_json, job.reminder, job.pwd, int(job.autoJob or 0),
                int(job.mailJob or 0), int(job.isolate or 0), create_time_str,
                start_time_str, stop_time_str, job._rc, job.pid,
                int(job._blocked or 0), job.logfile, job._host, job._user,
                job.workspace, job.proj, env_json, self._status
            ))

        # Update dependencies
        self._execute("DELETE FROM job_dependencies WHERE job_key = ?", (key,))
        if job._depends:
            for dep_key in job._depends:
                self._execute(
                    "INSERT INTO job_dependencies (job_key, depends_on_key) "
                    "VALUES (?, ?)",
                    (key, dep_key))

        # Update recent list if this is a new job
        if not existing:
            self.recent = key

        self._setDirty()

    def __delitem__(self, key):
        """Delete job by key."""
        self._execute("DELETE FROM job_dependencies WHERE job_key = ?", (key,))
        self._execute(
            "DELETE FROM jobs WHERE key = ? AND status = ?",
            (key, self._status))
        self._setDirty()

        # Update recent list
        recent = self.recent
        if recent and key in recent:
            recent.remove(key)
            self._set_metadata(self.RECENT, json.dumps(recent))

    def uidx(self):
        """Get and increment unique index counter."""
        cur = self._get_metadata(self.IDX, 0)
        if isinstance(cur, str):
            cur = int(cur)
        self._set_metadata(self.IDX, str(cur + 1))
        return cur

    def _get_metadata(self, key, default=None):
        """Get metadata value."""
        row = self._fetchone(
            "SELECT value FROM metadata WHERE key = ?", (key,))
        if row:
            try:
                return json.loads(row[0])
            except (json.JSONDecodeError, ValueError):
                return row[0]
        return default

    def _set_metadata(self, key, value):
        """Set metadata value."""
        if not isinstance(value, str):
            value = json.dumps(value)
        self._execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value))
        self._setDirty()

    @property
    def recent(self) -> list[str]:
        """Get list of recent job keys."""
        if r := self._get_metadata(self.RECENT):
            return r
        return []

    @recent.setter
    def recent(self, key):
        """Add key to recent list."""
        recent_list = self.recent
        if key in recent_list:
            recent_list.remove(key)
        recent_list.insert(0, key)
        if len(recent_list) > 100:  # NUM_RECENT from original
            recent_list = recent_list[:100]
        self._set_metadata(self.RECENT, recent_list)

    def get_jobs_by_workspace(self, workspace: str) -> list[JobInfo]:
        """Efficiently get all jobs for a workspace using index."""
        rows = self._fetchall(
            self._get_job_query() + " AND workspace = ? ORDER BY create_time",
            (self._status, workspace))
        return [job for r in rows if (job := self._job_from_row(r)) is not None]

    def get_jobs_since(self, since: datetime) -> list[JobInfo]:
        """Efficiently get jobs created after a timestamp using index."""
        since_str = since.isoformat()
        rows = self._fetchall(
            self._get_job_query() + " AND create_time > ? ORDER BY create_time",
            (self._status, since_str))
        return [job for r in rows if (job := self._job_from_row(r)) is not None]

    def search_by_command(self, search: str) -> list[JobInfo]:
        """Search jobs by command string."""
        rows = self._fetchall(
            self._get_job_query() + " AND cmd LIKE ? ORDER BY create_time DESC",
            (self._status, f"%{search}%"))
        return [job for r in rows if (job := self._job_from_row(r)) is not None]


def createSchema(conn):
    """Create the database schema with proper indices."""
    cursor = conn.cursor()

    # Main jobs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            persist_key TEXT,
            uidx INTEGER NOT NULL,
            prog TEXT,
            args TEXT,
            cmd TEXT,
            reminder TEXT,
            pwd TEXT,
            auto_job INTEGER DEFAULT 0,
            mail_job INTEGER DEFAULT 0,
            isolate INTEGER DEFAULT 0,
            create_time TEXT,
            start_time TEXT,
            stop_time TEXT,
            rc INTEGER,
            pid INTEGER,
            blocked INTEGER DEFAULT 0,
            logfile TEXT,
            host TEXT,
            user TEXT,
            workspace TEXT,
            proj TEXT,
            env TEXT,
            status TEXT NOT NULL
        )
    """)

    # Indices for efficient queries
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_key ON jobs(key)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_workspace ON jobs(workspace)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_create_time ON jobs(create_time)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_stop_time ON jobs(stop_time)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_status_workspace "
        "ON jobs(status, workspace)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_status_create "
        "ON jobs(status, create_time)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_status_stop "
        "ON jobs(status, stop_time)")

    # Job dependencies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_dependencies (
            job_key TEXT NOT NULL,
            depends_on_key TEXT NOT NULL,
            PRIMARY KEY (job_key, depends_on_key),
            FOREIGN KEY (job_key) REFERENCES jobs(key) ON DELETE CASCADE
        )
    """)

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_dep_job_key "
        "ON job_dependencies(job_key)")

    # Metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()


def migrateFromKeyValue(conn, old_conn, status):
    # pylint: disable=too-many-locals,protected-access
    """
    Migrate data from old key-value format to new relational format.

    Args:
        conn: New database connection
        old_conn: Old database connection
        status: 'active' or 'inactive'
    """
    LOG.info("Migrating %s jobs from key-value format to relational format",
             status)

    # Read from old format
    old_cursor = old_conn.cursor()
    old_cursor.execute(
        f"SELECT key, value FROM {status} WHERE key NOT LIKE '\\_%'")

    migrated = 0
    for key, value_json in old_cursor.fetchall():
        try:
            # Deserialize job from old format
            job_dict = json.loads(value_json, object_hook=decodeJobInfo)
            if not isinstance(job_dict, JobInfo):
                continue

            job = job_dict

            # Insert into new format
            args_json = json.dumps(job.args) if job.args else None
            cmd_json = json.dumps(job.cmd) if job._cmd else None
            env_json = json.dumps(job.environ) if job.environ else None

            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO jobs (
                    key, persist_key, uidx, prog, args, cmd, reminder, pwd,
                    auto_job, mail_job, isolate, create_time, start_time,
                    stop_time, rc, pid, blocked, logfile, host, user,
                    workspace, proj, env, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?)
            """, (
                key, job._persistKeyGenerated, job._uidx, job.prog, args_json,
                cmd_json, job.reminder, job.pwd, int(job.autoJob or 0),
                int(job.mailJob or 0), int(job.isolate or 0),
                job._create.isoformat() if job._create else None,
                job._start.isoformat() if job._start else None,
                job._stop.isoformat() if job._stop else None,
                job._rc, job.pid,
                int(job._blocked or 0), job.logfile, job._host, job._user,
                job.workspace, job.proj, env_json, status
            ))

            # Migrate dependencies
            if job._depends:
                for dep_key in job._depends:
                    cursor.execute(
                        "INSERT OR IGNORE INTO job_dependencies "
                        "(job_key, depends_on_key) VALUES (?, ?)",
                        (key, dep_key))

            migrated += 1

        except Exception as e:
            LOG.warning("Failed to migrate job %s: %s", key, e)
            continue

    # Migrate metadata
    for meta_key in ["_schemaVersion_", "_lastKey_", "_lastJob_",
                     "_itemCount_", "_checkPoint_", "_recentItems_",
                     "_currentIndex_"]:
        try:
            old_cursor.execute(
                f"SELECT value FROM {status} WHERE key = ?", (meta_key,))
            row = old_cursor.fetchone()
            if row:
                cursor.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    (meta_key, row[0]))
        except Exception as e:
            LOG.debug("Could not migrate metadata %s: %s", meta_key, e)

    conn.commit()
    LOG.info("Migrated %d %s jobs", migrated, status)


class RelationalJobs(JobsBase):
    """
    Jobs database using proper relational schema with indices.

    This implementation provides significant performance improvements over
    the old key-value store for common operations like filtering by workspace,
    searching by command, and querying by time range.
    """

    def __init__(self, config, plugins, migrate=True):
        """
        Initialize relational database.

        Args:
            config: Configuration object
            plugins: Plugins instance
            migrate: If True, migrate from old format if it exists
        """
        super().__init__(config, plugins)
        self._filename = resolveDbFile(config, "jobsDb_v2.sqlite")
        self._old_filename = resolveDbFile(config, "jobsDb.sqlite")

        # Check if we need to migrate
        needs_migration = (migrate and
                           not os.path.exists(self._filename) and
                           os.path.exists(self._old_filename))

        self._lock.lock()

        # Create/open new database
        conn = sqlite3.connect(self._filename)
        conn.isolation_level = "EXCLUSIVE"
        createSchema(conn)

        # Perform migration if needed
        if needs_migration:
            try:
                old_conn = sqlite3.connect(self._old_filename)
                migrateFromKeyValue(conn, old_conn, "active")
                migrateFromKeyValue(conn, old_conn, "inactive")
                old_conn.close()
                LOG.info("Migration from key-value format completed")
            except Exception as e:
                LOG.error("Migration failed: %s", e)

        # Initialize active and inactive databases
        active_db = RelationalDatabase(
            self, config, self._instanceId, "active")
        inactive_db = RelationalDatabase(
            self, config, self._instanceId, "inactive")

        # Set connections on the database objects
        active_db.conn = conn
        inactive_db.conn = conn

        # Assign directly to private attributes (we're still in __init__)
        self._active = active_db
        self._inactive = inactive_db

        # Initialize metadata if needed
        self._init_metadata()

        conn.close()
        self._lock.unlock()

    def _init_metadata(self):
        """Initialize metadata with default values if not present."""
        # Use _active directly since we're in init
        conn = self._active.conn
        cursor = conn.cursor()

        # Check if metadata is initialized
        cursor.execute("SELECT COUNT(*) FROM metadata")
        if cursor.fetchone()[0] == 0:
            # Initialize with defaults
            cursor.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (DatabaseMeta.SV, SCHEMA_VERSION))
            cursor.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (DatabaseMeta.LASTKEY, ""))
            cursor.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (DatabaseMeta.LASTJOB, ""))
            cursor.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (DatabaseMeta.ITEMCOUNT, "0"))
            cursor.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (DatabaseMeta.CHECKPOINT, ""))
            cursor.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (DatabaseMeta.RECENT, "[]"))
            cursor.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (DatabaseMeta.IDX, "0"))
            conn.commit()

    def isLocked(self):
        return self._lock.isLocked()

    def lock(self):
        super().lock()
        self._lock.lock()
        conn = sqlite3.connect(self._filename)
        conn.isolation_level = "EXCLUSIVE"
        # Set conn directly to avoid property getter triggering __len__
        self._active.conn = conn
        self._inactive.conn = conn
        self._active.lock()
        self._inactive.lock()
        conn.execute("BEGIN EXCLUSIVE")

    def unlock(self):
        super().unlock()
        conn = self._active.conn
        if self._active.dirty or self._inactive.dirty:
            conn.commit()
        self._active.unlock()
        self._inactive.unlock()
        self._active.conn = None
        self._inactive.conn = None
        conn.close()
        self._lock.unlock()


# Import os for file checks in __init__
