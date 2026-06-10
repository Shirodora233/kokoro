# Kokoro Web Frontend

Lightweight web UI for the PostgreSQL-backed conversation system.

Run it from the repository root:

```bash
.venv/bin/python -m web_frontend.server --port 8765
```

```bash
ssh -L 8765:127.0.0.1:8765 wsl-rm
```

Open:

```text
http://127.0.0.1:8765
```

The server uses the existing `.env` file and persists data through the PostgreSQL connection configured by `CONVERSATION_DATABASE_URL` or `DATABASE_URL`.
