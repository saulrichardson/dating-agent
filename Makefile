.PHONY: help setup emulator appium appium-driver appium-mcp hinge-mcp cli validate-control validate-llm-synthetic llm-regression long-horizon validate-system-synthetic

help:
	@echo "Concierge (Appium-first)"
	@echo ""
	@echo "  make setup          - Create venv and install Python deps"
	@echo "  make emulator       - Start Android emulator"
	@echo "  make appium-driver  - Install Appium UiAutomator2 driver"
	@echo "  make appium         - Start Appium server"
	@echo "  make appium-mcp     - Start Appium MCP server"
	@echo "  make hinge-mcp      - Start Hinge MCP control server"
	@echo "  make cli            - Run interactive mobile CLI"
	@echo "  make validate-control - Run no-device hinge control contract checks"
	@echo "  make validate-llm-synthetic - Run synthetic LLM suite (requires OPENAI_API_KEY)"
	@echo "  make llm-regression - Run offline regression dataset (requires OPENAI_API_KEY)"
	@echo "  make long-horizon   - Run long-horizon rollout simulation (requires OPENAI_API_KEY)"
	@echo "  make validate-system-synthetic - Aggregate suite: contract + synthetic + regression + rollouts"

setup:
	python3 -m venv venv
	. venv/bin/activate && pip install -r requirements.txt

emulator:
	./scripts/start-android-emulator.sh

appium-driver:
	./scripts/install-appium-uiautomator2.sh

appium:
	./scripts/start-appium-server.sh

appium-mcp:
	./scripts/start-appium-mcp.sh

hinge-mcp:
	./scripts/start-hinge-agent-mcp.sh

cli:
	. venv/bin/activate && python -m automation_service.cli

validate-control:
	. venv/bin/activate && python scripts/validate-hinge-control-contract.py

validate-llm-synthetic:
	. venv/bin/activate && python scripts/validate-llm-suite.py --config automation_service/mobile_examples/live_hinge_agent.llm.example.json --synthetic

llm-regression:
	. venv/bin/activate && python scripts/run-llm-regression.py --dataset datasets/hinge_llm_regression/cases.synthetic.v1.jsonl --include-screenshot --temperature 0 --baseline datasets/hinge_llm_regression/baselines/baseline_gpt-4.1-mini.jsonl

long-horizon:
	. venv/bin/activate && python scripts/validate-long-horizon.py --scenarios datasets/hinge_rollouts/scenarios.synthetic.v1.json --temperature 0

validate-system-synthetic:
	. venv/bin/activate && python scripts/validate-system-suite.py --run-synthetic --run-regression --regression-baseline datasets/hinge_llm_regression/baselines/baseline_gpt-4.1-mini.jsonl --run-long-horizon
