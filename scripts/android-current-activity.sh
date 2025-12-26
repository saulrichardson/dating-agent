#!/usr/bin/env bash
set -euo pipefail

# Prints the current foreground activity (best-effort) for the connected device/emulator.
#
# This is useful for filling in Appium capabilities:
# - appium:appPackage
# - appium:appActivity
#
# Usage:
#   ./scripts/android-current-activity.sh

if ! command -v adb >/dev/null 2>&1; then
  echo "ERROR: adb not found in PATH." 1>&2
  exit 1
fi

if ! adb get-state >/dev/null 2>&1; then
  echo "ERROR: No Android device/emulator detected by adb." 1>&2
  echo "Run: adb devices" 1>&2
  exit 1
fi

echo "Foreground activity (best-effort):"

# Android versions vary in which dumpsys line is present. Try several.
adb shell dumpsys activity activities 2>/dev/null | grep -m 1 -E "mResumedActivity" || true
adb shell dumpsys window windows 2>/dev/null | grep -m 1 -E "mCurrentFocus|mFocusedApp" || true
