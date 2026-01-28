import json
import os
import sqlite3
from subprocess import CalledProcessError
from unittest import TestCase

from jobrunner.utils import autoDecode

from .integration_lib import getTestEnv, job, run, setUpModuleHelper


def setUpModule():
    setUpModuleHelper()


def get_db_path(env):
    """Get path to the jobs database."""
    return os.path.join(env.tmpDir, "db", "jobs.db")


def get_sequence_steps(env, sequence_name):
    """
    Get sequence steps from database.

    Returns list of (step_number, job_key, dependencies) tuples.
    """
    db_path = get_db_path(env)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all steps
    cursor.execute(
        "SELECT step_number, job_key FROM sequence_steps "
        "WHERE name = ? ORDER BY step_number",
        (sequence_name,),
    )
    steps = cursor.fetchall()

    result = []
    for step_num, job_key in steps:
        # Get dependencies for this step
        cursor.execute(
            "SELECT dependency_step, dependency_type "
            "FROM sequence_dependencies "
            "WHERE name = ? AND step_number = ?",
            (sequence_name, step_num),
        )
        deps = [(row[0], row[1]) for row in cursor.fetchall()]
        result.append((step_num, job_key, deps))

    conn.close()
    return result


def get_job_cmd(env, job_key):
    """Get the command for a job from database."""
    db_path = get_db_path(env)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT cmd_json FROM jobs WHERE key = ?", (job_key,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return json.loads(row[0])


