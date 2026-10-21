#!/usr/bin/env bash
# Proves tests/test_boot_isolation.py is not decorative.
#
# Copies the working tree (tracked + untracked, not ignored) into a temporary clone,
# creates an offline venv there (uv cache only; no network), runs the boot smoke test once
# unmutated (must PASS) and then four times with src/aidashvideo/__init__.py mutated to
#   1. start a thread, 2. open a socket, 3. run a subprocess, 4. inject a fake torch module.
# Each mutated run must FAIL. Exit 0 only when all five expectations hold.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CLONE="$(mktemp -d "${TMPDIR:-/tmp}/aidashvideo-tripwire.XXXXXX")"
trap 'rm -rf "$CLONE"' EXIT
git ls-files -co --exclude-standard -z | while IFS= read -r -d '' f; do
  [[ -e "$f" ]] || continue
  mkdir -p "$CLONE/$(dirname "$f")"
  cp -p "$f" "$CLONE/$f"
done
cd "$CLONE"
export UV_PYTHON_DOWNLOADS=never
uv sync --offline --locked >/dev/null 2>&1   # dev group only, from the uv cache

TEST="tests/test_boot_isolation.py::test_boot_import_isolation"
run_test() { uv run --offline --no-sync pytest -q -p no:cacheprovider "$TEST" >/dev/null 2>&1; }

if run_test; then echo "control (unmutated): PASS (expected)"; else echo "control FAILED"; exit 1; fi

INIT="src/aidashvideo/__init__.py"
cp "$INIT" "$INIT.orig"
declare -a MUTATIONS=(
  $'import threading\nthreading.Thread(target=lambda: None).start()\n'
  $'import socket\nsocket.socket()\n'
  $'import subprocess\nsubprocess.run(["true"], check=False)\n'
  $'import sys, types\nsys.modules["torch"] = types.ModuleType("torch")\n'
)
NAMES=("thread start" "socket" "subprocess call" "fake torch module")
failures=0
for i in "${!MUTATIONS[@]}"; do
  cp "$INIT.orig" "$INIT"
  printf '%s' "${MUTATIONS[$i]}" >> "$INIT"
  if run_test; then
    echo "mutation $((i+1)) (${NAMES[$i]}): test still PASSES -> decorative"
  else
    echo "mutation $((i+1)) (${NAMES[$i]}): test FAILS (expected)"
    failures=$((failures+1))
  fi
done
cp "$INIT.orig" "$INIT"
[[ $failures == 4 ]] && { echo "all 4 mutations detected"; exit 0; }
echo "only $failures/4 mutations detected"; exit 1
