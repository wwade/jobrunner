#!/bin/bash
set -xe
FILESPEC=(setup.py jobrunner test-docker.py)
isort --atomic "${FILESPEC[@]}"
autopep8 -j32 -rai "${FILESPEC[@]}"
pylint "${FILESPEC[@]}"
