#!/bin/bash
cd "$(dirname "$0")" || exit 1
set -xeuo pipefail
PY=$(python -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))")
python -m pip install --upgrade pip setuptools wheel pipenv
set +x
mirrorUrl=$(pip config list | grep index-url | cut -d= -f2 | cut -d\' -f2 || true)
mirror=()
if [[ -n "$mirrorUrl" ]]; then
    mirrorUrl=${mirrorUrl/[[:space:]]/}
    echo "mirrorUrl: $mirrorUrl"
    mirror+=(--pypi-mirror="$mirrorUrl")
fi
echo mirror: "${mirror[@]}"
set -x

pipenv=(python -m pipenv)

"${pipenv[@]}" --python "$PY" "${PIPENV_CMD:-sync}" "${mirror[@]}" --dev --keep-outdated

FILES=(setup.py jobrunner)
if [[ "$PY" =~ 3\. ]]
then
    FILES+=("test-docker.py")
fi
"${pipenv[@]}" run isort -c --diff -rc "${FILES[@]}"
"${pipenv[@]}" run autopep8 --exit-code -ra --diff "${FILES[@]}"
"${pipenv[@]}" run pylint -d fixme "${FILES[@]}"
find jobrunner -type f -name "*.py" -not -name "compat.py" | xargs "${pipenv[@]}" run flake8 setup.py

"${pipenv[@]}" run pip install .

"${pipenv[@]}" run pytest -v -l --junitxml=junit/test-results.xml --durations=10 jobrunner/
