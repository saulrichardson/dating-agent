#!/usr/bin/env bash
set -euo pipefail

# Starts the local Hinge Agent MCP server (stdio transport).
# This server keeps a live Appium session across tool calls so external agents
# can observe, decide, and execute without restarting the app every step.
#
# Usage:
#   ./scripts/start-hinge-agent-mcp.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

exec python -m automation_service.mobile.hinge_agent_mcp
