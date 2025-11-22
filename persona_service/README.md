# Persona Service

HTTP service for extracting messaging style from chat logs. Provides extracted persona to Automation Service via Context Service.

## Quick Start

### Using Docker (Recommended)

```bash
make start
```

This will build and start the service at `http://localhost:8081`

### Manual Start

```bash
pip install -r requirements.txt
python server.py
```

## API Endpoints

### Health Check

```bash
GET /health
```

Returns: `{"status": "ok"}`

### Extract Persona

```bash
POST /extract
Content-Type: application/json

{
  "chat_logs": [
    {"text": "hey how are you??", "sender": "me", "timestamp": 1000},
    {"text": "i'm good!", "sender": "me", "timestamp": 1005}
  ]
}
```

Returns: `{"persona": {...}}`

## How It Works

1. **Extract Persona**: Analyzes chat logs to extract messaging style (capitalization, punctuation, emoji usage, tone, etc.)
2. **Store in Context Service**: The extracted persona is stored in Context Service where Automation Service can access it
3. **Provide Context**: Automation Service retrieves the persona from Context Service to maintain consistent messaging style

## Makefile Commands

- `make build` - Build Docker image
- `make up` - Start service
- `make down` - Stop service
- `make logs` - View logs
- `make restart` - Restart service
- `make clean` - Stop and remove volumes
- `make start` - Build and start (recommended)

