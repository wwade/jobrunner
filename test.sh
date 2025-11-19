#!/bin/bash
cd "$(dirname "$0")" || exit 1
set -xeuo pipefail

# Check if poetry is installed
if ! command -v poetry &> /dev/null; then
    echo "Poetry not found, installing..."
    pip install poetry
    if command -v asdf &> /dev/null; then
        asdf reshim
    fi
fi

poetry --version

# Install dependencies
poetry install --all-groups
poetry run make
