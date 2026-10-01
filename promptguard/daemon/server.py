from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from promptguard.audit.logger import AuditLogger


DEFAULT_TTL_SECONDS = 5.0
TASK_TTL_SECONDS = 900.0


class State:
    def __init__(self, audit_path: Path):
        self.lock = threading.Lock()
        self.operations: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.placeholders: dict[str, dict[str, dict[str, int]]] = {}
        self.audit = AuditLogger(audit_path)

    def sweep(self) -> None:
        now = time.monotonic()
        with self.lock:
            expired = [key for key, value in self.operations.items() if value["expires_at"] <= now]
            for key in expired:
                operation = self.operations.pop(key)
                self.audit.write("operation_expired", session_id=operation["session_id"], turn_id=operation["turn_id"], operation_id=key, status="expired")
            stale_tasks = [key for key, value in self.tasks.items() if value["expires_at"] <= now]
            for key in stale_tasks:
                self.tasks.pop(key, None)
                self.placeholders.pop(key, None)


class Handler(BaseHTTPRequestHandler):
    server: "PromptGuardServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size).decode("utf-8") or "{}")

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self.server.state.sweep()
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if self.path == "/stats":
            with self.server.state.lock:
                return self._send(200, {"pending_operations": len(self.server.state.operations), "active_tasks": len(self.server.state.tasks)})
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        started = time.perf_counter()
        self.server.state.sweep()
        try:
            body = self._json()
            if self.path == "/task":
                session_id = str(body["session_id"])
                with self.server.state.lock:
                    self.server.state.tasks[session_id] = {
                        "turn_id": str(body.get("turn_id", "")),
                        "prompt": str(body.get("prompt", "")),
                        "expires_at": time.monotonic() + TASK_TTL_SECONDS,
                    }
                self.server.state.audit.write("task_stored", session_id=session_id, turn_id=str(body.get("turn_id", "")), status="ok", prompt_present=bool(body.get("prompt")), prompt_length=len(str(body.get("prompt", ""))))
                return self._send(200, {"ok": True})
            if self.path == "/register":
                command = body.get("command")
                if not isinstance(command, str) or not command:
                    return self._send(400, {"error": "invalid_command"})
                operation_id = str(uuid.uuid4())
                session_id, turn_id = str(body.get("session_id", "")), str(body.get("turn_id", ""))
                ttl = min(max(float(body.get("ttl_seconds", DEFAULT_TTL_SECONDS)), 0.05), 30.0)
                with self.server.state.lock:
                    task = self.server.state.tasks.get(session_id, {})
                    self.server.state.operations[operation_id] = {
                        "command": command,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "task_context": {"prompt": task.get("prompt", ""), "turn_id": task.get("turn_id", "")},
                        "expires_at": time.monotonic() + ttl,
                    }
                self.server.state.audit.write("operation_registered", session_id=session_id, turn_id=turn_id, operation_id=operation_id, status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 2))
                return self._send(200, {"operation_id": operation_id})
            if self.path == "/claim":
                operation_id = str(body.get("operation_id", ""))
                with self.server.state.lock:
                    operation = self.server.state.operations.pop(operation_id, None)
                if operation is None:
                    self.server.state.audit.write("operation_claim", operation_id=operation_id, status="missing")
                    return self._send(404, {"error": "missing_operation"})
                if operation["expires_at"] <= time.monotonic():
                    self.server.state.audit.write("operation_claim", session_id=operation["session_id"], turn_id=operation["turn_id"], operation_id=operation_id, status="expired")
                    return self._send(410, {"error": "expired_operation"})
                self.server.state.audit.write("operation_claim", session_id=operation["session_id"], turn_id=operation["turn_id"], operation_id=operation_id, status="claimed", latency_ms=round((time.perf_counter() - started) * 1000, 2))
                return self._send(200, {key: operation[key] for key in ("command", "session_id", "turn_id", "task_context")})
            if self.path == "/placeholder":
                session_id = str(body["session_id"])
                candidate_type = str(body["candidate_type"])
                digest = str(body["fingerprint"])
                with self.server.state.lock:
                    by_type = self.server.state.placeholders.setdefault(session_id, {}).setdefault(candidate_type, {})
                    if digest not in by_type:
                        by_type[digest] = len(by_type) + 1
                    index = by_type[digest]
                return self._send(200, {"placeholder": f"[{candidate_type}_{index}]"})
            if self.path == "/event":
                allowed = {"session_id", "turn_id", "operation_id", "status", "failure_kind", "latency_ms", "candidate_count", "candidate_types", "actions", "marker_present", "exit_code"}
                metadata = {key: value for key, value in body.items() if key in allowed}
                self.server.state.audit.write(str(body.get("event", "runtime_event")), **metadata)
                return self._send(200, {"ok": True})
            if self.path == "/shutdown":
                self.server.state.audit.write("daemon_stopped", status="ok")
                self._send(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._send(404, {"error": "not_found"})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._send(400, {"error": "bad_request"})


class PromptGuardServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], state: State):
        super().__init__(address, Handler)
        self.state = state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--audit-log", type=Path, default=Path(__file__).resolve().parents[1] / "runtime" / "audit.jsonl")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Demo v0 daemon must bind to loopback")
    state = State(args.audit_log)
    state.audit.write("daemon_started", status="ok", port=args.port)
    with PromptGuardServer((args.host, args.port), state) as server:
        server.serve_forever(poll_interval=0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
