#!/usr/bin/env python3
"""
Benchmark script comparing old key-value database vs new relational database.

Usage:
    python benchmark_db.py [--jobs N] [--runs N]
"""

import argparse
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta

from dateutil.tz import tzutc

from jobrunner.config import Config
from jobrunner.db.sqlite_db import Sqlite3Jobs
from jobrunner.db.relational_db import RelationalJobs
from jobrunner.plugins import Plugins
from jobrunner.service.registry import registerServices


class BenchmarkConfig:
    """Minimal config for benchmarking."""
    def __init__(self, tmpdir):
        self.dbDir = tmpdir
        self.logDir = tmpdir
        self.lockFile = os.path.join(tmpdir, "lock")
        self.verbose = False
        self.debugLevel = set()
        self.uiWatchReminderSummary = True


def create_test_jobs(jobs_db, num_jobs=1000):
    """Create test jobs in database."""
    print(f"Creating {num_jobs} test jobs...")

    workspaces = [
        "/home/user/project1",
        "/home/user/project2",
        "/home/user/project3",
        "/home/user/project4",
        "/home/user/project5",
    ]

    commands = [
        ["python", "script.py"],
        ["bash", "test.sh"],
        ["make", "build"],
        ["npm", "test"],
        ["cargo", "build"],
        ["go", "test"],
    ]

    jobs_db.lock()

    created_keys = []
    start_time = time.time()

    for i in range(num_jobs):
        cmd = commands[i % len(commands)]
        workspace = workspaces[i % len(workspaces)]

        job, fd = jobs_db.new(cmd, False)
        os.close(fd)

        job._workspace = workspace
        job._proj = f"project{i % 5 + 1}"

        # Vary creation times
        minutes_ago = num_jobs - i
        job._create = datetime.now(tzutc()) - timedelta(minutes=minutes_ago)

        jobs_db.active[job.key] = job

        # Stop some jobs
        if i % 3 == 0:
            rc = 0 if i % 6 == 0 else 1
            job.stop(jobs_db, rc)

        created_keys.append(job.key)

    jobs_db.unlock()

    elapsed = time.time() - start_time
    print(f"  Created {num_jobs} jobs in {elapsed:.2f}s "
          f"({num_jobs/elapsed:.0f} jobs/sec)")

    return created_keys


def benchmark_workspace_filter(jobs_db, workspace, runs=10):
    """Benchmark filtering jobs by workspace."""
    times = []

    for _ in range(runs):
        jobs_db.lock()
        start = time.time()

        # Simulate old method: get all, filter in Python
        if hasattr(jobs_db.active, 'get_jobs_by_workspace'):
            # New method with index
            results = jobs_db.active.get_jobs_by_workspace(workspace)
        else:
            # Old method: full scan
            from jobrunner.db import JobsBase
            all_jobs = JobsBase.getDbSorted(jobs_db.active)
            results = [j for j in all_jobs if j.workspace == workspace]

        elapsed = time.time() - start
        times.append(elapsed)
        jobs_db.unlock()

    avg_time = sum(times) / len(times)
    return avg_time, len(results)


def benchmark_command_search(jobs_db, search_term, runs=10):
    """Benchmark searching jobs by command."""
    times = []

    for _ in range(runs):
        jobs_db.lock()
        start = time.time()

        if hasattr(jobs_db.inactive, 'search_by_command'):
            # New method with index
            results = jobs_db.inactive.search_by_command(search_term)
        else:
            # Old method: full scan
            from jobrunner.db import JobsBase
            all_jobs = JobsBase.getDbSorted(jobs_db.inactive)
            results = [j for j in all_jobs if search_term in j.cmdStr]

        elapsed = time.time() - start
        times.append(elapsed)
        jobs_db.unlock()

    avg_time = sum(times) / len(times)
    return avg_time, len(results)


def benchmark_time_range(jobs_db, hours_ago=1, runs=10):
    """Benchmark getting jobs within time range."""
    times = []
    since = datetime.now(tzutc()) - timedelta(hours=hours_ago)

    for _ in range(runs):
        jobs_db.lock()
        start = time.time()

        if hasattr(jobs_db.inactive, 'get_jobs_since'):
            # New method with index
            results = jobs_db.inactive.get_jobs_since(since)
        else:
            # Old method: full scan
            from jobrunner.db import JobsBase
            all_jobs = JobsBase.getDbSorted(jobs_db.inactive)
            results = [j for j in all_jobs
                      if j.createTime and j.createTime > since]

        elapsed = time.time() - start
        times.append(elapsed)
        jobs_db.unlock()

    avg_time = sum(times) / len(times)
    return avg_time, len(results)


