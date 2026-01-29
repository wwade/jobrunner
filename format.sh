#!/bin/bash
set -xe
FILESPEC=(jobrunner test-docker.py)
poetry run ruff format "${FILESPEC[@]}"
poetry run ruff check --fix "${FILESPEC[@]}"
