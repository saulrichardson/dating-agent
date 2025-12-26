#!/usr/bin/env bash
set -euo pipefail

# Starts an Appium 2 server locally using Node 20 via fnm.
#
# Usage:
#   ./scripts/start-appium-server.sh
#
# Env:
#   APPIUM_PORT=4723
#   NODE_VERSION=20
#   ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools

NODE_VERSION="${NODE_VERSION:-20}"
APPIUM_PORT="${APPIUM_PORT:-4723}"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/opt/homebrew/share/android-commandlinetools}"

export ANDROID_SDK_ROOT
export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT}}"

# Help Appium find adb/emulator even if the user didn't modify PATH globally.
export PATH="${ANDROID_SDK_ROOT}/platform-tools:${ANDROID_SDK_ROOT}/emulator:${PATH}"

if command -v fnm >/dev/null 2>&1; then
  exec fnm exec --using="${NODE_VERSION}" npx --yes appium@latest server --port "${APPIUM_PORT}"
fi

echo "fnm is not installed; running appium with the current Node runtime." 1>&2
exec npx --yes appium@latest server --port "${APPIUM_PORT}"

