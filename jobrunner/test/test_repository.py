"""
Tests for repository layer.
"""

from datetime import datetime, timedelta
import os
import tempfile
import unittest

from dateutil.tz import tzutc

from jobrunner.domain import Job, JobStatus
from jobrunner.repository import SqliteJobRepository


class TestSqliteJobRepository(unittest.TestCase):
    """Test SQLite repository implementation."""

    def setUp(self):
        """Set up test repository."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.repo = SqliteJobRepository(self.db_path)

    def tearDown(self):
        """Clean up test repository."""
        self.repo.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        """Test saving and retrieving a job."""
        job = Job(
            key="test_key",
            uidx=1,
            cmd=["echo", "test"],
            prog="echo",
            args=["test"],
            status=JobStatus.PENDING,
        )

        self.repo.save(job)

        retrieved = self.repo.get("test_key")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.key, "test_key")
        self.assertEqual(retrieved.cmd, ["echo", "test"])
        self.assertEqual(retrieved.status, JobStatus.PENDING)

    def test_get_nonexistent(self):
        """Test getting a nonexistent job."""
        result = self.repo.get("nonexistent")
        self.assertIsNone(result)

    def test_exists(self):
        """Test checking if job exists."""
        job = Job(key="test", uidx=1)
        self.assertFalse(self.repo.exists("test"))

        self.repo.save(job)
        self.assertTrue(self.repo.exists("test"))

    def test_delete(self):
        """Test deleting a job."""
        job = Job(key="test", uidx=1)
        self.repo.save(job)

        self.assertTrue(self.repo.exists("test"))

        self.repo.delete("test")
        self.assertFalse(self.repo.exists("test"))

    def test_find_active(self):
        """Test finding active jobs."""
        now = datetime.now(tzutc())

        job1 = Job(key="job1", uidx=1, status=JobStatus.RUNNING, create_time=now)
        job2 = Job(key="job2", uidx=2, status=JobStatus.COMPLETED,
                   create_time=now + timedelta(seconds=1))
        job3 = Job(key="job3", uidx=3, status=JobStatus.PENDING,
                   create_time=now + timedelta(seconds=2))

        self.repo.save(job1)
        self.repo.save(job2)
        self.repo.save(job3)

        active = self.repo.find_active()

        self.assertEqual(len(active), 2)
        self.assertEqual(active[0].key, "job1")
        self.assertEqual(active[1].key, "job3")

    def test_find_completed(self):
        """Test finding completed jobs."""
        now = datetime.now(tzutc())

        job1 = Job(
            key="cjob1",
            uidx=1,
            status=JobStatus.COMPLETED,
            stop_time=now,
        )
        job2 = Job(
            key="cjob2",
            uidx=2,
            status=JobStatus.RUNNING,
        )
        job3 = Job(
            key="cjob3",
            uidx=3,
            status=JobStatus.COMPLETED,
            stop_time=now + timedelta(seconds=1),
        )

        self.repo.save(job1)
        self.repo.save(job2)
        self.repo.save(job3)

        completed = self.repo.find_completed(limit=10)

        self.assertEqual(len(completed), 2)
        # Sorted by stop_time descending
        self.assertEqual(completed[0].key, "cjob3")
        self.assertEqual(completed[1].key, "cjob1")

    def test_find_by_workspace(self):
        """Test filtering by workspace."""
        job1 = Job(key="job1", uidx=1, workspace="/ws1")
        job2 = Job(key="job2", uidx=2, workspace="/ws2")
        job3 = Job(key="job3", uidx=3, workspace="/ws1")

        self.repo.save(job1)
        self.repo.save(job2)
        self.repo.save(job3)

        ws1_jobs = self.repo.find_active(workspace="/ws1")

        self.assertEqual(len(ws1_jobs), 2)
        self.assertEqual(ws1_jobs[0].key, "job1")
        self.assertEqual(ws1_jobs[1].key, "job3")

    def test_search_by_command(self):
        """Test searching by command."""
        job1 = Job(key="job1", uidx=1, cmd=["echo", "hello"])
        job2 = Job(key="job2", uidx=2, cmd=["ls", "-la"])
        job3 = Job(key="job3", uidx=3, cmd=["echo", "world"])

        self.repo.save(job1)
        self.repo.save(job2)
        self.repo.save(job3)

        results = self.repo.search_by_command("echo")

        self.assertEqual(len(results), 2)

    def test_next_uidx(self):
        """Test unique index generation."""
        idx1 = self.repo.next_uidx()
        idx2 = self.repo.next_uidx()
        idx3 = self.repo.next_uidx()

        self.assertEqual(idx1, 0)
        self.assertEqual(idx2, 1)
        self.assertEqual(idx3, 2)

    def test_metadata(self):
        """Test metadata operations."""
        metadata = self.repo.get_metadata()

        metadata.last_key = "test_key"
        metadata.last_job = "test_job"
        metadata.checkpoint = datetime.now(tzutc())
        metadata.recent_keys = ["key1", "key2"]

        self.repo.update_metadata(metadata)

        # Retrieve and verify
        retrieved = self.repo.get_metadata()

        self.assertEqual(retrieved.last_key, "test_key")
        self.assertEqual(retrieved.last_job, "test_job")
        self.assertIsNotNone(retrieved.checkpoint)
        self.assertEqual(retrieved.recent_keys, ["key1", "key2"])

    def test_count(self):
        """Test counting jobs."""
        self.assertEqual(self.repo.count(), 0)

        job1 = Job(key="job1", uidx=1, status=JobStatus.RUNNING)
        job2 = Job(key="job2", uidx=2, status=JobStatus.COMPLETED)

        self.repo.save(job1)
        self.assertEqual(self.repo.count(), 1)

        self.repo.save(job2)
        self.assertEqual(self.repo.count(), 2)

        self.assertEqual(self.repo.count(JobStatus.RUNNING), 1)
        self.assertEqual(self.repo.count(JobStatus.COMPLETED), 1)


if __name__ == "__main__":
    unittest.main()
