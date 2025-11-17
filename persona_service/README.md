# Persona Service

HTTP service for extracting messaging style from chat logs and generating replies.

## Quick Start

### Using Docker (Recommended)

```bash
make start
```

This will build and start the service at `http://localhost:5001`

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

### Generate Reply

```bash
POST /generate
Content-Type: application/json

{
  "persona": {...},
  "recent_messages": [
    {"text": "Hey!", "sender": "other"},
    {"text": "hi", "sender": "me"}
  ]
}
```

Returns: `{"reply": "..."}`

## Makefile Commands

- `make build` - Build Docker image
- `make up` - Start service
- `make down` - Stop service
- `make logs` - View logs
- `make restart` - Restart service
- `make clean` - Stop and remove volumes
- `make start` - Build and start (recommended)

