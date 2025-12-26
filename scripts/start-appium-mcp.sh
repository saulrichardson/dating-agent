#!/usr/bin/env bash
set -euo pipefail

# Starts the Appium MCP server (stdio transport) using Node 20 via fnm.
#
# Why Node 20:
# - We observed module-resolution errors running appium-mcp under Node 24 on this machine.
#
# Usage:
#   ./scripts/start-appium-mcp.sh
#
# Optional:
#   NODE_VERSION=20 ./scripts/start-appium-mcp.sh

NODE_VERSION="${NODE_VERSION:-20}"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/opt/homebrew/share/android-commandlinetools}"

export ANDROID_SDK_ROOT
export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT}}"
export PATH="${ANDROID_SDK_ROOT}/platform-tools:${ANDROID_SDK_ROOT}/emulator:${PATH}"

if command -v fnm >/dev/null 2>&1; then
  exec fnm exec --using="${NODE_VERSION}" npx --yes appium-mcp@latest
fi

cat <<'EOF' 1>&2
fnm is not installed, so this script can't force Node 20.

Install fnm (recommended), then re-run:
  brew install fnm

Or run appium-mcp with a Node 20 runtime:
  npx --yes appium-mcp@latest
EOF
exit 1
