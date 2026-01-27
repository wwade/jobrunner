# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`jobrunner` (published as `shell-jobrunner`) is a Python-based job runner with logging capabilities. It allows users to run shell commands in the background, track their execution, monitor progress, and receive notifications upon completion. Jobs can be configured to depend on other jobs, retry failed commands, and send notifications via email or chat applications.

## Development Commands

### Initial Setup
```bash
# Install Poetry (if not already installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install --all-extras
```

### Code Formatting
```bash
# Format and lint code (required before commits)
./format.sh

# Or with poetry
poetry run ./format.sh
```

### Running Tests

**Recommended: Full test suite (like CI)**
```bash
./test.sh
```
This script automatically handles poetry setup, runs all linters, installs the package, and runs pytest with recommended options. Use this before committing.

**Quick test run (if already in poetry env):**
```bash
make check        # Just run tests, skip linting
make all          # Lint + install + test
```

**Manual pytest (most flexible):**
```bash
# Run all tests with details
poetry run pytest -v -l --durations=10 jobrunner/

# Run a specific test file
poetry run pytest jobrunner/test/config_test.py

# Run a specific test
poetry run pytest jobrunner/test/config_test.py::TestClassName::test_method_name
```

**Other Makefile targets:**
```bash
make lint         # Run all linters only
make install      # Install package
make format       # Format code (./format.sh)
```

### Local CI Testing
```bash
# Test across multiple Python versions using Docker
./test-docker.py [--versions 3.9 3.10 3.11] [--upgrade] [--ignore-unclean]
```

## Architecture

### Core Components

**Entry Points:**
- `job` - Main CLI command (jobrunner/main.py:main)
- `chatmail` - Chat notification utility (jobrunner/mail/chat.py:main)

**Database Layer:**
- `jobrunner/repository/` - Repository pattern implementation for job persistence
  - `sqlite_repository.py` - SQLite3-based relational storage for jobs
  - Jobs are stored in SQLite database in `~/.local/share/job/` (Linux) or platform-specific data directory
  - Database schema has four tables: jobs, metadata, sequence_steps, sequence_dependencies
  - Job dependencies stored in `depends_on_json` column only (derived `all_deps` field is not persisted)
  - Recent optimizations: schema init fast path, query optimization with IN clauses, --list-keys optimization
- Legacy `jobrunner/db/` - Old database abstraction (being phased out)

**Plugin System:**
- `jobrunner/plugins.py` - Plugin manager that discovers and loads plugins
- Plugins registered via `wwade.jobrunner` entrypoint
- Plugin functions: `getResources()`, `workspaceIdentity()`, `workspaceProject()`, `priority()`
- Plugins execute in priority order (lower number = higher priority)
- Old-style plugins in `jobrunner/plugin/` directory are deprecated but still supported

**Service Registry:**
- `jobrunner/service/registry.py` - Dependency injection container
- Registers database implementations and job info handlers
- Used throughout codebase via `service()` calls

**Configuration:**
- Default config file: `~/.config/jobrc`
- Config format documented in `jobrunner/config.py:RC_FILE_HELP`
- Supports mail notifications, chat integration (Google Chat), and UI preferences

**Job Information:**
- `jobrunner/domain/job.py:Job` - Pure domain model representing a job (new architecture)
- `jobrunner/info.py:JobInfo` - Legacy job data structure (being phased out)
- Tracks: command, status, dependencies, timing, output location, working directory, isolation mode
- Jobs identified by numeric ID or pattern matching (command name, regex)
- Dependencies: `depends_on` (list) stores all dependency keys; `all_deps` (set) is derived from it

### Key Workflows

**Running a Job:**
1. Command parsed in `main.py:parseArgs()`
2. Config loaded from rcfile
3. Database connection established via service registry
4. Job created with dependencies resolved
5. Command executed in subprocess with output redirected to log file
6. Job status tracked in database

