#!/bin/bash
set -euo pipefail
py38=(3.8 "Pipfile-3.8.lock")
py27=(2.7 "Pipfile-2.7.lock")
py37=(3.7 "Pipfile.lock")
VERSIONS=(
    'py38[@]'
    'py27[@]'
    'py37[@]'
)

PIPCONF=(
    "${HOME}/.config/pip/pip.conf"
    "/etc/pip.conf"
    "${HOME}/.pip/pip.conf"
)

function assertClean {
    out=$(git status -s --porcelain "$1")
    if [[ -n "$out" ]]; then
        echo "$1 will be overwritten and is currently unclean."
        echo
        exit 1
    fi
}

assertClean "Pipfile.lock"
assertClean "Pipfile"

pipConf=/dev/null
for conf in "${PIPCONF[@]}"; do
    if [[ -r "$conf" ]]; then
        pipConf=$conf
        break
    fi
done

set -x
for pyInfo in "${VERSIONS[@]}"; do
    python=""
    for x in "${!pyInfo}"; do
        if [[ -z "$python" ]]; then
            python=$x
        else
            pipLock=$x
        fi
    done
    assertClean "$pipLock"
    base="$PWD/docker-${python}"
    mkdir -p "${base}"/home/me/{.cache,.local}/
    if [[ "$pipLock" != "Pipfile.lock" ]]; then
        cp -v "$pipLock" Pipfile.lock
    fi
    if [[ "$python" != "3.7" ]]; then
        sed -i 's/python_version\s*=\s*\S*/python_version = "'"${python}"'"/' Pipfile
    fi
    docker run --rm \
           -v "$PWD":/src \
           -v "${base}/home:/home" \
           -v "${pipConf}:/etc/pip.conf" \
           -v "${HOME}/.cache:/home/me/.cache" \
           -e HOME=/home/me \
           -e _NEW_UID=$(id -u) \
           -e _NEW_GID=$(id -g) \
           -e PIP_INDEX_URL="${PIP_INDEX_URL:-}" \
           python:"$python" \
           /src/test-docker-helper.sh

    if [[ "$pipLock" != "Pipfile.lock" ]]; then
        cp -v Pipfile.lock "$pipLock"
        git checkout Pipfile
        git checkout Pipfile.lock
    fi
done
echo "All tests passed [exit=$?]"
