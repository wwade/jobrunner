#!/bin/bash
set -xe
FILESPEC=(
   jobrunner_git
)
isort --atomic "${FILESPEC[@]}"
black "${FILESPEC[@]}"
pylint "${FILESPEC[@]}"
mypy --strict "${FILESPEC[@]}"
