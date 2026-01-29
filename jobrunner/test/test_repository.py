"""
Tests for repository layer.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta
import os
import tempfile
import unittest

from dateutil.tz import tzutc

from jobrunner.domain import Job, JobStatus
from jobrunner.repository import SqliteJobRepository
from jobrunner.sequences import DEP_TYPE_SUCCESS


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
        job2 = Job(
            key="job2",
            uidx=2,
            status=JobStatus.COMPLETED,
            create_time=now + timedelta(seconds=1),
        )
        job3 = Job(
            key="job3",
            uidx=3,
            status=JobStatus.PENDING,
            create_time=now + timedelta(seconds=2),
        )

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

    def test_find_completed_for_listing(self):
        """Test finding completed jobs with for_listing=True optimization."""
        now = datetime.now(tzutc())

        # Create a job with all fields populated
        full_job = Job(
            key="full_job",
            uidx=1,
            prog="echo",
            args=["hello", "world"],
            cmd=["echo", "hello", "world"],
            reminder="test reminder",
            pwd="/home/user",
            create_time=now,
            start_time=now + timedelta(seconds=1),
            stop_time=now + timedelta(seconds=2),
            status=JobStatus.COMPLETED,
            rc=0,
            pid=12345,
            blocked=False,
            workspace="/ws1",
            project="test_project",
            host="localhost",
            user="testuser",
            env={"PATH": "/usr/bin", "HOME": "/home/user"},
            depends_on=["job1", "job2"],
            logfile="/tmp/log.txt",
            auto_job=True,
            mail_job=False,
            isolate=True,
            persist_key="persist1",
            persist_key_generated=False,
        )

        self.repo.save(full_job)

        # Test for_listing=True returns minimal fields
        listing_jobs = self.repo.find_completed(for_listing=True)
        self.assertEqual(len(listing_jobs), 1)
        listing_job = listing_jobs[0]

        # Essential fields should be populated
        self.assertEqual(listing_job.key, "full_job")
        self.assertEqual(listing_job.uidx, 1)
        self.assertEqual(listing_job.cmd, ["echo", "hello", "world"])
        self.assertEqual(listing_job.reminder, "test reminder")
        self.assertEqual(listing_job.create_time, now)
        self.assertEqual(listing_job.start_time, now + timedelta(seconds=1))
        self.assertEqual(listing_job.stop_time, now + timedelta(seconds=2))
        self.assertEqual(listing_job.status, JobStatus.COMPLETED)
        self.assertEqual(listing_job.rc, 0)

        # Non-essential fields should be None/empty (optimization)
        self.assertIsNone(listing_job.prog)
        self.assertIsNone(listing_job.args)
        self.assertIsNone(listing_job.pwd)
        self.assertIsNone(listing_job.pid)
        self.assertFalse(listing_job.blocked)
        self.assertIsNone(listing_job.workspace)
        self.assertIsNone(listing_job.project)
        self.assertIsNone(listing_job.host)
        self.assertIsNone(listing_job.user)
        self.assertEqual(listing_job.env, {})
        self.assertEqual(listing_job.depends_on, [])
        self.assertEqual(listing_job.all_deps, set())
        self.assertIsNone(listing_job.logfile)
        self.assertFalse(listing_job.auto_job)
        self.assertFalse(listing_job.mail_job)
        self.assertFalse(listing_job.isolate)
        self.assertIsNone(listing_job.persist_key)
        # persist_key_generated is set by __post_init__ to persist_key or key
        self.assertEqual(listing_job.persist_key_generated, "full_job")

        # Test for_listing=False returns complete fields
        complete_jobs = self.repo.find_completed(for_listing=False)
        self.assertEqual(len(complete_jobs), 1)
        complete_job = complete_jobs[0]

        # All fields should be populated
        self.assertEqual(complete_job.key, "full_job")
        self.assertEqual(complete_job.prog, "echo")
        self.assertEqual(complete_job.args, ["hello", "world"])
        self.assertEqual(complete_job.cmd, ["echo", "hello", "world"])
        self.assertEqual(complete_job.pwd, "/home/user")
        self.assertEqual(complete_job.workspace, "/ws1")
        self.assertEqual(
            complete_job.env, {"PATH": "/usr/bin", "HOME": "/home/user"}
        )
        self.assertEqual(complete_job.depends_on, ["job1", "job2"])
        self.assertTrue(complete_job.auto_job)
        self.assertTrue(complete_job.isolate)

        # Test that both modes return the same job keys
        job2 = Job(
            key="job2",
            uidx=2,
            cmd=["ls"],
            status=JobStatus.COMPLETED,
            stop_time=now + timedelta(seconds=3),
        )
        self.repo.save(job2)

        listing_keys = [j.key for j in self.repo.find_completed(for_listing=True)]
        complete_keys = [j.key for j in self.repo.find_completed(for_listing=False)]
        self.assertEqual(listing_keys, complete_keys)

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

    def test_find_latest(self):
        """Test finding most recent job."""
        now = datetime.now(tzutc())

        job1 = Job(
            key="job1",
            uidx=1,
            status=JobStatus.COMPLETED,
            create_time=now,
        )
        job2 = Job(
            key="job2",
            uidx=2,
            status=JobStatus.RUNNING,
            create_time=now + timedelta(seconds=1),
            mail_job=False,
        )
        job3 = Job(
            key="job3",
            uidx=3,
            status=JobStatus.PENDING,
            create_time=now + timedelta(seconds=2),
            reminder="test reminder",
        )

        self.repo.save(job1)
        self.repo.save(job2)
        self.repo.save(job3)

        # Test finding latest active job
        latest = self.repo.find_latest(exclude_completed=True)
        self.assertIsNotNone(latest)
        # job3 is most recent active, but let's test without skip_reminders
        # so it should return job3
        self.assertEqual(latest.key, "job3")

        # Test finding latest active job, skipping reminders
        latest = self.repo.find_latest(exclude_completed=True, skip_reminders=True)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.key, "job2")

        # Test finding latest job overall (including completed)
        latest = self.repo.find_latest(exclude_completed=False)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.key, "job3")

        # Test finding latest with workspace filter
        latest = self.repo.find_latest(workspace="/nonexistent")
        self.assertIsNone(latest)

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

    def assertMatchingJobs(
        self, expected: Iterable[str], matches: Iterable[Job]
    ) -> None:
        self.assertEqual(expected, [job.key for job in matches])

    def test_find_matching(self):
        """Test finding jobs matching a keyword."""
        now = datetime.now(tzutc())

        # Create jobs with different command patterns
        job1 = Job(
            key="job1",
            uidx=1,
            cmd=["echo", "test message"],
            status=JobStatus.RUNNING,
            create_time=now,
            start_time=now,
            mail_job=False,
        )
        job2 = Job(
            key="job2",
            uidx=2,
            cmd=["python", "test.py"],
            status=JobStatus.COMPLETED,
            create_time=now + timedelta(seconds=1),
            start_time=now + timedelta(seconds=1),
            stop_time=now + timedelta(seconds=10),
            mail_job=False,
        )
        job3 = Job(
            key="another_key",
            uidx=3,
            cmd=["ls", "-la"],
            status=JobStatus.COMPLETED,
            create_time=now + timedelta(seconds=2),
            stop_time=now + timedelta(seconds=11),
            mail_job=False,
        )
        job4 = Job(
            key="mail_job",
            uidx=4,
            cmd=["echo", "test"],
            status=JobStatus.COMPLETED,
            create_time=now + timedelta(seconds=3),
            stop_time=now + timedelta(seconds=12),
            mail_job=True,  # This should be filtered out
        )
        job5 = Job(
            key="reminder_job",
            uidx=5,
            cmd=["sleep", "10"],
            reminder="test reminder",
            status=JobStatus.RUNNING,
            create_time=now + timedelta(seconds=4),
            mail_job=False,
        )

        self.repo.save(job1)
        self.repo.save(job2)
        self.repo.save(job3)
        self.repo.save(job4)
        self.repo.save(job5)

        # Test: Find jobs by command keyword "test"
        matches = self.repo.find_matching("test")
        # job1, job2 (not job4 as it's mail_job, not job5 as "test" not in cmd)
        self.assertMatchingJobs(["job2", "job1"], matches)

        # Test: Find jobs by key prefix
        matches = self.repo.find_matching("another")
        self.assertMatchingJobs(["another_key"], matches)

        # Test: Skip reminders (using "sleep" to match reminder_job)
        matches_with_reminder = self.repo.find_matching("sleep")
        self.assertMatchingJobs(["reminder_job"], matches_with_reminder)

        matches_no_reminder = self.repo.find_matching("sleep", skip_reminders=True)
        self.assertMatchingJobs([], matches_no_reminder)

        # Test: Filter by workspace
        job_with_ws = Job(
            key="ws_job",
            uidx=6,
            cmd=["echo", "test"],
            status=JobStatus.COMPLETED,
            create_time=now + timedelta(seconds=5),
            start_time=now + timedelta(seconds=5),
            stop_time=now + timedelta(seconds=15),
            workspace="/home/user/project",
            mail_job=False,
        )
        self.repo.save(job_with_ws)

        matches = self.repo.find_matching("test", workspace="/home/user/project")
        self.assertMatchingJobs(["ws_job"], matches)

        # Test: No matches
        matches = self.repo.find_matching("nonexistent_keyword")
        self.assertMatchingJobs([], matches)

        # Test: Ordering - completed jobs (oldest first), then active jobs (oldest
        # first)
        matches = self.repo.find_matching("test")
        self.assertMatchingJobs(["job2", "ws_job", "job1"], matches)

        # Test: Filter by checkpoint (since parameter)
        checkpoint = now + timedelta(seconds=2)
        matches_since_checkpoint = self.repo.find_matching("test", since=checkpoint)
        # Only jobs created at or after checkpoint: ws_job (at +5s)
        # job1 (at 0s) and job2 (at +1s) are before checkpoint
        self.assertMatchingJobs(["ws_job"], matches_since_checkpoint)

        # Test: Checkpoint with no matches
        future_checkpoint = now + timedelta(seconds=100)
        matches_future = self.repo.find_matching("test", since=future_checkpoint)
        self.assertMatchingJobs([], matches_future)


class TestSqliteJobRepositorySequences(unittest.TestCase):
    """Test sequence methods in SQLite repository."""

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

    def test_is_sequence_nonexistent(self):
        """Test is_sequence returns False for nonexistent sequence."""
        self.assertFalse(self.repo.is_sequence("nonexistent"))

    def test_add_sequence_step_and_is_sequence(self):
        """Test adding sequence step and checking existence."""
        step_num = self.repo.add_sequence_step(
            name="test_seq", job_key="job1", dependencies=[]
        )

        self.assertEqual(0, step_num)
        self.assertTrue(self.repo.is_sequence("test_seq"))

    def test_add_sequence_step_with_dependencies(self):
        """Test adding sequence step with dependencies."""
        # Add first step
        self.repo.add_sequence_step("seq", "job1", [])

        # Add second step with dependencies
        step_num = self.repo.add_sequence_step(
            "seq", "job2", [(0, DEP_TYPE_SUCCESS)]
        )

        self.assertEqual(1, step_num)

        # Verify dependencies
        steps = self.repo.get_sequence_steps("seq")
        self.assertEqual(2, len(steps))
        self.assertEqual([(0, DEP_TYPE_SUCCESS)], steps[1][2])

    def test_get_sequence_steps_order(self):
        """Test get_sequence_steps returns steps in order."""
        self.repo.add_sequence_step("seq", "job1", [])
        self.repo.add_sequence_step("seq", "job2", [])
        self.repo.add_sequence_step("seq", "job3", [])

        steps = self.repo.get_sequence_steps("seq")

        self.assertEqual(3, len(steps))
        self.assertEqual(0, steps[0][0])  # step_number
        self.assertEqual(1, steps[1][0])
        self.assertEqual(2, steps[2][0])
        self.assertEqual("job1", steps[0][1])  # job_key
        self.assertEqual("job2", steps[1][1])
        self.assertEqual("job3", steps[2][1])

    def test_delete_sequence(self):
        """Test deleting a sequence."""
        self.repo.add_sequence_step("seq", "job1", [])
        self.repo.add_sequence_step("seq", "job2", [])

        self.assertTrue(self.repo.is_sequence("seq"))

        self.repo.delete_sequence("seq")

        self.assertFalse(self.repo.is_sequence("seq"))
        self.assertEqual([], self.repo.get_sequence_steps("seq"))

    def test_list_sequences(self):
        """Test listing all sequences."""
        self.repo.add_sequence_step("seq1", "job1", [])
        self.repo.add_sequence_step("seq2", "job1", [])
        self.repo.add_sequence_step("seq1", "job2", [])

        sequences = self.repo.list_sequences()

        self.assertEqual(sorted(["seq1", "seq2"]), sorted(sequences))


if __name__ == "__main__":
    unittest.main()
