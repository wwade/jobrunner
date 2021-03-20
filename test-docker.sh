#!/bin/bash
set -euo pipefail
py27=(2.7 "Pipfile-2.7.lock")
py37=(3.7 "Pipfile.lock")
VERSIONS=(
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
    sed -i 's/\(python_version\s*=.*\)[[:digit:]]\.[[:digit:]]/\1'"${python}/" Pipfile
    docker run --rm -i \
           -v "$PWD":/src \
           -v "${base}/home:/home" \
           -v "${pipConf}:/etc/pip.conf" \
           -v "${HOME}/.cache:/home/me/.cache" \
           -e HOME=/home/me \
           -e _NEW_UID=$(id -u) \
           -e _NEW_GID=$(id -g) \
           -e PIP_INDEX_URL="${PIP_INDEX_URL:-}" \
           python:"$python" \
           sh -uex << 'EOF'
cat /etc/pip.conf
useradd --no-create-home --uid $_NEW_UID me
su -c "bash" me << '__2EOF'
   set -uxeo pipefail
   PATH="${PATH}:${HOME}/.local/bin"
   export PATH
   export PIP_INDEX_URL="$PIP_INDEX_URL"
   /src/test.sh
__2EOF
EOF

    if [[ "$pipLock" != "Pipfile.lock" ]]; then
        cp -v Pipfile.lock "$pipLock"
        git checkout Pipfile
        git checkout Pipfile.lock
    fi
done
