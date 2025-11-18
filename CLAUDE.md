# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`jobrunner` (published as `shell-jobrunner`) is a Python-based job runner with logging capabilities. It allows users to run shell commands in the background, track their execution, monitor progress, and receive notifications upon completion. Jobs can be configured to depend on other jobs, retry failed commands, and send notifications via email or chat applications.

## Development Commands

### Initial Setup
```bash
# Create virtualenv and install development dependencies
pipenv --three install --dev
pipenv run pip install -e .
```

### Code Formatting
```bash
# Format and lint code (required before commits)
./format.sh

# Or within pipenv
pipenv run ./format.sh
```

### Running Tests

**Recommended: Full test suite (like CI)**
```bash
./test.sh
```
This script automatically handles pipenv setup, runs all linters, installs the package, and runs pytest with recommended options. Use this before committing.

**Quick test run (if already in virtualenv):**
```bash
make check        # Just run tests, skip linting
make all          # Lint + install + test
```

**Manual pytest (most flexible):**
```bash
# Run all tests with details
pipenv run pytest -v -l --durations=10 jobrunner/

# Run a specific test file
pipenv run pytest jobrunner/test/config_test.py

# Run a specific test
pipenv run pytest jobrunner/test/config_test.py::TestClassName::test_method_name
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
- `jobrunner/db/` - Database abstraction with SQLite implementation
  - `sqlite_db.py` - SQLite3-based key-value store for job metadata
  - Jobs are stored in SQLite database in `~/.local/share/job/` (Linux) or platform-specific data directory
  - Database schema uses two tables: one for jobs, one for metadata

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
- `jobrunner/info.py:JobInfo` - Core data structure representing a job
- Tracks: command, status, dependencies, timing, output location, working directory, isolation mode
- Jobs identified by numeric ID or pattern matching (command name, regex)

### Key Workflows

**Running a Job:**
1. Command parsed in `main.py:parseArgs()`
2. Config loaded from rcfile
3. Database connection established via service registry
4. Job created with dependencies resolved
5. Command executed in subprocess with output redirected to log file
6. Job status tracked in database

**Job Dependencies:**
- `-b<job>` - Run after job completes (any exit code)
- `-B<job>` - Run after job succeeds (exit code 0)
- `.` is an alias for the most recent job

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

## Important Patterns

**Logging:**
- Use standard Python logging via `jobrunner.logging`
- Debug logs go to `~/.local/share/job/jobrunner-debug`

**Database Access:**
- Always access via service registry: `service().db.jobs(config, plugins)`
- Use `lockedSection(jobs)` context manager for thread safety

**Plugin Development:**
- Register via setuptools entry_point `wwade.jobrunner`
- Raise `NotImplementedError` when plugin cannot provide a value
- Return values from higher priority plugins take precedence
