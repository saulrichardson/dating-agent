.PHONY: help cli mcp

help:
	@echo "Automation Service (Appium-only)"
	@echo ""
	@echo "  make cli   - Run interactive Appium CLI"
	@echo "  make mcp   - Start Hinge MCP control server"

cli:
	python -m automation_service.cli

mcp:
	python -m automation_service.mobile.hinge_agent_mcp
