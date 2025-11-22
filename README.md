# Concierge

Dating app automation with persona extraction and context management services.

## Services

This project includes three microservices:

- **Context Service** (`http://localhost:8080`) - Manages conversation context per user/match
- **Persona Service** (`http://localhost:8081`) - Extracts messaging style and provides context to Automation Service
- **Automation Service** (`http://localhost:8082`) - Playwright-based UI automation with CLI

### Quick Start (All Services)

```bash
make start
```

This will build and start both services. View logs with `make logs`.

### Individual Service Management

Each service can also be managed independently:

```bash
# Context Service
cd context_service && make start

# Persona Service  
cd persona_service && make start

# Automation Service
cd automation_service && make start
```

See `make help` for all available commands.

## Setup

1. Create a virtual environment:
```bash
python3 -m venv venv
```

2. Activate the virtual environment:
```bash
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Automation Service CLI

**Important:** Always activate the virtual environment before running:

```bash
source venv/bin/activate
python -m automation_service.cli
```

Or use the service directly:
```bash
cd automation_service && make start
```

## Deactivate

When you're done, deactivate the virtual environment:
```bash
deactivate
```

