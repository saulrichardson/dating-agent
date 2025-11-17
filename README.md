# Concierge

Dating app automation with persona extraction and context management services.

## Services

This project includes two microservices:

- **Context Service** (`http://localhost:8080`) - Manages conversation context per user/match
- **Persona Service** (`http://localhost:8081`) - Extracts messaging style and generates replies

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

## Testing

Both services include unit and integration tests using pytest.

### Running Tests

**Context Service:**
```bash
cd context_service
source ../venv/bin/activate
make test
# or: pytest tests/ -v
```

**Persona Service:**
```bash
cd persona_service
source ../venv/bin/activate
make test
# or: pytest tests/ -v
```

### Test Coverage

- **Unit Tests**: Test individual components in isolation (e.g., storage logic)
- **Integration Tests**: Test API endpoints using Flask's test client

**Context Service** includes:
- 6 unit tests for storage operations
- 7 integration tests for API endpoints

**Persona Service** includes:
- 4 integration tests for API endpoints and validation

All tests use temporary files and isolated test clients, so they don't interfere with running services.

## Usage

**Important:** Always activate the virtual environment before running the script:

```bash
source venv/bin/activate
python test_bumble_playwright.py
```

## Deactivate

When you're done, deactivate the virtual environment:
```bash
deactivate
```

