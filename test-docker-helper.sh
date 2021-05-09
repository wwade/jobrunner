#!/bin/bash
cd "$(dirname $0)"
set -xeuo pipefail
cat /etc/pip.conf
useradd --no-create-home --uid $_NEW_UID me
su -c bash me << 'EOF'
   set -uxeo pipefail
   PATH="${PATH}:${HOME}/.local/bin"
   export PATH
   export PIP_INDEX_URL="$PIP_INDEX_URL"
   export PIPENV_CMD="$PIPENV_CMD"
   /src/test.sh
EOF
