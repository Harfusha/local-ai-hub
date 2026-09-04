#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE=auto
EXTRA=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile) PROFILE=${2:?missing profile}; shift 2 ;;
    --skip-model-pull|--skip-tools|--skip-agent-config|--skip-service|--skip-ollama-install|--skip-local-nlp-preload)
      EXTRA="$EXTRA $1"; shift ;;
    -h|--help)
      echo "Usage: ./install.sh [--profile auto|cpu|low|balanced|high|max] [setup skip flags]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1
}

PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
    PYTHON=$candidate
    break
  fi
done

as_root() {
  if [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Administrator privileges are required to install Python automatically." >&2
    return 1
  fi
}

if [ -z "$PYTHON" ]; then
  echo "[local-ai-hub] Python 3.11+ not found; attempting platform package-manager installation."
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install python@3.14
      else
        echo "Homebrew is required for automatic Python installation on macOS. Install Python 3.11+ and rerun." >&2; exit 1
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update && as_root apt-get install -y python3 python3-venv python3-pip
      elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y python3 python3-pip
      elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install python3 python3-pip
      elif command -v apk >/dev/null 2>&1; then
        as_root apk add --no-cache python3 py3-pip
      elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -S --noconfirm --needed python python-pip
      else
        echo "No supported package manager found. Install Python 3.11+ and rerun." >&2; exit 1
      fi
      ;;
    *) echo "Unsupported bootstrap platform. Install Python 3.11+ and run tools/setup.py." >&2; exit 1 ;;
  esac
  for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then PYTHON=$candidate; break; fi
  done
fi

if [ -z "$PYTHON" ]; then echo "Python 3.11+ installation did not produce a usable interpreter." >&2; exit 1; fi
if ! "$PYTHON" -m venv --help >/dev/null 2>&1; then
  echo "Python '$PYTHON' does not provide the stdlib venv module required by Local AI Hub." >&2
  exit 1
fi
# shellcheck disable=SC2086
exec "$PYTHON" "$ROOT/tools/setup.py" --profile "$PROFILE" $EXTRA