class SequenceTest(TestCase):
    """Test sequence recording and replay functionality."""

    def test_simple_sequence(self):
        """Test recording a simple linear sequence."""
        with getTestEnv() as env:
            # Create a simple sequence
            job("-c", "echo step1")
            job("--sequence", "simple", "-B.", "-c", "echo step2")

            # Verify sequence was recorded
            steps = get_sequence_steps(env, "simple")
            self.assertEqual(2, len(steps))

            # Verify step order and dependencies
            step0_num, step0_key, step0_deps = steps[0]
            step1_num, step1_key, step1_deps = steps[1]

            self.assertEqual(0, step0_num)
            self.assertEqual(1, step1_num)

            # Step 0 has no dependencies
            self.assertEqual([], step0_deps)

            # Step 1 depends on step 0 (success)
            self.assertEqual([(0, "success")], step1_deps)

            # Verify job commands
            cmd0 = get_job_cmd(env, step0_key)
            cmd1 = get_job_cmd(env, step1_key)
            self.assertEqual(["bash", "-c", "echo step1"], cmd0)
            self.assertEqual(["bash", "-c", "echo step2"], cmd1)

    def test_sequence_replacement(self):
        """Test that sequences are replaced, not appended."""
        with getTestEnv() as env:
            # Create initial sequence with 3 steps
            job("-c", "echo old1")
            job("-B.", "-c", "echo old2")
            job("--sequence", "replace_test", "-B.", "-c", "echo old3")

            # Verify initial sequence
            steps = get_sequence_steps(env, "replace_test")
            self.assertEqual(3, len(steps))
            old_keys = [step[1] for step in steps]

            # Create new sequence with same name but different jobs
            job("--sequence", "replace_test", "-c", "echo new")

            # Verify sequence was replaced
            steps = get_sequence_steps(env, "replace_test")
            self.assertEqual(1, len(steps))

            step_num, job_key, deps = steps[0]
            self.assertEqual(0, step_num)
            self.assertEqual([], deps)

            # Verify new job command
            cmd = get_job_cmd(env, job_key)
            self.assertEqual(["bash", "-c", "echo new"], cmd)

            # Verify old job key is not in the sequence
            self.assertNotIn(job_key, old_keys)

    def test_diamond_dependency(self):  # pylint: disable=too-many-locals
        """Test sequence with diamond dependency pattern.

        Creates:
               step0
              /     \\
           step1   step2
              \\     /
               step3
        """
        with getTestEnv() as env:
            # Create step0
            job("-c", "echo step0")
            step0_key = run(["job", "-K"], capture=True).strip()

            # Create step1 depending on step0
            job("-B", step0_key, "-c", "echo step1")
            step1_key = run(["job", "-K"], capture=True).strip()

            # Create step2 depending on step0
            job("-B", step0_key, "-c", "echo step2")
            step2_key = run(["job", "-K"], capture=True).strip()

            # Create step3 depending on both step1 and step2
            job(
                "--sequence",
                "diamond",
                "-B",
                step1_key,
                "-B",
                step2_key,
                "-c",
                "echo step3",
            )

            # Verify sequence structure
            steps = get_sequence_steps(env, "diamond")
            self.assertEqual(4, len(steps))

            # Build map of job_key -> (step_num, deps)
            key_to_step = {step[1]: (step[0], step[2]) for step in steps}

            # Verify step0 has no dependencies
            step0_num, step0_deps = key_to_step[step0_key]
            self.assertEqual([], step0_deps)

            # Verify step1 depends on step0
            # Note: Transitive dependencies are stored with original dep type
            # from the job's depends_on, not re-interpreted
            step1_num, step1_deps = key_to_step[step1_key]
            self.assertEqual(1, len(step1_deps))
            self.assertEqual(step0_num, step1_deps[0][0])

            # Verify step2 depends on step0
            step2_num, step2_deps = key_to_step[step2_key]
            self.assertEqual(1, len(step2_deps))
            self.assertEqual(step0_num, step2_deps[0][0])

            # Verify step3 depends on both step1 and step2
            # Find step3 (the job that's not step0, step1, or step2)
            all_keys = {step[1] for step in steps}
            known_keys = {step0_key, step1_key, step2_key}
            step3_key = (all_keys - known_keys).pop()

            _, step3_deps = key_to_step[step3_key]
            # Sort dependencies for consistent comparison
            step3_deps_sorted = sorted(step3_deps)
            expected_deps = sorted([(step1_num, "success"), (step2_num, "success")])
            self.assertEqual(expected_deps, step3_deps_sorted)

            # Verify the diamond structure through commands
            self.assertEqual(
                ["bash", "-c", "echo step0"], get_job_cmd(env, step0_key)
            )
            self.assertEqual(
                ["bash", "-c", "echo step1"], get_job_cmd(env, step1_key)
            )
            self.assertEqual(
                ["bash", "-c", "echo step2"], get_job_cmd(env, step2_key)
            )

    def test_mixed_dependency_types(self):  # pylint: disable=too-many-locals
        """Test sequence with both success (-B) and completion (-b) deps."""
        with getTestEnv() as env:
            # Create step0
            job("-c", "echo step0")
            step0_key = run(["job", "-K"], capture=True).strip()

            # Create step1 that runs after step0 completes (any exit code)
            job("-b", step0_key, "-c", "echo step1")
            step1_key = run(["job", "-K"], capture=True).strip()

            # Create step2 that runs only after step0 succeeds
            job("-B", step0_key, "-c", "echo step2")
            step2_key = run(["job", "-K"], capture=True).strip()

            # Create step3 with mixed dependencies
            job(
                "--sequence",
                "mixed",
                "-b",
                step1_key,  # completion dependency
                "-B",
                step2_key,  # success dependency
                "-c",
                "echo step3",
            )

            # Verify sequence structure
            steps = get_sequence_steps(env, "mixed")
            self.assertEqual(4, len(steps))

            # Build map of job_key -> (step_num, deps)
            key_to_step = {step[1]: (step[0], step[2]) for step in steps}

            # Get step3 (the final step with mixed dependencies)
            # Find the step that's not step0, step1, or step2
            all_keys = {step[1] for step in steps}
            known_keys = {step0_key, step1_key, step2_key}
            step3_key = (all_keys - known_keys).pop()

            _, step3_deps = key_to_step[step3_key]
            step1_num = key_to_step[step1_key][0]
            step2_num = key_to_step[step2_key][0]

            # Verify mixed dependency types
            step3_deps_sorted = sorted(step3_deps)
            expected_deps = sorted(
                [(step1_num, "completion"), (step2_num, "success")]
            )
            self.assertEqual(expected_deps, step3_deps_sorted)

    def test_long_chain(self):
        """Test sequence with a long dependency chain."""
        with getTestEnv() as env:
            # Create a chain of 5 jobs
            job("-c", "echo step1")

            for i in range(2, 6):
                job("-B.", "-c", f"echo step{i}")

            # Add final job to sequence
            job("--sequence", "long_chain", "-B.", "-c", "echo step6")

            # Verify sequence has all 6 steps
            steps = get_sequence_steps(env, "long_chain")
            self.assertEqual(6, len(steps))

            # Verify linear dependency chain
            for i, (step_num, _, deps) in enumerate(steps):
                self.assertEqual(i, step_num)

                if i == 0:
                    # First step has no dependencies
                    self.assertEqual([], deps)
                else:
                    # Each subsequent step depends on the previous one
                    self.assertEqual(1, len(deps))
                    self.assertEqual(i - 1, deps[0][0])

    def test_replay_sequence(self):
        """Test replaying a recorded sequence."""
        with getTestEnv() as env:
            # Create a simple sequence
            job("-c", "echo original1")
            job("--sequence", "replay_test", "-B.", "-c", "echo original2")

            # Get original job count
            db_path = get_db_path(env)
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs")
            original_count = cursor.fetchone()[0]
            conn.close()

            # Replay the sequence
            run(["job", "--retry", "replay_test"])

            # Verify new jobs were created
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs")
            new_count = cursor.fetchone()[0]
            conn.close()

            # Should have 2 more jobs (the replayed sequence)
            self.assertEqual(original_count + 2, new_count)

    def test_sequence_name_validation(self):
        """Test that invalid sequence names are rejected."""
        with getTestEnv() as env:
            # Test name with spaces - should fail
            with self.assertRaises(CalledProcessError) as error:
                run(
                    ["job", "--sequence", "bad name", "-c", "echo test"],
                    capture=True,
                )
            output = autoDecode(error.exception.output)
            self.assertIn("can only contain", output.lower())

            # Test name with special characters - should fail
            with self.assertRaises(CalledProcessError) as error:
                run(
                    ["job", "--sequence", "bad@name!", "-c", "echo test"],
                    capture=True,
                )
            output = autoDecode(error.exception.output)
            self.assertIn("can only contain", output.lower())

            # Test valid name works
            job("--sequence", "valid_name-1.0", "-c", "echo test")
            steps = get_sequence_steps(env, "valid_name-1.0")
            self.assertEqual(1, len(steps))

    def test_replay_nonexistent_sequence(self):
        """Test that replaying nonexistent sequence fails gracefully."""
        with getTestEnv():
            # When trying to replay something that doesn't exist,
            # it will fail with "No job for key" error since it's not
            # recognized as a sequence
            with self.assertRaises(CalledProcessError) as error:
                run(["job", "--retry", "nonexistent_seq"], capture=True)
            # Error message should indicate the key doesn't exist
            output = autoDecode(error.exception.output).lower()
            self.assertIn("no job for key", output)

    def test_sequence_with_missing_original_job(self):
        """Test replay when original job no longer exists."""
        # This is a data integrity test - should rarely happen in practice
        # but good to handle gracefully
        with getTestEnv() as env:
            # Create and record a sequence
            job("-c", "echo step1")
            job("--sequence", "test_missing", "-B.", "-c", "echo step2")

            # Manually delete one of the original jobs from database
            db_path = get_db_path(env)
            steps = get_sequence_steps(env, "test_missing")
            first_job_key = steps[0][1]

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE key = ?", (first_job_key,))
            conn.commit()
            conn.close()

            # Try to replay - should fail with helpful error
            with self.assertRaises(CalledProcessError) as error:
                run(["job", "--retry", "test_missing"], capture=True)
            # Should mention the missing job
            output = autoDecode(error.exception.output)
            self.assertIn(first_job_key, output)
