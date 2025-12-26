#!/usr/bin/env bash
set -euo pipefail

# Installs the Android UiAutomator2 driver for Appium 2.
#
# Usage:
#   ./scripts/install-appium-uiautomator2.sh
#
# Env:
#   NODE_VERSION=20

NODE_VERSION="${NODE_VERSION:-20}"

if command -v fnm >/dev/null 2>&1; then
  exec fnm exec --using="${NODE_VERSION}" npx --yes appium@latest driver install uiautomator2
fi

echo "fnm is not installed; running appium with the current Node runtime." 1>&2
exec npx --yes appium@latest driver install uiautomator2

