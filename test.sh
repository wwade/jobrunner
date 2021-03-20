#!/bin/bash
cd "$(dirname $0)"
set -xeuo pipefail
PY=$(python -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))")
python -m pip install --upgrade pip setuptools wheel pipenv
set +x
mirrorUrl=$(pip config list | grep index-url | cut -d= -f2 | cut -d\' -f2)
mirror=""
if [[ -n "$mirrorUrl" ]]; then
    mirrorUrl=${mirrorUrl/[[:space:]]/}
    echo "mirrorUrl: $mirrorUrl"
    mirror="--pypi-mirror=$mirrorUrl"
fi
echo "mirror: $mirror"
set -x
pipenv --python "$PY" install "${mirror}" --dev

FILES=(setup.py jobrunner)
pipenv run isort -c --diff -rc "${FILES[@]}"
pipenv run autopep8 --exit-code -ra --diff "${FILES[@]}"
pipenv run pylint -d fixme "${FILES[@]}"

pipenv run pip install .

pipenv run pytest -v -l --junitxml=junit/test-results.xml --durations=10 jobrunner/
