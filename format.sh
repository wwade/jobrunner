#!/bin/bash
set -xe
FILESPEC=(jobrunner test-docker.py)
isort --atomic "${FILESPEC[@]}"
autopep8 -j32 -rai "${FILESPEC[@]}"
pylint "${FILESPEC[@]}"