def benchmark_recent_jobs(jobs_db, limit=5, runs=10):
    """Benchmark getting recent jobs."""
    times = []

    for _ in range(runs):
        jobs_db.lock()
        start = time.time()

        from jobrunner.db import JobsBase
        results = JobsBase.getDbSorted(jobs_db.inactive, _limit=limit)
        if len(results) > limit:
            results = results[-limit:]

        elapsed = time.time() - start
        times.append(elapsed)
        jobs_db.unlock()

    avg_time = sum(times) / len(times)
    return avg_time, len(results)


def run_benchmarks(num_jobs=1000, num_runs=10):
    """Run all benchmarks comparing old vs new database."""
    print("=" * 70)
    print(f"Database Performance Benchmark")
    print(f"Jobs: {num_jobs}, Runs per test: {num_runs}")
    print("=" * 70)

    registerServices(testing=True)
    plugins = Plugins()

    # Benchmark old database
    print("\n[1/2] Benchmarking OLD key-value database...")
    tmpdir_old = tempfile.mkdtemp()
    try:
        config_old = BenchmarkConfig(tmpdir_old)
        jobs_old = Sqlite3Jobs(config_old, plugins)
        create_test_jobs(jobs_old, num_jobs)

        old_ws_time, old_ws_count = benchmark_workspace_filter(
            jobs_old, "/home/user/project1", num_runs)
        old_cmd_time, old_cmd_count = benchmark_command_search(
            jobs_old, "python", num_runs)
        old_time_time, old_time_count = benchmark_time_range(
            jobs_old, 1, num_runs)
        old_recent_time, old_recent_count = benchmark_recent_jobs(
            jobs_old, 5, num_runs)

    finally:
        shutil.rmtree(tmpdir_old, ignore_errors=True)

    # Benchmark new database
    print("\n[2/2] Benchmarking NEW relational database...")
    tmpdir_new = tempfile.mkdtemp()
    try:
        config_new = BenchmarkConfig(tmpdir_new)
        jobs_new = RelationalJobs(config_new, plugins, migrate=False)
        create_test_jobs(jobs_new, num_jobs)

        new_ws_time, new_ws_count = benchmark_workspace_filter(
            jobs_new, "/home/user/project1", num_runs)
        new_cmd_time, new_cmd_count = benchmark_command_search(
            jobs_new, "python", num_runs)
        new_time_time, new_time_count = benchmark_time_range(
            jobs_new, 1, num_runs)
        new_recent_time, new_recent_count = benchmark_recent_jobs(
            jobs_new, 5, num_runs)

    finally:
        shutil.rmtree(tmpdir_new, ignore_errors=True)

    # Print results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    def print_result(name, old_time, new_time, count):
        speedup = old_time / new_time if new_time > 0 else float('inf')
        print(f"\n{name}:")
        print(f"  Results found: {count}")
        print(f"  Old DB: {old_time*1000:8.2f} ms")
        print(f"  New DB: {new_time*1000:8.2f} ms")
        print(f"  Speedup: {speedup:7.1f}x")

    print_result("Filter by workspace", old_ws_time, new_ws_time, old_ws_count)
    print_result("Search by command", old_cmd_time, new_cmd_time, old_cmd_count)
    print_result("Get jobs in time range", old_time_time, new_time_time,
                 old_time_count)
    print_result("Get recent jobs", old_recent_time, new_recent_time,
                 old_recent_count)

    # Summary
    avg_speedup = (
        (old_ws_time / new_ws_time +
         old_cmd_time / new_cmd_time +
         old_time_time / new_time_time +
         old_recent_time / new_recent_time) / 4
    )

    print("\n" + "=" * 70)
    print(f"Average speedup: {avg_speedup:.1f}x")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark jobrunner database implementations")
    parser.add_argument(
        "--jobs", type=int, default=1000,
        help="Number of test jobs to create (default: 1000)")
    parser.add_argument(
        "--runs", type=int, default=10,
        help="Number of runs per benchmark (default: 10)")

    args = parser.parse_args()

    run_benchmarks(args.jobs, args.runs)
