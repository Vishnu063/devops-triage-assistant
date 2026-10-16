#!/usr/bin/env bash
# Install into a private project environment once, then launch the assistant.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_dir"

if [[ "$(uname -s)" != Linux ]]; then
    echo 'This launcher requires Linux. On Windows, run it inside WSL (Ubuntu).' >&2
    exit 1
fi

python_bin="${TRIAGE_PYTHON:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
    echo 'Python 3.11+ is required. Install Python, then run bash start.sh again.' >&2
    exit 1
fi
if ! "$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo 'Python 3.11+ is required. Set TRIAGE_PYTHON to a supported Python executable.' >&2
    exit 1
fi

venv_dir="$project_dir/.venv"
if [[ ! -x "$venv_dir/bin/python" ]]; then
    echo 'Creating the local Python environment...'
    if ! "$python_bin" -m venv "$venv_dir"; then
        echo 'Could not create the environment. On Ubuntu/Debian, install the matching python3-venv package and retry.' >&2
        exit 1
    fi
fi
if [[ ! -x "$venv_dir/bin/devops-triage" ]]; then
    echo 'Installing DevOps Triage Assistant (first run needs internet access)...'
    if ! "$venv_dir/bin/python" -m pip install --disable-pip-version-check --no-deps -e "$project_dir"; then
        echo 'Installation failed. Check your internet connection and pip output, then retry bash start.sh.' >&2
        exit 1
    fi
fi

if [[ $# -eq 0 ]]; then
    set -- web
fi
exec "$venv_dir/bin/devops-triage" "$@"
