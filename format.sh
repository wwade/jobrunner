#!/bin/sh
set -xe
FILESPEC=(setup.py jobrunner)
isort --atomic "${FILESPEC[@]}"
autopep8 -j32 -rai "${FILESPEC[@]}"
pylint "${FILESPEC[@]}"
