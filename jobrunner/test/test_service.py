"""
Tests for service layer.
"""

from argparse import Namespace
import os
import shutil
import tempfile
import unittest
from unittest import mock

from jobrunner import plugins, utils
from jobrunner.config import Config
from jobrunner.domain import JobStatus
from jobrunner.repository import SqliteJobRepository
from jobrunner.service_layer import JobService


def setUpModule():
    mockPlug = mock.MagicMock(plugins.Plugins)
    mockPlug.workspaceIdentity.return_value = "MYWS"
    mockPlug.workspaceProject.return_value = ("myProject", True)
    utils.MOD_STATE.plugins = mockPlug


class TestJobService(unittest.TestCase):
    """Test JobService business logic."""

    def setUp(self):
        """Set up test service."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.repo = SqliteJobRepository(self.db_path)

        # Create minimal config using mock options
        options = Namespace(
            stateDir=self.temp_dir,
            rcFile="/dev/null",  # Empty config file
            debugLevel=[],
            verbose=None,
        )
        self.config = Config(options)

        self.service = JobService(self.repo, self.config)

    def tearDown(self):
        """Clean up test service."""
        self.service.close()

        # Clean up temp files
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_create_job(self):
        """Test creating a job."""
        job, fd = self.service.create_job(cmd=["echo", "test"])

        self.assertIsNotNone(job)
        self.assertEqual(job.cmd, ["echo", "test"])
        self.assertEqual(job.prog, "echo")
        self.assertEqual(job.args, ["test"])
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertIsNotNone(job.logfile)

        # Close file descriptor
        os.close(fd)

        # Verify job was saved
        retrieved = self.repo.get(job.key)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.key, job.key)

    def test_create_reminder(self):
        """Test creating a reminder job."""
        job, fd = self.service.create_job(
            cmd=None,
            reminder="Test reminder",
        )

        self.assertIsNotNone(job)
        self.assertEqual(job.reminder, "Test reminder")
        self.assertEqual(job.cmd, ["(reminder)"])

        os.close(fd)

    def test_start_job(self):
        """Test starting a job."""
        job, fd = self.service.create_job(cmd=["sleep", "1"])
        os.close(fd)

        updated = self.service.start_job(job.key, pid=12345)

        self.assertEqual(updated.status, JobStatus.RUNNING)
        self.assertEqual(updated.pid, 12345)
        self.assertIsNotNone(updated.start_time)

    def test_complete_job(self):
        """Test completing a job."""
        job, fd = self.service.create_job(cmd=["echo", "test"])
        os.close(fd)

        self.service.start_job(job.key, pid=12345)
        completed = self.service.complete_job(job.key, rc=0)

        self.assertEqual(completed.status, JobStatus.COMPLETED)
        self.assertEqual(completed.rc, 0)
        self.assertIsNotNone(completed.stop_time)
        self.assertIsNone(completed.pid)

    def test_set_dependencies(self):
        """Test setting job dependencies."""
        job1, fd1 = self.service.create_job(cmd=["echo", "first"])
        job2, fd2 = self.service.create_job(cmd=["echo", "second"])
        os.close(fd1)
        os.close(fd2)

        updated = self.service.set_dependencies(job2.key, [job1.key])

        self.assertEqual(updated.depends_on, [job1.key])
        self.assertEqual(updated.all_deps, {job1.key})

    def test_get_active_jobs(self):
        """Test getting active jobs."""
        job1, fd1 = self.service.create_job(cmd=["echo", "1"])
        job2, fd2 = self.service.create_job(cmd=["echo", "2"])
        job3, fd3 = self.service.create_job(cmd=["echo", "3"])

        os.close(fd1)
        os.close(fd2)
        os.close(fd3)

        # Complete job2
        self.service.start_job(job2.key, pid=123)
        self.service.complete_job(job2.key, rc=0)

        active = self.service.get_active_jobs()

        self.assertEqual(len(active), 2)
        self.assertIn(job1.key, [j.key for j in active])
        self.assertIn(job3.key, [j.key for j in active])

    def test_get_completed_jobs(self):
        """Test getting completed jobs."""
        job1, fd1 = self.service.create_job(cmd=["echo", "1"])
        _, fd2 = self.service.create_job(cmd=["echo", "2"])

        os.close(fd1)
        os.close(fd2)

        self.service.start_job(job1.key, pid=123)
        self.service.complete_job(job1.key, rc=0)

        completed = self.service.get_completed_jobs(limit=10)

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].key, job1.key)

    def test_find_job_by_exact_key(self):
        """Test finding job by exact key."""
        job, fd = self.service.create_job(cmd=["echo", "test"])
        os.close(fd)

        found = self.service.find_job_by_pattern(job.key)

        self.assertEqual(found.key, job.key)

    def test_find_job_by_command_pattern(self):
        """Test finding job by command pattern."""
        job, fd = self.service.create_job(cmd=["echo", "unique_string"])
        os.close(fd)

        found = self.service.find_job_by_pattern("unique_string")

        self.assertEqual(found.key, job.key)

    def test_find_job_most_recent(self):
        """Test finding most recent job."""
        _, fd1 = self.service.create_job(cmd=["echo", "1"])
        job2, fd2 = self.service.create_job(cmd=["echo", "2"])

        os.close(fd1)
        os.close(fd2)

        found = self.service.find_job_by_pattern(None)

        # Should return most recent
        self.assertEqual(found.key, job2.key)

    def test_block_unblock_job(self):
        """Test blocking and unblocking jobs."""
        job, fd = self.service.create_job(cmd=["echo", "test"])
        os.close(fd)

        # Block
        blocked = self.service.block_job(job.key)
        self.assertTrue(blocked.blocked)
        self.assertEqual(blocked.status, JobStatus.BLOCKED)

        # Unblock
        unblocked = self.service.unblock_job(job.key)
        self.assertFalse(unblocked.blocked)
        self.assertEqual(unblocked.status, JobStatus.PENDING)

    def test_prune_jobs(self):
        """Test pruning old jobs."""
        # Create and complete 3 jobs
        jobs = []
        for i in range(3):
            job, fd = self.service.create_job(cmd=["echo", str(i)])
            os.close(fd)
            self.service.start_job(job.key, pid=123 + i)
            self.service.complete_job(job.key, rc=0)
            jobs.append(job)

        # Prune, keeping only 1
        deleted_count = self.service.prune_jobs(keep_count=1)

        self.assertEqual(deleted_count, 2)

        # Verify only 1 job remains
        self.assertEqual(self.service.count_completed(), 1)

    def test_checkpoint(self):
        """Test checkpoint functionality."""
        # Create a job
        _, fd1 = self.service.create_job(cmd=["echo", "before"])
        os.close(fd1)

        # Set checkpoint
        self.service.set_checkpoint()

        # Create another job
        job2, fd2 = self.service.create_job(cmd=["echo", "after"])
        os.close(fd2)

        # Get jobs since checkpoint
        since_cp = self.service.get_jobs_since_checkpoint()

        self.assertEqual(len(since_cp), 1)
        self.assertEqual(since_cp[0].key, job2.key)


if __name__ == "__main__":
    unittest.main()
