#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${ANDROID_HOME:-}" ]]; then
  if [[ -d "$HOME/Android/Sdk" ]]; then export ANDROID_HOME="$HOME/Android/Sdk"
  elif [[ -d "$HOME/android-sdk" ]]; then export ANDROID_HOME="$HOME/android-sdk"
  else echo "Set ANDROID_HOME to your installed Android SDK." >&2; exit 1
  fi
fi
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
cd "$ROOT/android"
exec ./gradlew --no-daemon assembleDebug
