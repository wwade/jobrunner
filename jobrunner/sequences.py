"""
Sequence recording and replay functionality.

Sequences allow recording a chain of jobs with their dependencies
and replaying them later.
"""

# pylint: disable=too-many-locals
# pylint: disable=too-many-branches

import re
import subprocess
import sys
import time
from typing import Dict, List, Set, Tuple

from jobrunner.db import JobsBase

from .adapters.job_converter import job_to_jobinfo
from .info import JobInfo
from .utils import sprint

# Dependency type constants
DEP_TYPE_SUCCESS = "success"
DEP_TYPE_COMPLETION = "completion"


def validate_sequence_name(name: str) -> None:
    """
    Validate a sequence name.

    Args:
        name: The sequence name to validate

    Raises:
        ValueError: If name is invalid
    """
    if not name:
        raise ValueError("Sequence name cannot be empty")

    if len(name) > 255:
        raise ValueError("Sequence name too long (max 255 characters)")

    # Allow alphanumeric, underscore, hyphen, dot
    if not re.match(r"^[a-zA-Z0-9_.-]+$", name):
        raise ValueError(
            "Sequence name can only contain letters, numbers, "
            "underscores, hyphens, and dots"
        )


def build_dependency_chain(
    job: JobInfo,
    all_jobs: Dict[str, JobInfo],
    visited: Set[str],
    chain: List[JobInfo],
) -> None:
    """
    Recursively build the full dependency chain for a job.

    Args:
        job: The job to process
        all_jobs: Dict mapping job keys to JobInfo objects
        visited: Set of already visited job keys
        chain: List to append jobs to (in reverse dependency order)
    """
    if job.key in visited:
        return

    visited.add(job.key)

    # First recurse into dependencies
    if job.depends:
        for dep_key in job.depends:
            if dep_key in all_jobs:
                dep_job = all_jobs[dep_key]
                build_dependency_chain(dep_job, all_jobs, visited, chain)

    # Then add this job
    chain.append(job)


def record_sequence(
    jobs_db: JobsBase,
    current_job: JobInfo,
    all_deps: List[JobInfo],
    success_deps: List[JobInfo],
    sequence_name: str,
) -> None:
    """
    Record a sequence including the current job and all its dependencies.

    Replaces any existing sequence with the same name.

    Args:
        jobs_db: JobsBase instance (with _repo attribute)
        current_job: The job being created with --seq flag
        all_deps: List of all dependency jobs (from -b, -B, --wait)
        success_deps: List of success-only dependency jobs (from -B)
        sequence_name: Name of the sequence to record
    """
    validate_sequence_name(sequence_name)

    # Delete existing sequence if it exists (replace behavior)
    if jobs_db.is_sequence(sequence_name):
        jobs_db.delete_sequence(sequence_name)

    # Build mapping: job_key -> (JobInfo, list of direct dep keys)
    # Fetch dependencies from database as they may have been cleared in memory
    job_deps_map: Dict[str, Tuple[JobInfo, List[str]]] = {}

    # Add all dependency jobs and fetch their dependencies from database
    for dep in all_deps:
        # Fetch from database to get persisted dependencies
        dep_domain = jobs_db.get(dep.key)
        dep_depends = (
            list(dep_domain.depends_on)
            if dep_domain and dep_domain.depends_on
            else []
        )
        job_deps_map[dep.key] = (dep, dep_depends)

    # Add current job with its dependencies
    current_deps = [dep.key for dep in all_deps]
    job_deps_map[current_job.key] = (current_job, current_deps)

    # Now traverse transitive dependencies by fetching from database
    # Collect all dependencies that need to be fetched
    to_fetch = set()
    for _, dep_list in job_deps_map.values():
        to_fetch.update(dep_list)
    # Remove jobs we already have
    to_fetch -= set(job_deps_map.keys())

    while to_fetch:
        dep_key = to_fetch.pop()
        if dep_key in job_deps_map:
            continue  # Already processed

        # Fetch the job from database
        dep_job_domain = jobs_db.get(dep_key)
        if dep_job_domain is None:
            continue  # Job not found in database

        # Convert to JobInfo
        dep_job_info = job_to_jobinfo(dep_job_domain, parent=jobs_db)

        # Get its dependencies
        dep_depends = (
            list(dep_job_domain.depends_on) if dep_job_domain.depends_on else []
        )
        job_deps_map[dep_key] = (dep_job_info, dep_depends)

        # Add its dependencies to the fetch queue
        for transitive_dep in dep_depends:
            if transitive_dep not in job_deps_map:
                to_fetch.add(transitive_dep)

    # Topological sort to get execution order
    visited: Set[str] = set()
    chain: List[JobInfo] = []

    def visit(job_key: str):
        if job_key in visited or job_key not in job_deps_map:
            return
        visited.add(job_key)
        job_info, deps_list = job_deps_map[job_key]
        # Visit dependencies first
        for dep_key in deps_list:
            visit(dep_key)
        # Then add this job
        chain.append(job_info)

    # Start from current job and work backwards
    visit(current_job.key)

    # Create mapping from job key to step number (preserving execution order)
    job_to_step: Dict[str, int] = {}
    for i, job in enumerate(chain):
        job_to_step[job.key] = i

    # Determine success dependencies as a set for quick lookup
    success_dep_keys = {dep.key for dep in success_deps}

    # Record each job in the sequence
    for job in chain:
        dependencies: List[Tuple[int, str]] = []

        # Get dependencies from our map (not from job.depends which may be empty)
        job_dep_list = job_deps_map.get(job.key, (None, []))[1]
        for dep_key in job_dep_list:
            if dep_key in job_to_step:
                # This dependency is within our sequence
                dep_step = job_to_step[dep_key]
                dep_type = (
                    DEP_TYPE_SUCCESS
                    if dep_key in success_dep_keys
                    else DEP_TYPE_COMPLETION
                )
                dependencies.append((dep_step, dep_type))

        # Add this step to the sequence
        jobs_db.add_sequence_step(
            name=sequence_name, job_key=job.key, dependencies=dependencies
        )


