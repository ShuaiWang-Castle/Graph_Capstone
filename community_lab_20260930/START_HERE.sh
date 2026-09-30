#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
"$PYTHON" tools/session.py start
"$PYTHON" tools/lab.py doctor
"$PYTHON" tools/lab.py selftest
"$PYTHON" tools/lab.py make-smoke
"$PYTHON" tools/check_anchor_capacity.py
printf '\nInfrastructure checks finished. Continue with GOAL_MODE_PROMPT_ZH.md.\n'
printf 'This script does not install native baselines or run the benchmark automatically.\n'
