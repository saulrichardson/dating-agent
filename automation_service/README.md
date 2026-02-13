# Automation Service (Appium-Only)

`automation_service` contains the native-mobile automation runtime used by this repo.

## Entrypoints

- CLI: `python -m automation_service.cli`
- Hinge MCP server: `python -m automation_service.mobile.hinge_agent_mcp`
- Live autonomous agent: `automation_service/mobile/live_hinge_agent.py`
- Full-fidelity extractor: `automation_service/mobile/full_fidelity_hinge.py`

## Scope

This package intentionally does **not** include:

- Playwright/browser automation
- Bumble web automation
- Legacy HTTP microservice APIs

All flows assume:

1. Android emulator/device is running.
2. Appium server is running.
3. App under test (e.g. Hinge) is installed and signed in.

## Local Install

From repo root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source venv/bin/activate
python -m automation_service.cli
```

## Key Paths

- `automation_service/mobile/appium_http_client.py`
- `automation_service/mobile/live_hinge_agent.py`
- `automation_service/mobile/hinge_agent_mcp.py`
- `automation_service/mobile/full_fidelity_hinge.py`
- `automation_service/mobile_examples/`
