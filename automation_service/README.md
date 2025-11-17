# Automation Service

HTTP service and CLI for dating app UI automation using Playwright.

## Quick Start

### Using Docker (Recommended)

```bash
make start
```

This will build and start the service at `http://localhost:8082`

### Manual Start

```bash
pip install -r requirements.txt
playwright install chromium
python server.py
```

### CLI Usage

```bash
python cli.py
```

Or from the project root:
```bash
python -m automation_service.cli
```

## API Endpoints

### Health Check

```bash
GET /health
```

Returns: `{"status": "ok"}`

### Save Authentication State

```bash
POST /auth/save
```

Starts the authentication save process in the background.

### Test Chat Flow

```bash
POST /chat/test
```

Starts the chat flow test in the background.

### Extract Chat History

```bash
POST /chat/extract
Content-Type: application/json

{
  "user_id": "default"
}
```

Starts chat history extraction and persona upload.

## Makefile Commands

- `make build` - Build Docker image
- `make up` - Start service
- `make down` - Stop service
- `make logs` - View logs
- `make restart` - Restart service
- `make clean` - Stop and remove volumes
- `make start` - Build and start (recommended)

