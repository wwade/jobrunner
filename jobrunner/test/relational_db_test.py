"""
Tests for the new relational database implementation.
"""

from datetime import datetime, timedelta
import os
import shutil
import sqlite3
import tempfile
import unittest

from dateutil.tz import tzutc

from jobrunner.db.relational_db import RelationalJobs, createSchema
from jobrunner.plugins import Plugins
from jobrunner.service.registry import registerServices


class TestRelationalDatabase(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        registerServices(testing=True)
        self.tmpdir = tempfile.mkdtemp()
        self.config = self._makeConfig()
        self.plugins = Plugins()

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temp directory
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _makeConfig(self):
        """Create a test configuration."""
        class TestConfig:
            def __init__(self, tmpdir):
                self.dbDir = tmpdir
                self.logDir = tmpdir
                self.lockFile = os.path.join(tmpdir, "lock")
                self.verbose = False
                self.debugLevel = set()
                self.uiWatchReminderSummary = True

        return TestConfig(self.tmpdir)

    def test_create_schema(self):
        """Test that schema creation works."""
        db_file = os.path.join(self.tmpdir, "test.db")
        conn = sqlite3.connect(db_file)
        createSchema(conn)

        # Verify tables exist
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        self.assertIn("jobs", tables)
        self.assertIn("job_dependencies", tables)
        self.assertIn("metadata", tables)

        # Verify indices exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_%'")
        indices = [row[0] for row in cursor.fetchall()]

        self.assertIn("idx_jobs_key", indices)
        self.assertIn("idx_jobs_status", indices)
        self.assertIn("idx_jobs_workspace", indices)
        self.assertIn("idx_jobs_create_time", indices)
        self.assertIn("idx_jobs_stop_time", indices)

        conn.close()

    def test_basic_job_operations(self):
        """Test basic CRUD operations on jobs."""
        jobs = RelationalJobs(self.config, self.plugins, migrate=False)

        # Create a job
        jobs.lock()
        job, fd = jobs.new(["echo", "test"], False)
        os.close(fd)
        jobs.active[job.key] = job

        # Verify job is in active
        self.assertIn(job.key, jobs.active)
        retrieved = jobs.active[job.key]
        self.assertEqual(retrieved.cmd, ["echo", "test"])
        self.assertEqual(retrieved.prog, "echo")

        # Stop the job
        job.stop(jobs, 0)

        # Verify job moved to inactive
        self.assertNotIn(job.key, jobs.active)
        self.assertIn(job.key, jobs.inactive)

        inactive_job = jobs.inactive[job.key]
        self.assertEqual(inactive_job.rc, 0)
        self.assertIsNotNone(inactive_job.stopTime)

        jobs.unlock()

    def test_workspace_filtering(self):
        # pylint: disable=protected-access
        """Test efficient filtering by workspace."""
        jobs = RelationalJobs(self.config, self.plugins, migrate=False)

        jobs.lock()

        # Create jobs with different workspaces
        job1, fd1 = jobs.new(["cmd1"], False)
        os.close(fd1)
        job1._workspace = "/workspace/one"
        jobs.active[job1.key] = job1

        job2, fd2 = jobs.new(["cmd2"], False)
        os.close(fd2)
        job2._workspace = "/workspace/two"
        jobs.active[job2.key] = job2

        job3, fd3 = jobs.new(["cmd3"], False)
        os.close(fd3)
        job3._workspace = "/workspace/one"
        jobs.active[job3.key] = job3

        # Query by workspace using efficient index
        ws_jobs = jobs.active.get_jobs_by_workspace("/workspace/one")
        self.assertEqual(len(ws_jobs), 2)
        self.assertTrue(all(j.workspace == "/workspace/one"
                            for j in ws_jobs))

        jobs.unlock()

    def test_time_based_queries(self):
        # pylint: disable=protected-access
        """Test efficient time-based queries."""
        jobs = RelationalJobs(self.config, self.plugins, migrate=False)

        jobs.lock()

        now = datetime.now(tzutc())
        one_hour_ago = now - timedelta(hours=1)

        # Create job with specific create time
        job1, fd1 = jobs.new(["old_cmd"], False)
        os.close(fd1)
        job1._create = one_hour_ago
        jobs.active[job1.key] = job1

        # Create recent job
        job2, fd2 = jobs.new(["new_cmd"], False)
        os.close(fd2)
        job2._create = now
        jobs.active[job2.key] = job2

        # Query for jobs since 30 minutes ago
        thirty_min_ago = now - timedelta(minutes=30)
        recent_jobs = jobs.active.get_jobs_since(thirty_min_ago)

        self.assertEqual(len(recent_jobs), 1)
        self.assertEqual(recent_jobs[0].key, job2.key)

        jobs.unlock()

    def test_command_search(self):
        """Test searching by command string."""
        jobs = RelationalJobs(self.config, self.plugins, migrate=False)

        jobs.lock()

        # Create jobs with different commands
        job1, fd1 = jobs.new(["python", "script.py"], False)
        os.close(fd1)
        jobs.active[job1.key] = job1
        job1.stop(jobs, 0)

        job2, fd2 = jobs.new(["bash", "test.sh"], False)
        os.close(fd2)
        jobs.active[job2.key] = job2
        job2.stop(jobs, 0)

        job3, fd3 = jobs.new(["python", "analyze.py"], False)
        os.close(fd3)
        jobs.active[job3.key] = job3
        job3.stop(jobs, 0)

        # Search for python commands
        python_jobs = jobs.inactive.search_by_command("python")
        self.assertEqual(len(python_jobs), 2)
        self.assertTrue(all("python" in str(j.cmd) for j in python_jobs))

        jobs.unlock()

    def test_job_dependencies(self):
        """Test that job dependencies are properly stored and retrieved."""
        jobs = RelationalJobs(self.config, self.plugins, migrate=False)

        jobs.lock()

        # Create first job
        job1, fd1 = jobs.new(["echo", "first"], False)
        os.close(fd1)
        jobs.active[job1.key] = job1

        # Create second job that depends on first
        job2, fd2 = jobs.new(["echo", "second"], False)
        os.close(fd2)
        job2.depends = [job1]
        jobs.active[job2.key] = job2

        # Retrieve and verify dependencies
        retrieved = jobs.active[job2.key]
        self.assertIsNotNone(retrieved.depends)
        self.assertEqual(len(retrieved.depends), 1)
        self.assertEqual(retrieved.depends[0], job1.key)

        jobs.unlock()

    def test_job_deletion(self):
        """Test that job deletion works correctly."""
        jobs = RelationalJobs(self.config, self.plugins, migrate=False)

        jobs.lock()

        job, fd = jobs.new(["test"], False)
        os.close(fd)
        key = job.key
        jobs.active[key] = job

        # Verify job exists
        self.assertIn(key, jobs.active)

        # Delete job
        del jobs.active[key]

        # Verify job is gone
        self.assertNotIn(key, jobs.active)

        jobs.unlock()

    def test_recent_jobs_tracking(self):
        """Test that recent jobs are tracked correctly."""
        jobs = RelationalJobs(self.config, self.plugins, migrate=False)

        jobs.lock()

        # Create several jobs
        keys = []
        for i in range(5):
            job, fd = jobs.new([f"cmd{i}"], False)
            os.close(fd)
            jobs.active[job.key] = job
            keys.append(job.key)

        # Check recent list
        recent = jobs.active.recent
        self.assertIsInstance(recent, list)

        # Most recent should be last created
        self.assertEqual(recent[0], keys[-1])

        jobs.unlock()


if __name__ == "__main__":
    unittest.main()
