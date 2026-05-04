# Kokoro Web Frontend

Lightweight web UI for the JSON-backed conversation system.

Run it from the repository root:

```bash
.venv/bin/python -m web_frontend.server --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

The server uses the existing `.env` file and persists data through `conversation/data/*.json`.

