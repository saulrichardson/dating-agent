# Hinge Autonomous Control Skill

## Purpose

Run an end-to-end Hinge automation loop with a single live Appium session:

1. Observe current profile/thread state.
2. Evaluate next action (like, pass, open_thread, send_message, navigation, back, wait).
3. Execute action.
4. Persist decision artifacts for downstream analysis.

This skill is optimized for coding agents that need both deterministic control and LLM-driven free-form behavior.

## Prerequisites

1. Android emulator running and unlocked.
2. Appium server running (`http://127.0.0.1:4723` by default).
3. Hinge installed and user signed in.
4. `OPENAI_API_KEY` set when using LLM mode.

## Core Files

- Live loop runner:
  - `automation_service/mobile/live_hinge_agent.py`
- MCP control plane (for external coding agents):
  - `automation_service/mobile/hinge_agent_mcp.py`
- MCP launcher:
  - `scripts/start-hinge-agent-mcp.sh`
- Example configs:
  - `automation_service/mobile_examples/live_hinge_agent.example.json`
  - `automation_service/mobile_examples/live_hinge_agent.llm.example.json`
  - `automation_service/mobile_examples/live_hinge_agent.autonomous_swipe.llm.example.json`
- Example personality specs:
  - `automation_service/mobile_examples/hinge_agent_profile.example.json`
  - `automation_service/mobile_examples/hinge_agent_profile.creative_playful.example.json`
  - `automation_service/mobile_examples/hinge_agent_profile.direct_intentional.example.json`

## Recommended Workflow

1. Validate locators with deterministic mode (`decision_engine.type=deterministic`, `dry_run=true`).
2. Enable packet artifacts (`persist_packet_log=true`, `packet_capture_screenshot=true`) and inspect output.
3. Switch to LLM mode and keep `llm_failure_mode=fallback_deterministic` until stable.
4. Move to `dry_run=false` only after action validation is consistently passing.

## Artifact Contract

The live agent writes:

- Action log JSON (`hinge_live_action_log_*.json`)
- Packet log JSONL (`hinge_live_packet_log_*.jsonl`)
- Optional packet screenshots/XML (`artifacts/.../decision_packets/`)
- Optional per-action screenshots (`capture_each_action=true`)

Use packet logs as the canonical downstream input because each row includes:

- `screen_type`
- `quality_score_v1`
- `quality_features`
- `available_actions`
- `decision`
- `message_text` (when applicable)
- paths to screenshot/XML artifacts (if enabled)

## MCP Mode (Free-Form Agents)

Start:

```bash
./scripts/start-hinge-agent-mcp.sh
```

Tool flow:

1. `start_session(config_json_path=...)`
2. `step(mode="llm", execute_action=true, ...)` repeatedly
3. `stop_session()`

Use `observe` + `execute` when a human/operator wants direct action control.

## Fail-Fast Guidance

- Never continue when package is not `co.hinge.app` unless explicitly intended.
- Keep `validation.max_consecutive_failures` low during live runs.
- If `send_message` fails on locators, stop and fix selectors before continuing.
- Prefer explicit errors to silent fallback behavior.
