#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE=auto
EXPECTED_REVISION=""
EXTRA=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile) PROFILE=${2:?missing profile}; shift 2 ;;
    --expected-revision) EXPECTED_REVISION=${2:?missing verified commit SHA}; shift 2 ;;
    --skip-model-pull|--skip-tools|--skip-agent-config|--skip-service|--skip-ollama-install|--skip-local-nlp-preload|--skip-token-economy|--skip-companion-skills)
      EXTRA="$EXTRA $1"; shift ;;
    -h|--help)
      echo "Usage: ./install.sh --expected-revision <40-character-commit-SHA> [--profile auto|cpu|integrated|low|balanced|high|max] [setup skip flags]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$EXPECTED_REVISION" in
  *[!0-9a-fA-F]*|"") echo "--expected-revision must be a 40-character verified commit SHA." >&2; exit 2 ;;
esac
if [ "${#EXPECTED_REVISION}" -ne 40 ]; then echo "--expected-revision must be a 40-character verified commit SHA." >&2; exit 2; fi
if ! command -v git >/dev/null 2>&1; then echo "Git is required to verify the installer source commit." >&2; exit 2; fi
ACTUAL_REVISION=$(git -C "$ROOT" rev-parse --verify HEAD) || { echo "Could not resolve installer source commit." >&2; exit 2; }
if [ "$(printf '%s' "$ACTUAL_REVISION" | tr '[:upper:]' '[:lower:]')" != "$(printf '%s' "$EXPECTED_REVISION" | tr '[:upper:]' '[:lower:]')" ]; then
  echo "Source checkout does not match expected verified commit $EXPECTED_REVISION. Refusing install/update." >&2; exit 2
fi
SOURCE_STATUS=$(git -C "$ROOT" status --porcelain=v1 --untracked-files=all) || { echo "Could not inspect installer source status. Refusing install/update." >&2; exit 2; }
if [ -n "$SOURCE_STATUS" ]; then
  echo "Source checkout is dirty. Preserve changes, use the verified clean commit, then rerun install/update." >&2; exit 2
fi
echo "[local-ai-hub] Verified clean source commit: $ACTUAL_REVISION"

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
exec "$PYTHON" "$ROOT/tools/setup.py" --expected-revision "$EXPECTED_REVISION" --profile "$PROFILE" $EXTRA
