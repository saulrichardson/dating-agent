# Context Service

Minimal service for tracking conversation context per user per match.

## Prerequisites

- [Colima](https://github.com/abiosoft/colima) (or Docker Desktop)
- Docker and Docker Compose

### Installing Colima

```bash
brew install colima
colima start
```

## Running the Service

### Option 1: Docker Compose (Recommended)

**Start the service:**
```bash
docker compose up -d
```

**View logs:**
```bash
docker compose logs -f
```

**Stop the service:**
```bash
docker compose down
```

**Rebuild and restart:**
```bash
docker compose down
docker compose up -d --build
```

The service will be available at `http://localhost:8080`

### Option 2: Using Make

**Start the service:**
```bash
make start
```

**View logs:**
```bash
make logs
```

**Stop the service:**
```bash
make down
```

### Option 3: Local Python

**Start the server:**
```bash
pip install -r requirements.txt
python server.py
```

The service will be available at `http://localhost:5000`

## Storage

Uses a simple file-based JSON storage (`context_storage.json`) with keys in the format:
```
{user_id}:{match_id} -> context_string
```

## API Endpoints

- `GET /health` - Health check
- `GET /context/<user_id>/<match_id>` - Get context for a user-match pair
- `POST /context/<user_id>/<match_id>` - Set context for a user-match pair
- `PUT /context/<user_id>/<match_id>` - Set context for a user-match pair
- `DELETE /context/<user_id>/<match_id>` - Delete context for a user-match pair
- `GET /context/<user_id>` - Get all contexts for a user

## Testing the Service

### Health Check

```bash
curl http://localhost:8080/health
```

Expected response:
```json
{"status": "ok"}
```

### Example Requests

**Set context:**
```bash
curl -X POST http://localhost:8080/context/user123/match456 \
  -H "Content-Type: application/json" \
  -d '{"context": {"messages": ["Hello", "How are you?"], "timestamp": "2025-11-16T10:00:00Z"}}'
```

**Get context:**
```bash
curl http://localhost:8080/context/user123/match456
```

**Get all contexts for a user:**
```bash
curl http://localhost:8080/context/user123
```

**Delete context:**
```bash
curl -X DELETE http://localhost:8080/context/user123/match456
```

**Update context (PUT):**
```bash
curl -X PUT http://localhost:8080/context/user123/match456 \
  -H "Content-Type: application/json" \
  -d '{"context": {"messages": ["Updated message"], "timestamp": "2025-11-16T11:00:00Z"}}'
```

> **Note:** When running locally (Option 3), use port `5000` instead of `8080`.

## Direct Storage Usage

You can also use the storage directly without the server:

```python
from storage import ContextStorage

storage = ContextStorage()
storage.set_context("user123", "match456", "Some context string...")
context = storage.get_context("user123", "match456")
```

