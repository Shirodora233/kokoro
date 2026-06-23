"""Tiny HTTP server for the Kokoro web frontend."""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from conversation.service import ConversationService

STATIC_DIR = Path(__file__).resolve().parent


class KokoroRequestHandler(BaseHTTPRequestHandler):
    service: ConversationService

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api("GET", parsed.path, parse_qs(parsed.query))
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self._handle_api("POST", parsed.path, parse_qs(parsed.query))

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        self._handle_api("PATCH", parsed.path, parse_qs(parsed.query))

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self._handle_api("DELETE", parsed.path, parse_qs(parsed.query))

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _handle_api(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
    ) -> None:
        try:
            payload = self._read_json() if method in {"POST", "PATCH"} else {}
            response = self._route_api(method, path, query, payload)
            self._send_json(response)
        except NotImplementedError as error:
            self._send_json({"error": str(error)}, HTTPStatus.NOT_IMPLEMENTED)
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _route_api(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if method == "GET" and path == "/api/health":
            return {"ok": True}

        if method == "GET" and path == "/api/debug/memory":
            return {
                "memory": self.service.get_memory_debug_snapshot(
                    username=self._query_one(query, "username"),
                    session_id=self._query_one(query, "session_id"),
                    limit=self._query_int(query, "limit", 100),
                )
            }

        if method == "GET" and path == "/api/debug/memory/traces":
            return {
                "traces": self.service.list_memory_debug_traces(
                    session_id=self._query_one(query, "session_id"),
                    message_id=self._query_one(query, "message_id"),
                    limit=self._query_int(query, "limit", 20),
                )
            }

        trace_prefix = "/api/debug/memory/traces/"
        if method == "GET" and path.startswith(trace_prefix):
            trace_id = unquote(path.removeprefix(trace_prefix))
            return {
                "trace": self.service.get_memory_debug_trace(
                    trace_id,
                    include_raw=self._query_bool(query, "include_raw"),
                )
            }

        if method == "GET" and path == "/api/users":
            return {"users": [user.to_record() for user in self.service.list_users()]}

        if method == "POST" and path == "/api/users":
            username = self._require_text(payload, "username")
            display_name = self._optional_text(payload, "display_name")
            user = self.service.create_user(username, display_name=display_name)
            return {"user": user.to_record()}

        if method == "DELETE" and path.startswith("/api/users/"):
            username = unquote(path.removeprefix("/api/users/"))
            cascade = self._query_bool(query, "cascade")
            return {"deleted": self.service.delete_user_by_username(username, cascade=cascade)}

        if method == "GET" and path == "/api/sessions":
            username = self._query_one(query, "username")
            user_id = None
            if username:
                user = self.service.create_user(username)
                user_id = user.id
            sessions = self.service.list_sessions(user_id=user_id)
            return {"sessions": [session.to_record() for session in sessions]}

        if method == "POST" and path == "/api/sessions":
            username = self._require_text(payload, "username")
            title = self._optional_text(payload, "title") or "New chat"
            system_prompt = self._optional_text(payload, "system_prompt")
            user = self.service.create_user(username)
            session = self.service.start_session(
                user_id=user.id,
                title=title,
                system_prompt=system_prompt,
            )
            return {"session": session.to_record()}

        if method == "DELETE" and path == "/api/all":
            return {"deleted": self.service.delete_all()}

        session_messages_prefix = "/api/sessions/"
        if path.startswith(session_messages_prefix):
            suffix = path.removeprefix(session_messages_prefix)
            parts = suffix.split("/")
            session_id = unquote(parts[0])

            if len(parts) == 1 and method == "PATCH":
                title = self._require_text(payload, "title")
                session = self.service.rename_session(session_id, title)
                return {"session": session.to_record()}

            if len(parts) == 1 and method == "DELETE":
                return {"deleted": self.service.delete_session(session_id)}

            if len(parts) == 2 and parts[1] == "messages" and method == "GET":
                messages = self.service.get_transcript(session_id)
                return {"messages": [message.to_record() for message in messages]}

            if len(parts) == 2 and parts[1] == "checkpoints" and method == "GET":
                checkpoints = self.service.list_checkpoints(
                    session_id=session_id,
                    limit=self._query_int(query, "limit", 50),
                )
                return {
                    "checkpoints": [
                        checkpoint.to_record() for checkpoint in checkpoints
                    ]
                }

            if len(parts) == 2 and parts[1] == "turn-debug" and method == "GET":
                return {
                    "turn_debug": self.service.list_session_turn_debug(
                        session_id=session_id,
                        limit=self._query_int(query, "limit", 100),
                    )
                }

            if len(parts) == 2 and parts[1] == "branches" and method == "POST":
                checkpoint_id = self._require_text(payload, "checkpoint_id")
                title = self._optional_text(payload, "title")
                session = self.service.create_branch_from_checkpoint(
                    session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    title=title,
                )
                return {"session": session.to_record()}

            if len(parts) == 2 and parts[1] == "history" and method == "GET":
                page = self.service.get_session_history(
                    session_id=session_id,
                    page=self._query_int(query, "page", 1),
                    page_size=self._query_int(query, "page_size", 50),
                )
                return {"history": page.to_record()}

            if len(parts) == 2 and parts[1] == "context" and method == "GET":
                return {"context": self.service.get_model_context(session_id).to_record()}

            if len(parts) == 2 and parts[1] == "context" and method == "PATCH":
                context_start_index = int(payload.get("context_start_index", 0))
                session = self.service.set_context_start_index(
                    session_id=session_id,
                    context_start_index=context_start_index,
                )
                return {"session": session.to_record()}

            if len(parts) == 2 and parts[1] == "query" and method == "GET":
                message_query = self._query_one(query, "q")
                if not message_query:
                    raise ValueError("Missing required query parameter: q")
                page = self.service.query_session_messages(
                    session_id=session_id,
                    query=message_query,
                    page=self._query_int(query, "page", 1),
                    page_size=self._query_int(query, "page_size", 50),
                )
                return {"results": page.to_record()}

            if len(parts) == 2 and parts[1] == "messages" and method == "POST":
                content = self._require_text(payload, "content")
                username = self._optional_text(payload, "username")
                include_debug = (
                    self._query_bool(query, "debug")
                    or self._payload_bool(payload, "debug")
                )
                user_id = None
                if username:
                    user = self.service.create_user(username)
                    user_id = user.id
                do_not_remember = self._optional_bool(payload, "do_not_remember")
                user_message, assistant_message = self.service.send_message(
                    session_id=session_id,
                    content=content,
                    user_id=user_id,
                    idempotency_key=self._optional_text(payload, "idempotency_key"),
                    do_not_remember=do_not_remember,
                )
                response = {
                    "user_message": user_message.to_record(),
                    "assistant_message": assistant_message.to_record(),
                }
                if include_debug:
                    trace = self.service.memory_debug_trace_for_message(
                        session_id=session_id,
                        message_id=user_message.id,
                    )
                    response["memory_debug_trace"] = trace
                    response["memory_debug_trace_id"] = (
                        trace.get("trace_id") if trace else None
                    )
                return response

        # --- User-facing memory management ---
        if method == "GET" and path == "/api/memories":
            return self.service.list_memories(
                username=self._query_one(query, "username"),
                user_id=self._query_one(query, "user_id"),
                session_id=self._query_one(query, "session_id"),
                memory_type=self._query_one(query, "type"),
                limit=self._query_int(query, "limit", 100),
            )

        if method == "GET" and path.startswith("/api/memories/"):
            memory_id = unquote(path.removeprefix("/api/memories/"))
            return self.service.get_memory_detail(memory_id)

        if method == "DELETE" and path.startswith("/api/memories/"):
            memory_id = unquote(path.removeprefix("/api/memories/"))
            return self.service.forget_memory(memory_id)

        checkpoint_prefix = "/api/checkpoints/"
        if path.startswith(checkpoint_prefix):
            suffix = path.removeprefix(checkpoint_prefix)
            parts = suffix.split("/")
            checkpoint_id = unquote(parts[0])
            if len(parts) == 2 and parts[1] == "memory" and method == "GET":
                return {
                    "memory": self.service.get_checkpoint_memory(
                        checkpoint_id=checkpoint_id,
                        limit=self._query_int(query, "limit", 100),
                    )
                }
            if len(parts) == 1 and method == "PATCH":
                checkpoint = self.service.update_checkpoint(
                    checkpoint_id=checkpoint_id,
                    label=self._optional_text(payload, "label"),
                    metadata=payload.get("metadata")
                    if isinstance(payload.get("metadata"), dict)
                    else None,
                )
                return {"checkpoint": checkpoint.to_record()}

        raise ValueError(f"Unsupported route: {method} {path}")

    def _serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            request_path = "/index.html"
        relative = request_path.removeprefix("/")
        file_path = (STATIC_DIR / relative).resolve()
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR:
            self._send_json({"error": "Invalid static path"}, HTTPStatus.BAD_REQUEST)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(file_path.suffix, "application/octet-stream")

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _query_one(self, query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key)
        if not values:
            return None
        value = values[0].strip()
        return value or None

    def _query_bool(self, query: dict[str, list[str]], key: str) -> bool:
        value = (self._query_one(query, key) or "").lower()
        return value in {"1", "true", "yes", "on"}

    def _payload_bool(self, payload: dict[str, Any], key: str) -> bool:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _query_int(
        self,
        query: dict[str, list[str]],
        key: str,
        default: int,
    ) -> int:
        value = self._query_one(query, key)
        if value is None:
            return default
        return int(value)

    def _require_text(self, payload: dict[str, Any], key: str) -> str:
        value = self._optional_text(payload, key)
        if not value:
            raise ValueError(f"Missing required field: {key}")
        return value

    def _optional_text(self, payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _optional_bool(self, payload: dict[str, Any], key: str) -> bool:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Kokoro web frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env-file", default=str(ROOT_DIR / ".env"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    KokoroRequestHandler.service = ConversationService.default(
        env_file=Path(args.env_file),
    )
    server = ThreadingHTTPServer((args.host, args.port), KokoroRequestHandler)
    print(f"Serving Kokoro web frontend at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
