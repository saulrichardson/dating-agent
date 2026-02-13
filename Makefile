.PHONY: help setup emulator appium appium-driver appium-mcp hinge-mcp cli

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