**Finding Jobs:**
- `-F <KEYWORD>`, `--find <KEYWORD>` - Find all jobs matching the keyword
- Returns both active and inactive jobs, with active jobs listed first
- Can be combined with `-p` flag to filter by checkpoint (show only jobs after checkpoint)
- Similar to `-s` (which returns a single job), but returns all matches in list order

**Job Dependencies:**
- `-b<job>` - Run after job completes (any exit code)
- `-B<job>` - Run after job succeeds (exit code 0)
- `.` is an alias for the most recent job

**Job Sequences:**
- `--retry <KEY>` - Record a job and its dependencies as a replayable sequence
- `--list-sequences` - List all saved sequences
- `--delete-sequence <NAME>` - Delete a saved sequence
- Sequences allow recording a chain of jobs with their dependencies and replaying them later
- Sequence names can contain letters, numbers, underscores, hyphens, and dots (max 255 chars)
- When replaying a sequence, jobs are executed in dependency order

**Notifications:**
- Mail program specified in config (standard `mail` or `chatmail`)
- `chatmail` enables Google Chat integration with thread reuse and @mentions
- `--notifier` mode accepts JSON on stdin for system notification integration

## Code Style Requirements

- Python 3.9+ minimum version
- Line length: 85 characters (enforced by flake8/pycodestyle)
- Use `isort` for import ordering
- Use `autopep8` for formatting
- All code must pass `pylint` checks (except `fixme` warnings)
- `compat.py` is exempt from flake8 checks (compatibility layer)

## Testing Notes

- Tests located in `jobrunner/test/`
- Integration tests in `jobrunner/test/integration/`
- Test helpers in `jobrunner/test/helpers.py`
- Integration tests use helper scripts: `dump_json_input.py`, `send_email.py`, `await_file.py`
- Service registry must be cleared for testing: `registerServices(testing=True)`

### Writing Clean Tests

**Use assertEqual for Collection Comparisons:**
When testing collections, use `assertEqual` to directly compare lists instead of checking length and individual items separately. This is more concise and asserts both content AND order in a single assertion.

```python
# Good: Single assertion checks length, content, and order
matches = self.repo.find_matching("test")
self.assertEqual(["job2", "job1"], [job.key for job in matches])

# Avoid: Multiple assertions, verbose, doesn't verify order
matches = self.repo.find_matching("test")
self.assertEqual(len(matches), 2)
match_keys = [job.key for job in matches]
self.assertIn("job1", match_keys)
self.assertIn("job2", match_keys)
```

Benefits:
- Single line instead of 3-4 lines
- Verifies exact order, not just membership
- Clear test failures showing expected vs actual
- Less boilerplate code

**Extract to Helper Methods When Repeated:**
If you're doing the same collection transformation multiple times in a test, extract it to a helper method:

```python
class TestSqliteJobRepository(unittest.TestCase):
    def assertMatchingJobs(self, expected: Iterable[str], matches: Iterable[Job]) -> None:
        """Assert that matches contain exactly the expected job keys in order."""
        self.assertEqual(expected, [job.key for job in matches])

    def test_find_matching(self):
        matches = self.repo.find_matching("test")
        self.assertMatchingJobs(["job2", "job1"], matches)
```

## Important Patterns

**Logging:**
- Use standard Python logging via `jobrunner.logging`
- Debug logs go to `~/.local/share/job/jobrunner-debug`

**Profiling:**
- Set `JOBRUNNER_PROFILE=1` environment variable to enable performance profiling
- Outputs timing checkpoints to measure startup and query performance
- Useful for identifying performance bottlenecks in database operations

**Database Access:**
- Always access via service registry: `service().db.jobs(config, plugins)`
- Use `lockedSection(jobs)` context manager for thread safety

**Plugin Development:**
- Register via setuptools entry_point `wwade.jobrunner`
- Raise `NotImplementedError` when plugin cannot provide a value
- Return values from higher priority plugins take precedence
