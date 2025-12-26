#!/usr/bin/env bash
set -euo pipefail

# Starts the Android emulator for local Appium automation.
#
# Defaults are chosen to match the setup we bootstrap via sdkmanager/avdmanager.
#
# Usage:
#   ./scripts/start-android-emulator.sh
#   AVD_NAME=concierge_api34_play ./scripts/start-android-emulator.sh
#
# Notes:
# - This launches a GUI emulator window (recommended for early prototyping).
# - For Hinge, you likely need a Google Play image + Play Store sign-in.

ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/opt/homebrew/share/android-commandlinetools}"
AVD_NAME="${AVD_NAME:-concierge_api34_play}"

EMULATOR_BIN="${ANDROID_SDK_ROOT}/emulator/emulator"
if [[ ! -x "${EMULATOR_BIN}" ]]; then
  echo "ERROR: Android emulator binary not found at: ${EMULATOR_BIN}" 1>&2
  echo "Expected ANDROID_SDK_ROOT to point at an Android SDK with the 'emulator' package installed." 1>&2
  exit 1
fi

echo "Starting Android emulator:"
echo "  AVD_NAME=${AVD_NAME}"
echo "  ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT}"

exec "${EMULATOR_BIN}" -avd "${AVD_NAME}" -netdelay none -netspeed full

