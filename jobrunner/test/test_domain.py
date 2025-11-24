"""
Tests for domain models.
"""

from datetime import datetime, timedelta
import unittest

from dateutil.tz import tzutc

from jobrunner.domain import Job, JobStatus


class TestJob(unittest.TestCase):
    """Test Job domain model."""

    def test_create_basic_job(self):
        """Test creating a basic job."""
        job = Job(
            key="test_key",
            uidx=1,
            cmd=["echo", "hello"],
            prog="echo",
            args=["hello"],
        )

        self.assertEqual(job.key, "test_key")
        self.assertEqual(job.uidx, 1)
        self.assertEqual(job.cmd, ["echo", "hello"])
        self.assertEqual(job.prog, "echo")
        self.assertEqual(job.args, ["hello"])
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertIsNotNone(job.create_time)

    def test_job_is_active(self):
        """Test is_active method."""
        job = Job(key="test", uidx=1, status=JobStatus.PENDING)
        self.assertTrue(job.is_active())

        job.status = JobStatus.RUNNING
        self.assertTrue(job.is_active())

        job.status = JobStatus.COMPLETED
        self.assertFalse(job.is_active())

    def test_job_duration(self):
        """Test duration calculation."""
        now = datetime.now(tzutc())
        job = Job(
            key="test",
            uidx=1,
            create_time=now,
            start_time=now,
        )

        # Job running for 10 seconds
        job.stop_time = now + timedelta(seconds=10)
        self.assertAlmostEqual(job.duration_seconds(), 10.0, delta=0.1)

    def test_job_duration_no_start(self):
        """Test duration when job hasn't started."""
        job = Job(key="test", uidx=1)
        self.assertIsNone(job.duration_seconds())
        self.assertEqual(job.duration_str(), "Blocked")

    def test_job_cmd_str(self):
        """Test cmd_str method."""
        job = Job(
            key="test",
            uidx=1,
            cmd=["echo", "hello world"],
        )
        self.assertIn("echo", job.cmd_str())
        self.assertIn("hello world", job.cmd_str())

    def test_job_cmd_str_reminder(self):
        """Test cmd_str with reminder."""
        job = Job(
            key="test",
            uidx=1,
            cmd=["echo", "test"],
            reminder="Test reminder",
        )
        self.assertEqual(job.cmd_str(), "Test reminder")

    def test_job_sorting_active(self):
        """Test job sorting for active jobs."""
        now = datetime.now(tzutc())

        job1 = Job(key="job1", uidx=1, create_time=now)
        job2 = Job(key="job2", uidx=2, create_time=now + timedelta(seconds=1))

        jobs = [job2, job1]
        jobs.sort()

        self.assertEqual(jobs[0].key, "job1")
        self.assertEqual(jobs[1].key, "job2")

    def test_job_sorting_completed(self):
        """Test job sorting for completed jobs."""
        now = datetime.now(tzutc())

        job1 = Job(
            key="job1",
            uidx=1,
            status=JobStatus.COMPLETED,
            stop_time=now,
        )
        job2 = Job(
            key="job2",
            uidx=2,
            status=JobStatus.COMPLETED,
            stop_time=now + timedelta(seconds=1),
        )

        jobs = [job2, job1]
        jobs.sort()

        # Completed jobs sorted by stop_time
        self.assertEqual(jobs[0].key, "job1")
        self.assertEqual(jobs[1].key, "job2")

    def test_job_equality(self):
        """Test job equality."""
        job1 = Job(key="test", uidx=1)
        job2 = Job(key="test", uidx=2)
        job3 = Job(key="other", uidx=1)

        self.assertEqual(job1, job2)  # Same key
        self.assertNotEqual(job1, job3)  # Different key

    def test_job_hash(self):
        """Test job hashing."""
        job1 = Job(key="test", uidx=1)
        job2 = Job(key="test", uidx=2)

        # Same key should hash the same
        self.assertEqual(hash(job1), hash(job2))

        # Can be added to set
        job_set = {job1, job2}
        self.assertEqual(len(job_set), 1)


if __name__ == "__main__":
    unittest.main()
