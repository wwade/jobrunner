#!/bin/bash
cd "$(dirname "$0")" || exit 1
set -xeuo pipefail
PY=$(python -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))")

# Check if poetry is installed
if ! command -v poetry &> /dev/null; then
    echo "Poetry not found, installing..."
    python -m pip install --upgrade pip
    python -m pip install poetry
fi

poetry --version

# Install dependencies
poetry install --all-extras

FILES=(setup.py jobrunner)
if [[ "$PY" =~ 3\. ]]
then
    FILES+=("test-docker.py")
fi
poetry run isort -c --diff -rc "${FILES[@]}"
poetry run autopep8 --exit-code -ra --diff "${FILES[@]}"
poetry run pylint -d fixme "${FILES[@]}"
find jobrunner -type f -name "*.py" -not -name "compat.py" | xargs poetry run flake8 setup.py

poetry run pip install .

poetry run pytest -v -l --junitxml=junit/test-results.xml --durations=10 jobrunner/
