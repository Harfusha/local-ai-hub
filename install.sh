#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE=""
EXPECTED_REVISION=""
CONFIRM_FULL_REINSTALL=""
EXTRA=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile) PROFILE=${2:?missing profile}; shift 2 ;;
    --expected-revision) EXPECTED_REVISION=${2:?missing verified commit SHA}; shift 2 ;;
    --confirm-full-reinstall) CONFIRM_FULL_REINSTALL=${2:?missing exact deletion confirmation}; shift 2 ;;
    --skip-model-pull|--skip-tools|--skip-agent-config|--skip-service|--skip-ollama-install|--skip-local-nlp-preload|--skip-laya-runtime|--skip-ast-index|--skip-performance|--skip-profiling|--skip-token-economy|--skip-companion-skills)
      EXTRA="$EXTRA $1"; shift ;;
    --interactive|--non-interactive|--full-reinstall)
      EXTRA="$EXTRA $1"; shift ;;
    -h|--help)
      echo "Usage: ./install.sh [--expected-revision <40-character-commit-SHA>] [--profile auto|cpu|integrated|low|balanced|medium|high|max] [--interactive|--non-interactive] [--full-reinstall --confirm-full-reinstall 'DELETE <state path>'] [setup skip flags]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ -n "$EXPECTED_REVISION" ]; then
  case "$EXPECTED_REVISION" in
    *[!0-9a-fA-F]*) echo "--expected-revision must be a 40-character verified commit SHA." >&2; exit 2 ;;
  esac
  if [ "${#EXPECTED_REVISION}" -ne 40 ]; then echo "--expected-revision must be a 40-character verified commit SHA." >&2; exit 2; fi
fi
if ! command -v git >/dev/null 2>&1; then echo "Git is required to verify the installer source commit." >&2; exit 2; fi
ACTUAL_REVISION=$(git -C "$ROOT" rev-parse --verify HEAD) || { echo "Could not resolve installer source commit." >&2; exit 2; }
if [ "$(printf '%s' "$ACTUAL_REVISION" | tr '[:upper:]' '[:lower:]')" != "$(printf '%s' "$EXPECTED_REVISION" | tr '[:upper:]' '[:lower:]')" ]; then
  if [ -n "$EXPECTED_REVISION" ]; then echo "Source checkout does not match expected verified commit $EXPECTED_REVISION. Refusing install/update." >&2; exit 2; fi
fi
EXPECTED_REVISION=$ACTUAL_REVISION
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
        brew install python@3.14 || { echo "Python installation failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
      else
        echo "Homebrew is required for automatic Python installation on macOS. Install Python 3.11+ and rerun; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update || { echo "Python package index update failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
        VERSIONED_PYTHON=""
        for candidate in python3.14 python3.13 python3.12 python3.11; do
          if apt-cache show "$candidate" >/dev/null 2>&1 && apt-cache show "$candidate-venv" >/dev/null 2>&1; then
            VERSIONED_PYTHON=$candidate
            break
          fi
        done
        if [ -n "$VERSIONED_PYTHON" ]; then
          as_root apt-get install -y "$VERSIONED_PYTHON" "$VERSIONED_PYTHON-venv" || { echo "Python installation failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
        else
          as_root apt-get install -y python3 python3-venv python3-pip || { echo "Python installation failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
        fi
      elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y python3 python3-pip || { echo "Python installation failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
      elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install python3 python3-pip || { echo "Python installation failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
      elif command -v apk >/dev/null 2>&1; then
        as_root apk add --no-cache python3 py3-pip || { echo "Python installation failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
      elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -S --noconfirm --needed python python-pip || { echo "Python installation failed; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; }
      else
        echo "No supported package manager found. Install Python 3.11+ and rerun; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1
      fi
      ;;
    *) echo "Unsupported bootstrap platform. Install Python 3.11+ and run tools/setup.py; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1 ;;
  esac
  for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then PYTHON=$candidate; break; fi
  done
fi

if [ -z "$PYTHON" ]; then echo "Python 3.11+ installation did not produce a usable interpreter; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2; exit 1; fi
if ! "$PYTHON" -m venv --help >/dev/null 2>&1; then
  echo "Python '$PYTHON' does not provide the stdlib venv module required by Local AI Hub; see $ROOT/docs/INSTALLER_RECOVERY.md." >&2
  exit 1
fi
set -- "$ROOT/tools/setup.py" --expected-revision "$EXPECTED_REVISION"
if [ -n "$PROFILE" ]; then set -- "$@" --profile "$PROFILE"; fi
if [ -n "$CONFIRM_FULL_REINSTALL" ]; then set -- "$@" --confirm-full-reinstall "$CONFIRM_FULL_REINSTALL"; fi
# shellcheck disable=SC2086
exec "$PYTHON" "$@" $EXTRA
