#!/bin/bash
pip install --upgrade nose-cov
COVDIR="$HOME/tmp/jobrunner-coverage"
mkdir -p "$COVDIR"
nosetests -v -e integration --cover-erase --cover-inclusive --with-coverage --cover-html-dir="$COVDIR" --cover-html "$@"
echo "Coverage report dir: ${COVDIR}/index.html"
