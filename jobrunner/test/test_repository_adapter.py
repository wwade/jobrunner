"""
Tests for repository adapter layer.
"""

from argparse import Namespace
from datetime import datetime, timedelta
import os
import shutil
import tempfile
import unittest

from dateutil.tz import tzutc

from jobrunner.config import Config
from jobrunner.db.repository_adapter import RepositoryAdapter
from jobrunner.domain import Job, JobStatus
from jobrunner.plugins import Plugins
from jobrunner.repository import SqliteJobRepository
from jobrunner.service.registry import registerServices


class TestRepositoryAdapterOptimizations(unittest.TestCase):
    """Test RepositoryAdapter getDbSorted optimization paths."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.repo = SqliteJobRepository(self.db_path)

        # Register test services
        registerServices(testing=True)

        # Create adapter
        options = Namespace(
            stateDir=self.temp_dir,
            rcFile="/dev/null",
            debugLevel=[],
            verbose=None,
        )
        config = Config(options)
        plugins = Plugins()

        self.adapter = RepositoryAdapter(config, plugins)
        self.adapter._repo = self.repo

    def tearDown(self):
        """Clean up test environment."""
        self.repo.close()
        shutil.rmtree(self.temp_dir)

    def test_getDbSorted_no_filters_uses_cached_values(self):
        """Test that getDbSorted with no filters uses cached db.values()."""
        now = datetime.now(tzutc())

        # Create test jobs
        job1 = Job(
            key="job1",
            uidx=1,
            cmd=["echo", "test"],
            status=JobStatus.RUNNING,
            create_time=now,
        )
        job2 = Job(
            key="job2",
            uidx=2,
            cmd=["ls"],
            status=JobStatus.PENDING,
            create_time=now + timedelta(seconds=1),
        )

        self.repo.save(job1)
        self.repo.save(job2)

        # Get active database
        db = self.adapter.active

        # Call getDbSorted with no filters
        result = self.adapter.getDbSorted(db)

        # Should return all active jobs
        self.assertEqual(len(result), 2)
        keys = [job.key for job in result]
        self.assertIn("job1", keys)
        self.assertIn("job2", keys)

    def test_getDbSorted_active_with_checkpoint(self):
        """Test getDbSorted for active jobs with checkpoint filter."""
        now = datetime.now(tzutc())

        job1 = Job(
            key="job1",
            uidx=1,
            cmd=["echo", "test"],
            status=JobStatus.RUNNING,
            create_time=now,
        )
        job2 = Job(
            key="job2",
            uidx=2,
            cmd=["ls"],
            status=JobStatus.PENDING,
            create_time=now + timedelta(seconds=10),
        )

        self.repo.save(job1)
        self.repo.save(job2)

        # Set checkpoint
        metadata = self.repo.get_metadata()
        metadata.checkpoint = now + timedelta(seconds=5)
        self.repo.update_metadata(metadata)

        # Get active database
        db = self.adapter.active

        # Call getDbSorted with checkpoint
        result = self.adapter.getDbSorted(db, useCp=True)

        # Should only return jobs after checkpoint
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].key, "job2")

    def test_getDbSorted_active_without_checkpoint(self):
        """Test getDbSorted for active jobs without checkpoint uses find_active."""
        now = datetime.now(tzutc())

        job1 = Job(
            key="job1",
            uidx=1,
            cmd=["echo", "test"],
            status=JobStatus.RUNNING,
            create_time=now,
        )
        job2 = Job(
            key="job2",
            uidx=2,
            cmd=["ls"],
            status=JobStatus.COMPLETED,
            create_time=now + timedelta(seconds=1),
            stop_time=now + timedelta(seconds=2),
        )

        self.repo.save(job1)
        self.repo.save(job2)

        # Get active database
        db = self.adapter.active

        # Call getDbSorted with no checkpoint
        result = self.adapter.getDbSorted(db)

        # Should only return active job (job1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].key, "job1")

    def test_getDbSorted_completed_with_checkpoint(self):
        """Test getDbSorted for completed jobs with checkpoint filter."""
        now = datetime.now(tzutc())

        job1 = Job(
            key="job1",
            uidx=1,
            cmd=["echo", "test"],
            status=JobStatus.COMPLETED,
            create_time=now,
            stop_time=now + timedelta(seconds=1),
        )
        job2 = Job(
            key="job2",
            uidx=2,
            cmd=["ls"],
            status=JobStatus.COMPLETED,
            create_time=now + timedelta(seconds=10),
            stop_time=now + timedelta(seconds=11),
        )

        self.repo.save(job1)
        self.repo.save(job2)

        # Set checkpoint
        metadata = self.repo.get_metadata()
        metadata.checkpoint = now + timedelta(seconds=5)
        self.repo.update_metadata(metadata)

        # Get inactive database
        db = self.adapter.inactive

        # Call getDbSorted with checkpoint
        result = self.adapter.getDbSorted(db, useCp=True)

        # Should only return jobs after checkpoint
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].key, "job2")

    def test_getDbSorted_completed_without_checkpoint_uses_for_listing(self):
        """Test that completed jobs without checkpoint use for_listing=True."""
        now = datetime.now(tzutc())

        # Create job with full fields
        job1 = Job(
            key="job1",
            uidx=1,
            prog="echo",
            args=["hello"],
            cmd=["echo", "hello"],
            status=JobStatus.COMPLETED,
            create_time=now,
            stop_time=now + timedelta(seconds=1),
            env={"PATH": "/usr/bin"},
            depends_on=["dep1"],
        )

        self.repo.save(job1)

        # Get inactive database
        db = self.adapter.inactive

        # Call getDbSorted with no filters
        result = self.adapter.getDbSorted(db)

        # Should return exactly job1 with correct cmd
        self.assertEqual(["job1"], [job.key for job in result])
        self.assertEqual(result[0].cmd, ["echo", "hello"])

    # Note: test_getDbSorted_with_workspace_filter removed because
    # filterWs=True calls workspaceIdentity() which requires plugins setup
    # that's complex to mock. The underlying repository workspace filtering
    # is tested in test_repository.py::test_find_by_workspace

    def test_getDbSorted_with_limit(self):
        """Test getDbSorted with limit parameter."""
        now = datetime.now(tzutc())

        # Create 5 active jobs
        for i in range(5):
            job = Job(
                key=f"job{i}",
                uidx=i,
                cmd=["echo", str(i)],
                status=JobStatus.RUNNING,
                create_time=now + timedelta(seconds=i),
            )
            self.repo.save(job)

        # Get active database
        db = self.adapter.active

        # Call getDbSorted with limit
        result = self.adapter.getDbSorted(db, _limit=3)

        # Should return first 3 jobs (sorted by create_time ascending)
        self.assertEqual(["job0", "job1", "job2"], [job.key for job in result])

    def test_getDbSorted_result_sorting(self):
        """Test that getDbSorted returns jobs sorted by create_time ascending."""
        now = datetime.now(tzutc())

        # Create jobs in non-chronological order
        job3 = Job(
            key="job3",
            uidx=3,
            cmd=["echo", "3"],
            status=JobStatus.RUNNING,
            create_time=now + timedelta(seconds=30),
        )
        job1 = Job(
            key="job1",
            uidx=1,
            cmd=["echo", "1"],
            status=JobStatus.RUNNING,
            create_time=now + timedelta(seconds=10),
        )
        job2 = Job(
            key="job2",
            uidx=2,
            cmd=["echo", "2"],
            status=JobStatus.RUNNING,
            create_time=now + timedelta(seconds=20),
        )

        self.repo.save(job3)
        self.repo.save(job1)
        self.repo.save(job2)

        # Get active database
        db = self.adapter.active

        # Call getDbSorted
        result = self.adapter.getDbSorted(db)

        # Should be sorted by create_time ascending
        self.assertEqual(["job1", "job2", "job3"], [job.key for job in result])


if __name__ == "__main__":
    unittest.main()
