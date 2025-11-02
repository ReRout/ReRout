#!/usr/bin/env bash
set -euo pipefail

if ! command -v lsof >/dev/null 2>&1; then
  echo "lsof not found; please install it (macOS: brew install lsof)." >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <port> [port ...]" >&2
  exit 1
fi

for port in "$@"; do
  echo "Checking port ${port}..."
  pids=$(lsof -ti :"${port}" || true)
  if [ -n "${pids}" ]; then
    echo "Killing PIDs on port ${port}: ${pids}"
    kill -9 ${pids} || true
  else
    echo "No process on port ${port}."
  fi
done

echo "Done."
