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

# Android versions vary in which dumpsys line is present. Try several and also
# parse a package/activity component when possible.

line=""

line="$(adb shell dumpsys activity activities 2>/dev/null | grep -m 1 -E "topResumedActivity=|mTopResumedActivity=|mResumedActivity=|ResumedActivity:" || true)"
if [[ -n "${line}" ]]; then
  echo "${line}"
fi

win_line="$(adb shell dumpsys window windows 2>/dev/null | grep -m 1 -E "mCurrentFocus|mFocusedApp" || true)"
if [[ -n "${win_line}" ]]; then
  echo "${win_line}"
fi

# Fallback: some Android builds use `dumpsys window` (without `windows`).
if [[ -z "${win_line}" ]]; then
  win_line="$(adb shell dumpsys window 2>/dev/null | grep -m 1 -E "mCurrentFocus|mFocusedApp" || true)"
  if [[ -n "${win_line}" ]]; then
    echo "${win_line}"
  fi
fi

# Extract the first ComponentName-like token: package/activity
# Example: com.android.vending/com.google.android.finsky.unauthenticated.activity.UnauthenticatedMainActivity
component="$(printf "%s\n%s\n" "${line}" "${win_line}" | grep -oE '[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+' | head -n 1 || true)"
if [[ -n "${component}" ]]; then
  pkg="${component%%/*}"
  activity="${component#*/}"
  echo ""
  echo "Parsed (for Appium capabilities):"
  echo "  appium:appPackage=${pkg}"
  echo "  appium:appActivity=${activity}"
fi