def get_sequence_replay_plan(
    jobs_db, sequence_name: str
) -> List[Tuple[str, List[str], List[str]]]:
    """
    Get a plan for replaying a sequence.

    Args:
        jobs_db: JobsBase instance (with _repo attribute)
        sequence_name: Name of the sequence to replay

    Returns:
        List of (job_key, completion_deps, success_deps) tuples where:
        - job_key: The original job key to retry
        - completion_deps: List of step numbers to wait for completion (-b)
        - success_deps: List of step numbers to wait for success (-B)

    Raises:
        Exception: If sequence doesn't exist
    """
    validate_sequence_name(sequence_name)

    if not jobs_db.is_sequence(sequence_name):
        raise Exception(
            f"No sequence named '{sequence_name}' found. "
            f"Use 'job --list-seq' to see available sequences"
        )

    steps = jobs_db.get_sequence_steps(sequence_name)

    plan = []
    for _, job_key, dependencies in steps:
        completion_deps = []
        success_deps = []

        for dep_step, dep_type in dependencies:
            if dep_type == DEP_TYPE_SUCCESS:
                success_deps.append(dep_step)
            else:
                completion_deps.append(dep_step)

        plan.append((job_key, completion_deps, success_deps))

    return plan


def replay_sequence_from_main(jobs_db, sequence_name: str, _argv, _config):
    """
    Replay a sequence by invoking job command for each step.

    Args:
        jobs_db: JobsBase instance
        sequence_name: Name of sequence to replay
        argv: Original command-line arguments
        config: Config object
    """
    validate_sequence_name(sequence_name)

    if not jobs_db.is_sequence(sequence_name):
        raise Exception(
            f"No sequence named '{sequence_name}' found. "
            f"Use 'job --list-seq' to see available sequences"
        )

    sprint(f"Replaying sequence '{sequence_name}'")

    steps = jobs_db.get_sequence_steps(sequence_name)

    if not steps:
        sprint(f"Sequence '{sequence_name}' is empty")
        return

    # Mapping from step number to new job key
    step_to_new_key: Dict[int, str] = {}

    for step_num, original_job_key, dependencies in steps:
        # Get the original job to retry
        original_job = jobs_db.get(original_job_key)
        if original_job is None:
            sprint(
                f"Error: Original job '{original_job_key}' not found "
                f"for step {step_num}. Use 'job -l' to list available jobs."
            )
            sys.exit(1)

        # Generate a unique key for this replayed job
        timestamp = int(time.time())
        replay_key = f"replay_{sequence_name}_step{step_num}_{timestamp}"

        # Build command to retry this job with a unique key
        cmd = [sys.argv[0], "--retry", original_job_key, "-k", replay_key]

        # Add dependency flags
        for dep_step, dep_type in dependencies:
            if dep_step not in step_to_new_key:
                sprint(
                    f"Error: Step {step_num} depends on step {dep_step} "
                    f"which hasn't been created yet"
                )
                sys.exit(1)

            dep_key = step_to_new_key[dep_step]
            if dep_type == DEP_TYPE_SUCCESS:
                cmd.extend(["-B", dep_key])
            else:  # completion
                cmd.extend(["-b", dep_key])

        # Execute the job command
        sprint(f"  Step {step_num}: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=False, text=True, check=False)

        if result.returncode != 0:
            sprint(f"Error running step {step_num}")
            sys.exit(result.returncode)

        # Store the known key
        step_to_new_key[step_num] = replay_key
        sprint(f"  Created job: {replay_key}")

    sprint(f"Sequence '{sequence_name}' replayed successfully")
