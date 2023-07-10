#!/bin/bash
set -eu

if [ ! -d ".venv" ]; then
    echo "run s_install.sh first"
    exit 1
fi

source .venv/bin/activate
mypy --strict main.py
black main.py
isort --profile black main.py
