#!/bin/sh
set -xe
FILESPEC="job setup.py jobrunner"
isort -y -ac -rc $FILESPEC
autopep8 -j32 -rai $FILESPEC
pylint $FILESPEC
