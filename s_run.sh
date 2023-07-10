#!/bin/bash
set -eu

if [ ! -d ".venv" ]; then
    echo "run s_install.sh first"
    exit 1
fi

source .venv/bin/activate
python3 main.py $@
